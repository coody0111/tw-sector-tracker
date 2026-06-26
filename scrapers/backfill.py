"""
歷史行情補齊

方式：
  1. backfill_twse_monthly()     — TWSE STOCK_DAY + TPEx st43 逐股月別（完整覆蓋上市+上櫃）
  2. backfill_prices()           — FinMind TaiwanStockPrice（備用，每日 600 次上限）
  3. backfill_institutional()    — TWSE T86 逐日三大法人（每日一次 API，速度快）

建議流程：
  跑 backfill_twse_monthly（TWSE 先抓，non-TWSE 自動轉 TPEx，約 2~3 小時）；
  跑 backfill_institutional 補齊過去法人籌碼（建議 60 天）。
"""
import logging
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import List

import pandas as pd
import requests
import yfinance as yf

from scrapers.twse import fetch_daily_prices as fetch_twse_daily_prices

logger = logging.getLogger(__name__)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TPEX_STOCK_DAY_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"

_HEADERS_TWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
}

_HEADERS_TPEX = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tpex.org.tw/",
}

_HEADERS = _HEADERS_TWSE  # backward compat

# FinMind 連續失敗超過此數就視為 rate-limit 到上限，提早退出
_CONSECUTIVE_FAIL_LIMIT = 30

_csv_lock = threading.Lock()


def _merge_into_csv(path: Path, new_rows: list, overwrite: bool = False) -> bool:
    """把 new_rows merge 進 path 的 CSV。
    overwrite=False（預設）：只加入尚未有的 stock_id。
    overwrite=True：新資料覆蓋已有的同 stock_id，其餘保留。
    回傳是否有寫入。
    """
    new_df = pd.DataFrame(new_rows)
    with _csv_lock:
        if path.exists():
            old_df = pd.read_csv(path, dtype={"stock_id": str})
            if overwrite:
                updated_ids = set(new_df["stock_id"].astype(str))
                old_rest = old_df[~old_df["stock_id"].astype(str).isin(updated_ids)]
                merged = pd.concat([old_rest, new_df], ignore_index=True)
                merged = merged.drop_duplicates(subset=["stock_id"], keep="last")
            else:
                existing_ids = set(old_df["stock_id"].astype(str))
                to_add = new_df[~new_df["stock_id"].astype(str).isin(existing_ids)]
                if to_add.empty:
                    return False
                merged = pd.concat([old_df, to_add], ignore_index=True)
        else:
            merged = new_df
        merged.to_csv(path, index=False, encoding="utf-8-sig")
    return True


def _first_month_start(today: date, months: int) -> date:
    """Return the first day of the calendar-month window."""
    if months < 1:
        raise ValueError("months must be >= 1")

    y = today.year
    m = today.month - months + 1
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _iter_weekdays(start: date, end: date):
    """Yield weekdays only; TWSE holidays are skipped after API response."""
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _fetch_stock_months(sid: str, month_starts: list) -> tuple[str, list, bool]:
    """
    抓取單支股票的所有月份資料。
    回傳 (stock_id, rows_list, is_twse)
    rows_list: [{date_str, stock_id, close, change, change_pct, volume}, ...]
    """
    rows = []
    stock_fail = 0
    is_twse = False

    for mo in month_starts:
        date_str = mo.strftime("%Y%m%d")
        try:
            resp = requests.get(
                TWSE_STOCK_DAY_URL,
                params={"stockNo": sid, "date": date_str, "response": "json"},
                headers=_HEADERS,
                timeout=15,
            )
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("data"):
                stock_fail += 1
                if stock_fail >= 2 and not is_twse:
                    break  # 連兩個月都查無 → 非 TWSE，提早結束
                continue

            fields = data.get("fields", [])
            close_idx = fields.index("收盤價") if "收盤價" in fields else 6
            spread_idx = fields.index("漲跌價差") if "漲跌價差" in fields else 7
            vol_idx = fields.index("成交股數") if "成交股數" in fields else 1

            for row in data["data"]:
                minguo = row[0]
                parts = minguo.split("/")
                if len(parts) != 3:
                    continue
                try:
                    year_ad = int(parts[0]) + 1911
                    d_str = f"{year_ad}-{parts[1]}-{parts[2]}"
                    close = float(row[close_idx].replace(",", ""))
                    spread = float(row[spread_idx].replace(",", "").replace("+", ""))
                    prev_close = close - spread
                    change_pct = round(spread / prev_close * 100, 2) if prev_close != 0 else 0.0
                    vol_lots = int(row[vol_idx].replace(",", "")) // 1000
                except (ValueError, IndexError):
                    continue

                rows.append({
                    "stock_id":   sid,
                    "close":      close,
                    "change":     spread,
                    "change_pct": change_pct,
                    "volume":     vol_lots,
                    "_date":      d_str,
                })

            is_twse = True
            stock_fail = 0  # reset on success

        except Exception as exc:
            stock_fail += 1
            logger.debug("  %s %s 失敗: %s", sid, date_str, exc)
            if stock_fail >= 2 and not is_twse:
                break

        time.sleep(0.4)  # 每次 request 後稍等，避免被 TWSE 封鎖

    return sid, rows, is_twse


def _fetch_tpex_yfinance(sid: str, start: date, end: date) -> tuple[str, list, bool]:
    """
    用 yfinance 抓上櫃股票歷史行情（ticker = sid.TWO）。
    回傳 (stock_id, rows_list, is_tpex)
    """
    ticker_sym = f"{sid}.TWO"
    try:
        hist = yf.Ticker(ticker_sym).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
        if hist.empty:
            return sid, [], False

        closes = hist["Close"].astype(float)
        prev_closes = closes.shift(1)
        changes = (closes - prev_closes).round(2)
        change_pcts = ((changes / prev_closes) * 100).round(2)

        rows = []
        for ts, row in hist.iterrows():
            d_str = ts.strftime("%Y-%m-%d")
            close = round(float(row["Close"]), 2)
            change = float(changes.loc[ts]) if not pd.isna(changes.loc[ts]) else 0.0
            change_pct = float(change_pcts.loc[ts]) if not pd.isna(change_pcts.loc[ts]) else 0.0
            vol_lots = int(row["Volume"]) // 1000 if row["Volume"] else 0
            rows.append({
                "stock_id":   sid,
                "close":      close,
                "change":     change,
                "change_pct": change_pct,
                "volume":     vol_lots,
                "_date":      d_str,
            })
        return sid, rows, True

    except Exception as exc:
        logger.debug("  yfinance %s 失敗: %s", ticker_sym, exc)
        return sid, [], False


def backfill_twse_monthly(
    stock_ids: List[str],
    months: int = 6,
    output_dir: str = "data/daily_prices",
    workers: int = 3,
    today: date = None,
) -> int:
    """
    TWSE STOCK_DAY + TPEx st43 逐股月別補齊。
    先用 TWSE 抓，回傳 is_twse=False 的再用 TPEx 補，完整覆蓋上市+上櫃。
    回傳：寫入或更新的日期數。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    today = today or date.today()
    start = _first_month_start(today, months)

    month_starts = []
    cur = start
    while cur <= today:
        month_starts.append(cur)
        cur = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)

    total = len(stock_ids)
    logger.info(
        "TWSE+TPEx 月別補齊：%d 支股票，%d 個月（%s ~ %s）",
        total, len(month_starts), start.isoformat(), today.isoformat(),
    )

    day_rows: dict = defaultdict(list)
    non_twse: list = []
    done = 0

    # Phase 1: TWSE
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch_stock_months, sid, month_starts): sid
                   for sid in stock_ids}
        for fut in as_completed(futures):
            try:
                sid, rows, is_twse = fut.result()
                if is_twse:
                    for r in rows:
                        day_rows[r["_date"]].append(r)
                else:
                    non_twse.append(sid)
            except Exception as exc:
                logger.debug("TWSE fetch error: %s", exc)
            done += 1
            if done % 200 == 0 or done == total:
                logger.info("  TWSE [%d/%d]", done, total)

    logger.info("TWSE 完成：%d 支，non-TWSE（上櫃）補 yfinance：%d 支", total - len(non_twse), len(non_twse))

    # Phase 2: yfinance for non-TWSE (TPEx) stocks
    if non_twse:
        done2 = 0
        yf_workers = min(workers, 5)  # yfinance 不需要太多並發
        with ThreadPoolExecutor(max_workers=yf_workers) as executor:
            futures2 = {executor.submit(_fetch_tpex_yfinance, sid, start, today): sid
                        for sid in non_twse}
            for fut in as_completed(futures2):
                try:
                    _, rows, _ = fut.result()
                    for r in rows:
                        day_rows[r["_date"]].append(r)
                except Exception as exc:
                    logger.debug("yfinance fetch error: %s", exc)
                done2 += 1
                if done2 % 200 == 0 or done2 == len(non_twse):
                    logger.info("  yfinance [%d/%d]", done2, len(non_twse))

    written = 0
    for d_str, rows in sorted(day_rows.items()):
        if _merge_into_csv(output_path / f"{d_str}.csv", rows, overwrite=True):
            written += 1

    logger.info("TWSE+TPEx 補齊完成：寫入/更新 %d 日", written)
    return written


def backfill_prices(
    stock_ids: List[str],
    token: str,
    days: int = 180,
    output_dir: str = "data/daily_prices",
    sleep_sec: float = 0.4,
) -> int:
    """
    用 FinMind 逐股抓歷史行情，重組成 daily_prices/YYYY-MM-DD.csv。
    多次執行時會 merge 已有的 CSV（補上前次漏掉的股票）。
    FinMind 免費帳號每日約 600 次，超過後自動提早退出。
    回傳：成功寫入（含更新）的日期數。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    today = date.today()
    start_date = (today - timedelta(days=days)).isoformat()
    end_date = today.isoformat()

    day_rows: dict = defaultdict(list)
    total = len(stock_ids)
    ok = fail = consecutive_fail = 0

    logger.info("FinMind 逐股補齊：%d 支股票  %s ~ %s", total, start_date, end_date)

    for i, sid in enumerate(stock_ids, 1):
        try:
            resp = requests.get(FINMIND_URL, params={
                "dataset":    "TaiwanStockPrice",
                "data_id":    sid,
                "start_date": start_date,
                "end_date":   end_date,
                "token":      token,
            }, timeout=5)
            data = resp.json()

            if data.get("status") != 200 or not data.get("data"):
                fail += 1
                consecutive_fail += 1
            else:
                for row in data["data"]:
                    d = row["date"]
                    vol_lots = int(row["Trading_Volume"]) // 1000
                    close = float(row["close"])
                    spread = float(row.get("spread", 0))
                    prev_close = close - spread
                    change_pct = round(spread / prev_close * 100, 2) if prev_close != 0 else 0.0
                    day_rows[d].append({
                        "stock_id":   sid,
                        "close":      close,
                        "change":     spread,
                        "change_pct": change_pct,
                        "volume":     vol_lots,
                    })
                ok += 1
                consecutive_fail = 0

        except Exception as exc:
            fail += 1
            consecutive_fail += 1
            logger.debug("  %s 失敗: %s", sid, exc)

        if i % 50 == 0:
            logger.info("  [%d/%d] 已處理 %d 支，失敗 %d", i, total, ok, fail)

        if consecutive_fail >= _CONSECUTIVE_FAIL_LIMIT:
            logger.warning(
                "連續失敗 %d 次（可能已達 FinMind 每日上限），提早停止。"
                "明日重跑可補齊剩餘 %d 支。",
                consecutive_fail, total - i,
            )
            break

        time.sleep(sleep_sec)

    logger.info("抓取完成：成功 %d / 失敗 %d，整理成每日 CSV...", ok, fail)

    if not day_rows:
        logger.info("本次未取得任何資料，CSV 不更新。")
        return 0

    written = 0
    output_path_obj = Path(output_dir)
    for d_str, new_rows in sorted(day_rows.items()):
        if _merge_into_csv(output_path_obj / f"{d_str}.csv", new_rows):
            written += 1

    logger.info("寫入/更新 %d 個日期的 CSV", written)
    return written


def backfill_margin(
    days: int = 60,
    db_path: str = "data/screener.db",
    sleep_sec: float = 0.8,
    today: date = None,
) -> int:
    """
    補齊過去 N 個工作日的 TWSE 融資融券資料（MI_MARGN API）。
    已有資料的日期會跳過。回傳：成功寫入的交易日數。
    """
    from scrapers.chips import fetch_margin_all_twse
    import duckdb

    today = today or date.today()
    start_date = today - timedelta(days=days)
    trade_days = list(_iter_weekdays(start_date, today))

    try:
        con = duckdb.connect(db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS margin (
                stock_id        VARCHAR,
                date            DATE,
                margin_balance  BIGINT,
                margin_change   BIGINT,
                short_balance   BIGINT,
                short_change    BIGINT,
                PRIMARY KEY (stock_id, date)
            )
        """)
        existing_rows = con.execute("SELECT DISTINCT date FROM margin").df()
        con.close()
        existing_dates = set(existing_rows["date"].astype(str).tolist()) if not existing_rows.empty else set()
    except Exception as exc:
        logger.warning("無法讀取現有融資資料: %s", exc)
        existing_dates = set()

    need = len([d for d in trade_days if d.isoformat() not in existing_dates])
    logger.info("融資補齊：%s ~ %s（%d 工作日），需補 %d 日",
                start_date.isoformat(), today.isoformat(), len(trade_days), need)

    written = 0
    for i, trade_day in enumerate(trade_days, 1):
        d_str = trade_day.isoformat()
        if d_str in existing_dates:
            continue
        try:
            margin_df = fetch_margin_all_twse(trade_day)
            if margin_df.empty:
                time.sleep(sleep_sec)
                continue
            con = duckdb.connect(db_path)
            con.execute("DELETE FROM margin WHERE date = ?", [d_str])
            con.execute("INSERT INTO margin SELECT * FROM margin_df")
            con.close()
            written += 1
            logger.info("  [%d/%d] %s 寫入 %d 筆", i, len(trade_days), d_str, len(margin_df))
        except Exception as exc:
            logger.warning("  [%d/%d] %s 失敗: %s", i, len(trade_days), d_str, exc)
        time.sleep(sleep_sec)

    logger.info("融資補齊完成：成功寫入 %d 個交易日", written)
    return written


def backfill_institutional(
    days: int = 60,
    db_path: str = "data/screener.db",
    sleep_sec: float = 0.8,
    today: date = None,
) -> int:
    """
    補齊過去 N 個工作日的 TWSE 三大法人資料（T86 API）。
    已有資料的日期會跳過，只補缺漏。
    回傳：成功寫入的交易日數。
    """
    from scrapers.chips import fetch_institutional
    import duckdb

    today = today or date.today()
    start_date = today - timedelta(days=days)
    trade_days = list(_iter_weekdays(start_date, today))

    # 查詢 DB 中已有哪些日期
    try:
        con = duckdb.connect(db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS institutional (
                stock_id    VARCHAR,
                date        DATE,
                foreign_net BIGINT,
                trust_net   BIGINT,
                dealer_net  BIGINT,
                total_net   BIGINT,
                PRIMARY KEY (stock_id, date)
            )
        """)
        existing_rows = con.execute("SELECT DISTINCT date FROM institutional").df()
        con.close()
        existing_dates = set(existing_rows["date"].astype(str).tolist()) if not existing_rows.empty else set()
    except Exception as exc:
        logger.warning("無法讀取現有法人資料: %s", exc)
        existing_dates = set()

    logger.info(
        "法人補齊：%s ~ %s（%d 工作日），已有 %d 日，需補 %d 日",
        start_date.isoformat(), today.isoformat(),
        len(trade_days), len(existing_dates),
        len([d for d in trade_days if d.isoformat() not in existing_dates]),
    )

    written = 0
    for i, trade_day in enumerate(trade_days, 1):
        d_str = trade_day.isoformat()
        if d_str in existing_dates:
            continue

        try:
            inst_df = fetch_institutional(trade_day)
            if inst_df.empty:
                logger.debug("  %s 無資料（非交易日或尚未發布），跳過", d_str)
                time.sleep(sleep_sec)
                continue

            con = duckdb.connect(db_path)
            con.execute("DELETE FROM institutional WHERE date = ?", [d_str])
            con.execute("INSERT INTO institutional SELECT * FROM inst_df")
            con.close()
            written += 1
            logger.info("  [%d/%d] %s 寫入 %d 筆", i, len(trade_days), d_str, len(inst_df))

        except Exception as exc:
            logger.warning("  [%d/%d] %s 失敗: %s", i, len(trade_days), d_str, exc)

        time.sleep(sleep_sec)

    logger.info("法人補齊完成：成功寫入 %d 個交易日", written)
    return written
