"""
內部人持股（公司派／大股東）scraper — 公開資訊觀測站每月更新。
抓董事/監察人/經理人（公司派）與大股東(10%+) 的持股與設質(質押)比例。
"""
import logging
import random
import re
import time
from typing import Optional

import duckdb
import requests

logger = logging.getLogger(__name__)

_URL = "https://mopsov.twse.com.tw/mops/web/ajax_stapap1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}
_DB_PATH = "data/screener.db"

_MAX_RETRIES = 3
_RETRY_BACKOFF = (3.0, 7.0)
_JITTER = 0.8

# MOPS 是滾動時間窗限流（一段時間內請求太多會暫時擋，過一陣子自己解除），不是永久封鎖，
# 偵測到擋頁時用比一般網路錯誤更長的退避，讓時間窗有機會重置（2026-07-06 實測：一般 3-7 秒
# 退避不夠，擋住的窗口會持續數十支股票）。
_BLOCK_BACKOFF = (20.0, 40.0)

_ROW_RE = re.compile(r"<TR class=['\"](?:odd|even)['\"]>(.*?)</TR>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<TD[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_DATE_RE = re.compile(r"資料年月[:：](\d{5})")


class MOPSBlockedError(RuntimeError):
    """MOPS 回傳資安擋頁（WAF block／時間窗限流），不是合法的『查無資料』回應。"""


def _check_mops_response(resp) -> None:
    """偵測 MOPS 擋頁：合法回應（含『查無資料』在內）一律是 status 200；
    擋頁是 307 導向，內容含『安全性考量』/『SECURITY REASONS』字樣
    （2026-07-06 實測擋頁內容，不是臆測）。"""
    if resp.status_code != 200 or "安全性考量" in resp.text or "SECURITY REASONS" in resp.text:
        raise MOPSBlockedError(
            f"MOPS 疑似限流/封鎖此 IP（status={resp.status_code}），並非資料查無"
        )

# 大股東/未分類職稱一律歸「大股東」桶；董事/監察人/經理人相關頭銜歸「公司派」桶
_COMPANY_KEYWORDS = ("董事", "監察人", "經理", "協理", "主管")


def _to_int(text: str) -> int:
    text = text.strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        # 非數字（如 '-'／'－'／'N/A'）視為 0，避免單一 cell 解析失敗讓整支股票被當抓取
        # 失敗而靜默消失（「不報錯但漏資料」）——Debugger 2026-07-06 回報的 🟡
        return 0


def _classify_role(title: str) -> str:
    if "大股東" in title:
        return "major_holder"
    if any(kw in title for kw in _COMPANY_KEYWORDS):
        return "company"
    return "major_holder"  # 「其他」等未分類頭銜，預設歸大股東桶


def _parse_response(html: str) -> Optional[dict]:
    if "查無" in html:
        return None

    date_m = _DATE_RE.search(html)
    if not date_m:
        return None
    roc = date_m.group(1)
    year_ad = int(roc[:3]) + 1911
    month = int(roc[3:])
    report_date = f"{year_ad:04d}-{month:02d}-01"

    company_shares = 0
    company_pledge = 0
    major_shares = 0
    major_pledge = 0

    for row_html in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row_html)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(cells) != 9:
            continue
        title = cells[0]
        current_shares = _to_int(cells[3])
        pledge_shares = _to_int(cells[4])
        related_shares = _to_int(cells[6])
        related_pledge = _to_int(cells[7])

        bucket = _classify_role(title)
        shares = current_shares + related_shares
        pledge = pledge_shares + related_pledge
        if bucket == "company":
            company_shares += shares
            company_pledge += pledge
        else:
            major_shares += shares
            major_pledge += pledge

    return {
        "report_date": report_date,
        "company_shares": company_shares,
        "company_pledge_shares": company_pledge,
        "major_holder_shares": major_shares,
        "major_holder_pledge_shares": major_pledge,
    }


def _fetch_one_stock(stock_id: str) -> Optional[dict]:
    data = {
        "step": "1", "firstin": "true", "off": "1",
        "keyword4": "", "code1": "", "TYPEK2": "", "checkbtn": "",
        "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
        "isnew": "true", "co_id": stock_id, "year": "", "month": "",
    }
    # 注意：不要在這裡 catch POST 的例外——讓例外往上冒給呼叫端的重試迴圈接住重打
    # （比照 shareholder.py 修過的教訓，內層吞例外會讓外層重試機制形同虛設）
    r = requests.post(_URL, data=data, headers=_HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    _check_mops_response(r)  # 擋頁不會被 raise_for_status() 攔到（307 不是 4xx/5xx），要另外查
    return _parse_response(r.text)


def fetch_insider_holdings_monthly(stock_ids: list[str], delay: float = 1.0) -> tuple[list[dict], list[str]]:
    """抓一批股票最新一期的內部人持股資料。
    回傳 (results, blocked_ids)：
      results     — 成功解析到資料的 list of dict
      blocked_ids — 3 次重試都被 MOPS 擋掉（不是真的查無資料）的股票代號，
                    呼叫端可以之後單獨針對這批重跑，不要跟「真的沒有揭露資料」混在一起看。
    """
    import warnings
    warnings.filterwarnings("ignore")

    logger.info("內部人持股更新，共 %d 支股票", len(stock_ids))
    results = []
    blocked_ids: list[str] = []
    no_data = 0  # 真的解析不到資料（合法回應但查無揭露），跟被擋分開計數

    for i, sid in enumerate(stock_ids, 1):
        rec = None
        ok = False
        blocked = False
        for attempt in range(_MAX_RETRIES):
            try:
                rec = _fetch_one_stock(sid)
                ok = True
                break
            except MOPSBlockedError as e:
                blocked = True
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(random.uniform(*_BLOCK_BACKOFF))  # 滾動限流，退避久一點等它自己解除
                else:
                    logger.warning("  [%d] 被 MOPS 擋掉（重試 %d 次仍被擋）: %s，跳過 %s",
                                   i, _MAX_RETRIES, e, sid)
            except Exception as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(random.uniform(*_RETRY_BACKOFF))
                else:
                    logger.warning("  [%d] 抓取失敗（重試 %d 次）: %s，跳過 %s",
                                   i, _MAX_RETRIES, e, sid)
        if not ok:
            if blocked:
                blocked_ids.append(sid)
            else:
                no_data += 1
            time.sleep(delay + random.uniform(0, _JITTER))
            continue

        if rec:
            rec["stock_id"] = sid
            results.append(rec)
        else:
            no_data += 1

        if i % 50 == 0 or i == len(stock_ids):
            logger.info("  [%d/%d] 成功 %d，查無資料 %d，被擋 %d",
                        i, len(stock_ids), len(results), no_data, len(blocked_ids))

        time.sleep(delay + random.uniform(0, _JITTER))

    if blocked_ids:
        logger.warning(
            "本次有 %d 支股票因 MOPS 限流被擋（非真正查無資料），建議稍後單獨重跑這批：%s",
            len(blocked_ids),
            blocked_ids[:20] + (["..."] if len(blocked_ids) > 20 else []),
        )

    return results, blocked_ids


def save_to_db(rows: list[dict], db_path: str = _DB_PATH) -> int:
    """upsert 內部人持股到 DuckDB insider_holdings 表，算出月變化，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd

    con = duckdb.connect(db_path)
    sids = [r["stock_id"] for r in rows]
    write_date = max(r["report_date"] for r in rows)
    prev_rows = con.execute("""
        SELECT stock_id, company_shares, major_holder_shares
        FROM insider_holdings
        WHERE stock_id IN (SELECT UNNEST(?)) AND report_date < ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY report_date DESC) = 1
    """, [sids, write_date]).df()
    prev_map = {r["stock_id"]: r for _, r in prev_rows.iterrows()} if not prev_rows.empty else {}

    out_rows = []
    for r in rows:
        company_shares = r["company_shares"]
        major_shares = r["major_holder_shares"]
        company_pledge_pct = (
            round(r["company_pledge_shares"] / company_shares * 100, 4) if company_shares > 0 else None
        )
        major_holder_pledge_pct = (
            round(r["major_holder_pledge_shares"] / major_shares * 100, 4) if major_shares > 0 else None
        )
        prev = prev_map.get(r["stock_id"])
        company_chg = int(company_shares - prev["company_shares"]) if prev is not None else None
        major_holder_chg = int(major_shares - prev["major_holder_shares"]) if prev is not None else None

        out_rows.append({
            "stock_id": r["stock_id"],
            "report_date": r["report_date"],
            "company_shares": company_shares,
            "company_chg": company_chg,
            "company_pledge_pct": company_pledge_pct,
            "major_holder_shares": major_shares,
            "major_holder_chg": major_holder_chg,
            "major_holder_pledge_pct": major_holder_pledge_pct,
        })

    df = pd.DataFrame(out_rows)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    con.execute("DELETE FROM insider_holdings WHERE (stock_id, report_date) IN (SELECT stock_id, report_date FROM df)")
    con.execute("""
        INSERT INTO insider_holdings
        SELECT stock_id, report_date, company_shares, company_chg, company_pledge_pct,
               major_holder_shares, major_holder_chg, major_holder_pledge_pct
        FROM df
    """)
    n = len(df)
    con.close()
    return n
