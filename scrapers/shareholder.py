"""
集保持股分散表 scraper — TDCC 每週五更新一次
抓各股 ≥400張 大戶持股比例，計算週變化與連增/連減週數。
"""
import logging
import random
import re
import time
from datetime import date, datetime
from typing import Optional

import duckdb
import requests

logger = logging.getLogger(__name__)

_TDCC_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": _TDCC_URL,
}
# 等級 12-15 代表持股 ≥ 400,001 股（≥ 400張）
_LARGE_HOLDER_LEVELS = {"12", "13", "14", "15"}
_DB_PATH = "data/screener.db"

# 防封鎖／容錯（比照 backfill_yfinance 的手法）：暫時性 SSL 斷線/限流時退避重試，
# 每支之間隨機延遲而非固定間隔。
_MAX_RETRIES = 3
_RETRY_BACKOFF = (3.0, 7.0)   # 重試前隨機退避秒數
_JITTER = 0.8                 # 每支請求間隔的隨機抖動上限（秒）


def _get_session_tokens() -> tuple[requests.Session, str, str, list[str]]:
    """建立 TDCC session，回傳 (session, SYNCHRONIZER_TOKEN, SYNCHRONIZER_URI, available_dates)。"""
    s = requests.Session()
    r = s.get(_TDCC_URL, headers=_HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    tok = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', r.text).group(1)
    uri = re.search(r'name="SYNCHRONIZER_URI"\s+value="([^"]+)"', r.text).group(1)
    dates = re.findall(r'<option value="(\d{8})"', r.text)
    return s, tok, uri, dates


def _fetch_one_stock(s: requests.Session, tok: str, uri: str, stock_id: str, date_str: str) -> Optional[dict]:
    """抓單支股票的持股分散表，回傳 {lv12_15_shares, lv12_15_cnt, total_shares, total_cnt}。"""
    data = {
        "SYNCHRONIZER_TOKEN": tok,
        "SYNCHRONIZER_URI": uri,
        "method": "submit",
        "firDate": date_str,
        "scaDate": date_str,
        "sqlMethod": "StockNo",
        "stockNo": stock_id,
        "stockName": "",
    }
    # 注意：這裡刻意不 catch POST 的例外——讓 SSLError/ConnectionError/Timeout 等
    # 暫時性網路錯誤往上冒給 fetch_shareholder_weekly() 的重試迴圈接住重打。
    # 如果在這裡 catch 掉直接 return None，外層的 try/except 永遠看不到例外，
    # `ok=True` 會在第一次嘗試就成立、重試機制形同虛設（實際發生過的 bug）。
    r = s.post(_TDCC_URL, data=data, headers=_HEADERS, timeout=30, verify=False)
    r.raise_for_status()

    # 解析 table（第二個 table 是資料表）
    tables = re.findall(r"<table[^>]*>(.*?)</table>", r.text, re.DOTALL)
    if len(tables) < 2:
        return None

    cells = re.findall(r"<td[^>]*>(.*?)</td>", tables[1], re.DOTALL)
    cleaned = [re.sub(r"<[^>]+>", "", c).strip().replace(",", "") for c in cells]

    # 每列 5 欄：序號, 持股範圍, 人數, 股數, 占比
    rows = [cleaned[i:i+5] for i in range(0, len(cleaned), 5) if len(cleaned[i:i+5]) == 5]
    if not rows:
        return None

    lv_shares = 0
    lv_cnt = 0
    total_shares = 0
    total_cnt = 0

    for row in rows:
        level, _range, cnt_str, shares_str, _pct = row
        try:
            cnt = int(cnt_str) if cnt_str else 0
            shares = int(shares_str) if shares_str else 0
        except ValueError:
            continue

        if "合" in _range:  # 合計行（有些股票有差異數調整使合計變第17行）
            total_shares = shares
            total_cnt = cnt
        elif level in _LARGE_HOLDER_LEVELS:
            lv_shares += shares
            lv_cnt += cnt

    if total_shares == 0:
        return None

    return {
        "lv12_15_shares": lv_shares,
        "lv12_15_cnt": lv_cnt,
        "total_shares": total_shares,
        "total_cnt": total_cnt,
        "lv12_15_pct": round(lv_shares / total_shares * 100, 4),
    }


def fetch_shareholder_weekly(
    stock_ids: list[str],
    date_str: Optional[str] = None,
    delay: float = 1.2,
) -> list[dict]:
    """
    抓一批股票在指定週的持股分散表。
    date_str: 'YYYYMMDD'，None 則自動用最新可查日期。
    回傳 list of {stock_id, date, lv12_15_pct, lv12_15_cnt, total_shares}

    注意：TDCC 的 SYNCHRONIZER_TOKEN 是一次性的，每筆 POST 都需要先 GET 取新 token，
    因此每支股票實際上打 2 次請求（GET + POST）。
    """
    import warnings
    warnings.filterwarnings("ignore")

    # 先取一次確認 target_date
    _, _, _, available_dates = _get_session_tokens()
    if not available_dates:
        raise RuntimeError("無法取得 TDCC 可查日期")

    target_date = date_str or available_dates[0]
    if target_date not in available_dates:
        logger.warning("TDCC: %s 不在可查日期內，改用最新 %s", target_date, available_dates[0])
        target_date = available_dates[0]

    logger.info("集保持股分散表 %s，共 %d 支股票（每支 2 requests）", target_date, len(stock_ids))
    results = []
    failed = 0

    for i, sid in enumerate(stock_ids, 1):
        # 每支重新取 token（TDCC token 一次性）+ 抓資料，包在重試裡：
        # TDCC 偶發 SSL 斷線/限流是暫時性的，退避重試幾次幾乎都能救回，
        # 不要一失敗就跳過（原本零重試，穩定失敗 ~2.4%/週）。
        rec = None
        ok = False
        for attempt in range(_MAX_RETRIES):
            try:
                s, tok, uri, _ = _get_session_tokens()
                rec = _fetch_one_stock(s, tok, uri, sid, target_date)
                ok = True
                break
            except Exception as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(random.uniform(*_RETRY_BACKOFF))  # 退避後重試
                else:
                    logger.warning("  [%d] 抓取失敗（重試 %d 次）: %s，跳過 %s",
                                   i, _MAX_RETRIES, e, sid)
        if not ok:
            failed += 1
            time.sleep(delay + random.uniform(0, _JITTER))
            continue

        if rec:
            rec["stock_id"] = sid
            rec["date"] = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
            results.append(rec)
        else:
            failed += 1
            logger.debug("  [%d/%d] %s 無資料", i, len(stock_ids), sid)

        if i % 50 == 0 or i == len(stock_ids):
            logger.info("  [%d/%d] 成功 %d，失敗 %d", i, len(stock_ids), len(results), failed)

        # 隨機化間隔（不要固定 delay 死打），降低被 TDCC 限流的機率
        time.sleep(delay + random.uniform(0, _JITTER))

    return results


def save_to_db(rows: list[dict]) -> int:
    """upsert 集保資料到 DuckDB shareholder 表，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd
    df = pd.DataFrame(rows)[["stock_id", "date", "lv12_15_pct", "lv12_15_cnt", "lv12_15_shares", "total_shares"]]
    df["date"] = pd.to_datetime(df["date"]).dt.date

    con = duckdb.connect(_DB_PATH)
    # 計算 week_change 和 streak
    _add_week_change_streak(con, df)
    con.execute("DELETE FROM shareholder WHERE (stock_id, date) IN (SELECT stock_id, date FROM df)")
    # 明列欄位名（by-name 對應）：既有 DB 的 lv12_15_shares 是 ALTER 加在最後一欄，
    # 位置跟全新 CREATE TABLE 的中間位置不同，用位置式 INSERT 會錯位，故明列欄位
    con.execute(
        "INSERT INTO shareholder "
        "(stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak) "
        "SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, lv12_15_shares, total_shares, week_chg, streak FROM df"
    )
    n = len(df)
    con.close()
    return n


def _streak_step(chg: float, prev_streak: int) -> int:
    """依本週變化方向延續或翻轉 streak（正=連增，負=連減）。"""
    if chg > 0:
        return prev_streak + 1 if prev_streak > 0 else 1
    if chg < 0:
        return prev_streak - 1 if prev_streak < 0 else -1
    return 0


def _add_week_change_streak(con: duckdb.DuckDBPyConnection, df) -> None:
    """在 df 上原地加上 week_chg 和 streak 欄位（查 DB 上週資料）。"""
    import pandas as pd
    week_chg = []
    streak = []

    # 批次查上週資料。
    # streak 基準必須是「嚴格更舊的週」，不能是正在寫入的同一週——save_to_db 是先算
    # streak 再 DELETE 同 date，若這裡只取「最新一筆」，同一週被重跑（例如每日 cron、
    # 或 TDCC 尚未出新週仍抓到同一週）時會拿自己當基準，把 chg 算成 ~0、streak 洗成 0，
    # 連增/連減週數失真。加上 date < 本次寫入週，排除同 date。
    sids = df["stock_id"].tolist()
    write_date = df["date"].max() if not df.empty else None
    prev_rows = con.execute("""
        SELECT stock_id, lv12_15_pct, streak
        FROM shareholder
        WHERE stock_id IN (SELECT UNNEST(?)) AND date < ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
    """, [sids, write_date]).df() if sids and write_date is not None else pd.DataFrame()

    prev_map = {r["stock_id"]: r for _, r in prev_rows.iterrows()} if not prev_rows.empty else {}

    for _, row in df.iterrows():
        prev = prev_map.get(row["stock_id"])
        if prev is not None:
            chg = round(row["lv12_15_pct"] - prev["lv12_15_pct"], 4)
            s = _streak_step(chg, int(prev.get("streak", 0)))
        else:
            chg = None
            s = 0
        week_chg.append(chg)
        streak.append(s)

    df["week_chg"] = week_chg
    df["streak"] = streak


def recompute_latest_streak(db_path: str = _DB_PATH) -> int:
    """
    重算「每支股票目前資料庫裡最新一筆」的 week_chg/streak，跟該股次新一筆比較。

    背景：--update-shareholder（抓最新週）跟 --backfill-shareholder（補歷史週）是
    兩條分開呼叫的路徑，_add_week_change_streak 只在「寫入當下」處理那一批資料。
    如果最新週先寫入（那時 DB 裡還沒有更舊的週可比，week_chg/streak 被記成
    NULL/0——這在當下是正確答案），之後才 backfill 補進更舊的週，最新週的
    衍生欄位不會自動更新，因為沒有任何呼叫再去重寫那一批，會一直卡在錯誤的初始值
    （get_shareholder_top() 只抓每支股票最新一筆，這樣會讓 Section 8 排行永遠空白）。
    backfill 完成後應呼叫這個函式修正回來。不需要重打 TDCC，lv12_15_pct 已經在
    DB 裡，只是重算 week_chg/streak 兩個衍生欄位。回傳實際更新的股票數。
    """
    con = duckdb.connect(db_path)
    df = con.execute("""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct, streak,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
        )
        SELECT latest.stock_id, latest.date, latest.lv12_15_pct AS pct,
               prev.lv12_15_pct AS prev_pct, prev.streak AS prev_streak
        FROM (SELECT * FROM ranked WHERE rn = 1) latest
        LEFT JOIN (SELECT * FROM ranked WHERE rn = 2) prev
          ON latest.stock_id = prev.stock_id
    """).df()

    import pandas as pd
    updates = []
    for _, row in df.iterrows():
        if pd.isna(row["prev_pct"]):
            continue  # 沒有更早的週可比，維持原狀（新股或只有一週資料）
        chg = round(float(row["pct"]) - float(row["prev_pct"]), 4)
        prev_streak = int(row["prev_streak"]) if not pd.isna(row["prev_streak"]) else 0
        s = _streak_step(chg, prev_streak)
        updates.append((chg, s, row["stock_id"], row["date"]))

    if updates:
        con.executemany(
            "UPDATE shareholder SET week_chg = ?, streak = ? WHERE stock_id = ? AND date = ?",
            updates,
        )
    con.close()
    return len(updates)


def get_available_dates() -> list[str]:
    """回傳 TDCC 目前可查的週別日期列表（YYYYMMDD 格式）。"""
    import warnings
    warnings.filterwarnings("ignore")
    _, _, _, dates = _get_session_tokens()
    return dates
