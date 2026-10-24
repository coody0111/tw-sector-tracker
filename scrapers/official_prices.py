"""
官方逐日全市場行情回補（實際成交價）：一天抓兩次——上市 TWSE MI_INDEX、上櫃 TPEx 每日收盤行情。

為什麼（2026-10-24）：Yahoo 就算 auto_adjust=False，配股／減資／面額變更事件之前的價格仍被分割調整
（bug-reports：6415 2020-01-02 Yahoo 256.25 vs 官方 1025），Cody 決定行情改走官方來源重建。
逐股逐月的 STOCK_DAY 要 4 萬多次請求，逐日全市場 82 個月約 3,300 次。

設計：
- 由舊到新逐日處理，每天抓完立刻寫 data/daily_prices/<日期>.csv（整檔覆寫、只留股票池），
  CSV 多一欄 source=official（匯入 SQL 是指定欄位，不受影響）。
- 可中斷續跑：當天 CSV 已是 source=official 就跳過；被擋（TWSEBlockedError／TPExBlockedError）就停，
  已寫的保留，下次重跑接著做。
- 兩個市場都回「不是這天的資料」→ 休市：刪掉那天既有的 CSV（之前寫進去的複本或 Yahoo 佔位列）。
- 無成交（收盤 '--'）的股票不寫列（停牌期間不再出現假列）。
- 漲跌：官方有正負號就用官方（以參考價為基準）。除權息日官方不給數字（上市 'X'、上櫃 '除息'）：
  上櫃用前一天的「次日參考價」算（參考價口徑，CSV 多存一欄 next_ref）；上市 MI_INDEX 沒有參考價，
  只能用前一交易日收盤反推（前收口徑，跟官方差約 0.3 個百分點，高殖利率股更多）。
- 休市判斷以交易日行事曆為準：官方兩邊都回空、但行事曆說是交易日（還沒公布或 API 偶發空回應）就不刪。
"""
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import urllib3

from scrapers.chips import (
    TPExBlockedError,
    TWSEBlockedError,
    _HEADERS_TPEX,
    _HEADERS_TWSE,
    _check_twse_response,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_DAILY_QUOTES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
SOURCE_TAG = "official"


def _num(val) -> float | None:
    """'1,234.5' → 1234.5；'--'、空字串、HTML 殘骸等回 None。"""
    s = re.sub(r"<[^>]*>", "", str(val)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _row(sid, name, open_, high, low, close, change, volume_shares, next_ref=None) -> dict:
    return {
        "stock_id": sid, "stock_name": name,
        "open": open_, "high": high, "low": low, "close": close,
        "change": change, "volume": int(volume_shares or 0) // 1000, "next_ref": next_ref,
    }


def parse_twse_mi_index(data: dict, trade_date: date) -> list | None:
    """MI_INDEX（type=ALLBUT0999）→ 個股列；回應不是這天（休市）回 None。
    依欄位名稱找「每日收盤行情」那張表，欄位變動時拋 ValueError。"""
    if data.get("stat") != "OK" or str(data.get("date", "")) != trade_date.strftime("%Y%m%d"):
        return None
    tables = data.get("tables") or []
    table = next((t for t in tables if "證券代號" in (t.get("fields") or []) and "收盤價" in t["fields"]), None)
    if table is None:
        raise ValueError(f"MI_INDEX {trade_date}：找不到個股收盤行情表")
    f = {name: i for i, name in enumerate(table["fields"])}
    need = ["證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"]
    missing = [n for n in need if n not in f]
    if missing:
        raise ValueError(f"MI_INDEX {trade_date}：缺欄位 {missing}")
    rows = []
    for r in table.get("data") or []:
        close = _num(r[f["收盤價"]])
        if close is None or close <= 0:
            continue  # 無成交
        sign_raw = re.sub(r"<[^>]*>", "", str(r[f["漲跌(+/-)"]])).strip()
        diff = _num(r[f["漲跌價差"]])
        if "X" in sign_raw.upper() or diff is None:
            change = None  # 除權息：交給前一日收盤反推
        else:
            change = -diff if "-" in sign_raw else diff
        rows.append(_row(
            str(r[f["證券代號"]]).strip(), str(r[f["證券名稱"]]).strip(),
            _num(r[f["開盤價"]]), _num(r[f["最高價"]]), _num(r[f["最低價"]]), close,
            change, _num(r[f["成交股數"]]),
        ))
    return rows


def parse_tpex_daily_quotes(data: dict, trade_date: date) -> list | None:
    """TPEx 每日收盤行情 → 個股列；回應不是這天（休市）回 None。依欄位名稱取值，欄位變動時拋 ValueError。"""
    if str(data.get("stat", "")).lower() != "ok" or str(data.get("date", "")) != trade_date.strftime("%Y%m%d"):
        return None
    tables = data.get("tables") or []
    if not tables or not tables[0].get("data"):
        return None
    fields = [re.sub(r"\s", "", str(x)) for x in (tables[0].get("fields") or [])]
    f = {name: i for i, name in enumerate(fields)}
    need = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "成交股數"]
    missing = [n for n in need if n not in f]
    if missing:
        raise ValueError(f"TPEx 每日收盤行情 {trade_date}：缺欄位 {missing}（實際 {fields}）")
    i_ref = f.get("次日參考價")
    rows = []
    for r in tables[0]["data"]:
        close = _num(r[f["收盤"]])
        if close is None or close <= 0:
            continue
        rows.append(_row(
            str(r[f["代號"]]).strip(), str(r[f["名稱"]]).strip(),
            _num(r[f["開盤"]]), _num(r[f["最高"]]), _num(r[f["最低"]]), close,
            _num(r[f["漲跌"]]), _num(r[f["成交股數"]]),
            _num(r[i_ref]) if i_ref is not None else None,
        ))
    return rows


def fetch_twse_day(trade_date: date) -> list | None:
    resp = requests.get(
        TWSE_MI_INDEX_URL,
        params={"date": trade_date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
        headers=_HEADERS_TWSE, timeout=30, verify=False,
    )
    _check_twse_response(resp)
    return parse_twse_mi_index(resp.json(), trade_date)


def fetch_tpex_day(trade_date: date) -> list | None:
    resp = requests.get(
        TPEX_DAILY_QUOTES_URL,
        params={"date": trade_date.strftime("%Y/%m/%d"), "response": "json"},
        headers=_HEADERS_TPEX, timeout=30, verify=False,
    )
    ctype = resp.headers.get("Content-Type", "")
    if resp.status_code != 200 or "json" not in ctype.lower():
        raise TPExBlockedError(f"TPEx 疑似封鎖（status={resp.status_code}, content-type={ctype!r}）")
    return parse_tpex_daily_quotes(resp.json(), trade_date)


def _is_official_csv(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        df = pd.read_csv(path, usecols=lambda c: c == "source", dtype=str)
    except (ValueError, pd.errors.EmptyDataError):
        return False
    return "source" in df.columns and not df.empty and (df["source"] == SOURCE_TAG).all()


def _base_from_csv(path: Path) -> dict:
    """某天 CSV → {stock_id: 隔天漲跌基準}：有次日參考價用參考價，沒有用收盤。"""
    df = pd.read_csv(path, dtype={"stock_id": str})
    base = dict(zip(df["stock_id"], df["close"]))
    if "next_ref" in df.columns:
        base.update({k: v for k, v in zip(df["stock_id"], df["next_ref"]) if pd.notna(v) and v > 0})
    return base


def _prev_bases(output_dir: Path, before: date) -> dict:
    """續跑時：取 before 之前最近一個 CSV，當除權息日算漲跌的基準。"""
    earlier = sorted(p for p in output_dir.glob("*.csv") if p.stem < before.isoformat())
    return _base_from_csv(earlier[-1]) if earlier else {}


def _bases_from_rows(rows: list) -> dict:
    return {r["stock_id"]: (r.get("next_ref") or r["close"]) for r in rows}


def finalize_rows(rows: list, prev_base: dict, universe: set) -> list:
    """只留股票池；補上缺的漲跌（前一天的次日參考價，沒有就前一日收盤）並算漲跌幅。回傳新 list，不改 rows。"""
    out = []
    for r in rows:
        if r["stock_id"] not in universe:
            continue
        change = r["change"]
        prev = prev_base.get(r["stock_id"])
        if change is None:
            change = round(r["close"] - prev, 2) if prev else 0.0
        base = r["close"] - change
        out.append({
            **r,
            "change": change,
            "change_pct": round(change / base * 100, 2) if base else 0.0,
            "source": SOURCE_TAG,
        })
    return out


def backfill_official_prices(
    stock_ids: list,
    start: date,
    end: date = None,
    output_dir: str = "data/daily_prices",
    sleep_sec: float = 4.0,
) -> dict:
    """由 start 到 end 逐日抓官方全市場行情寫 CSV。回傳 {"written", "skipped", "holidays", "partial", "stopped"}。"""
    from config import is_trading_day
    from scrapers.backfill import backup_price_csvs

    end = end or date.today() - timedelta(days=1)  # 今天收盤資料可能還沒公布
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = set(stock_ids)
    # 會逐日覆寫既有 CSV，先整份複製一份；已經有官方 CSV 代表是續跑，不再備份
    # （每次都備份會把「開跑前的原始狀態」輪替掉，備份只留最近幾份）
    if not any(_is_official_csv(p) for p in out_dir.glob("*.csv")):
        backup_price_csvs(out_dir)
    prev_close = _prev_bases(out_dir, start)
    stats = {"written": 0, "skipped": 0, "holidays": 0, "partial": 0, "stopped": None}

    d = start
    while d <= end:
        path = out_dir / f"{d.isoformat()}.csv"
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        if _is_official_csv(path):
            prev_close.update(_base_from_csv(path))
            stats["skipped"] += 1
            d += timedelta(days=1)
            continue
        try:
            twse = fetch_twse_day(d)
            time.sleep(sleep_sec)
            tpex = fetch_tpex_day(d)
        except (TWSEBlockedError, TPExBlockedError) as exc:
            logger.error("官方行情被擋，停在 %s（已寫的保留，重跑會接著做）：%s", d.isoformat(), exc)
            stats["stopped"] = d.isoformat()
            break
        if twse is None and tpex is None and is_trading_day(d.isoformat()):
            logger.warning("%s 官方兩邊都沒資料，但行事曆是交易日（尚未公布或偶發空回應），不動既有 CSV", d.isoformat())
            stats["partial"] += 1
        elif twse is None and tpex is None:
            if path.exists():
                path.unlink()
                logger.info("%s 休市，刪除既有 CSV（複本或 Yahoo 佔位列）", d.isoformat())
            stats["holidays"] += 1
        elif twse is None or tpex is None:
            # 兩市場休市日相同，只有一邊有資料代表另一邊這次沒抓到：不寫（寫了會被標成官方而永遠不重抓）
            logger.warning("%s 只有%s有資料，這天先不寫，重跑時再抓", d.isoformat(), "上櫃" if twse is None else "上市")
            prev_close.update(_bases_from_rows(twse or tpex))
            stats["partial"] += 1
        else:
            rows = finalize_rows(twse + tpex, prev_close, universe)
            pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
            prev_close.update(_bases_from_rows(rows))
            stats["written"] += 1
            if stats["written"] % 20 == 0:
                logger.info("官方行情：已寫到 %s（%d 天）", d.isoformat(), stats["written"])
        time.sleep(sleep_sec)
        d += timedelta(days=1)
    logger.info("官方行情回補結束：寫入 %d 天、已是官方跳過 %d 天、休市 %d 天、只抓到一邊 %d 天%s",
                stats["written"], stats["skipped"], stats["holidays"], stats["partial"],
                f"、被擋停在 {stats['stopped']}" if stats["stopped"] else "")
    return stats
