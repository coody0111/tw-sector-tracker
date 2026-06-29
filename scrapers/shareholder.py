"""
集保持股分散表 scraper — TDCC 每週五更新一次
抓各股 ≥400張 大戶持股比例，計算週變化與連增/連減週數。
"""
import logging
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
    try:
        r = s.post(_TDCC_URL, data=data, headers=_HEADERS, timeout=30, verify=False)
        r.raise_for_status()
    except Exception as e:
        logger.debug("TDCC %s %s 失敗: %s", stock_id, date_str, e)
        return None

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
        # 每次 POST 前都重新取 token（TDCC token 一次性）
        try:
            s, tok, uri, _ = _get_session_tokens()
        except Exception as e:
            logger.warning("  [%d] 取 token 失敗: %s，跳過 %s", i, e, sid)
            failed += 1
            time.sleep(delay)
            continue

        rec = _fetch_one_stock(s, tok, uri, sid, target_date)
        if rec:
            rec["stock_id"] = sid
            rec["date"] = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
            results.append(rec)
        else:
            failed += 1
            logger.debug("  [%d/%d] %s 無資料", i, len(stock_ids), sid)

        if i % 50 == 0 or i == len(stock_ids):
            logger.info("  [%d/%d] 成功 %d，失敗 %d", i, len(stock_ids), len(results), failed)

        time.sleep(delay)

    return results


def save_to_db(rows: list[dict]) -> int:
    """upsert 集保資料到 DuckDB shareholder 表，回傳寫入筆數。"""
    if not rows:
        return 0
    import pandas as pd
    df = pd.DataFrame(rows)[["stock_id", "date", "lv12_15_pct", "lv12_15_cnt", "total_shares"]]
    df["date"] = pd.to_datetime(df["date"]).dt.date

    con = duckdb.connect(_DB_PATH)
    # 計算 week_change 和 streak
    _add_week_change_streak(con, df)
    con.execute("DELETE FROM shareholder WHERE (stock_id, date) IN (SELECT stock_id, date FROM df)")
    con.execute("INSERT INTO shareholder SELECT stock_id, date, lv12_15_pct, lv12_15_cnt, total_shares, week_chg, streak FROM df")
    n = len(df)
    con.close()
    return n


def _add_week_change_streak(con: duckdb.DuckDBPyConnection, df) -> None:
    """在 df 上原地加上 week_chg 和 streak 欄位（查 DB 上週資料）。"""
    import pandas as pd
    week_chg = []
    streak = []

    # 批次查上週資料
    sids = df["stock_id"].tolist()
    prev_rows = con.execute("""
        SELECT stock_id, lv12_15_pct, streak
        FROM shareholder
        WHERE stock_id IN (SELECT UNNEST(?))
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
    """, [sids]).df() if sids else pd.DataFrame()

    prev_map = {r["stock_id"]: r for _, r in prev_rows.iterrows()} if not prev_rows.empty else {}

    for _, row in df.iterrows():
        prev = prev_map.get(row["stock_id"])
        if prev is not None:
            chg = round(row["lv12_15_pct"] - prev["lv12_15_pct"], 4)
            prev_streak = int(prev.get("streak", 0))
            if chg > 0:
                s = prev_streak + 1 if prev_streak > 0 else 1
            elif chg < 0:
                s = prev_streak - 1 if prev_streak < 0 else -1
            else:
                s = 0
        else:
            chg = None
            s = 0
        week_chg.append(chg)
        streak.append(s)

    df["week_chg"] = week_chg
    df["streak"] = streak


def get_available_dates() -> list[str]:
    """回傳 TDCC 目前可查的週別日期列表（YYYYMMDD 格式）。"""
    import warnings
    warnings.filterwarnings("ignore")
    _, _, _, dates = _get_session_tokens()
    return dates
