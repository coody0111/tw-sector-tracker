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
import os
import random
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import List

import urllib3
import pandas as pd
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    """Yield trading days only (skip weekends and Taiwan national holidays)."""
    from config import is_trading_day
    current = start
    while current <= end:
        if is_trading_day(current.isoformat()):
            yield current
        current += timedelta(days=1)


def _fetch_stock_months(sid: str, month_starts: list) -> tuple[str, list]:
    """
    抓取單支 TWSE 股票的所有月份資料（只用於已確認為 TWSE 的股票）。
    回傳 (stock_id, rows_list)
    """
    rows = []

    for mo in month_starts:
        date_str = mo.strftime("%Y%m%d")
        for attempt in range(3):
            try:
                resp = requests.get(
                    TWSE_STOCK_DAY_URL,
                    params={"stockNo": sid, "date": date_str, "response": "json"},
                    headers=_HEADERS,
                    timeout=15,
                    verify=False,
                )
                data = resp.json()
                if data.get("stat") != "OK" or not data.get("data"):
                    break  # 該月無資料（假日/下市），跳到下一個月

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
                break  # 成功，跳出 retry 迴圈

            except (ValueError, requests.exceptions.JSONDecodeError,
                    requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                # 暫時性網路/SSL 問題，重試
                if attempt < 2:
                    time.sleep(3)
                else:
                    logger.debug("  %s %s 三次失敗，略過", sid, date_str)

            except Exception as exc:
                logger.debug("  %s %s 失敗: %s", sid, date_str, exc)
                break

        time.sleep(0.5)

    return sid, rows


TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def _fetch_tpex_all_days(stock_ids: set, start: date, end: date) -> dict:
    """
    用 TPEx OpenAPI 逐日抓全市場收盤，回傳 {date_str: [rows]} dict。
    每次 API 呼叫回傳當日所有上櫃股票，再過濾出我們需要的 stock_ids。
    """
    day_rows: dict = defaultdict(list)
    all_dates = list(_iter_weekdays(start, end))
    done = 0

    for d in all_dates:
        date_param = f"{d.year}/{d.month:02d}/{d.day:02d}"
        try:
            resp = requests.get(
                TPEX_DAILY_URL,
                params={"date": date_param},
                headers=_HEADERS_TPEX,
                timeout=15,
            )
            data = resp.json()
            if not data:
                time.sleep(0.3)
                continue

            for item in data:
                sid = str(item.get("SecuritiesCompanyCode", "")).strip()
                if sid not in stock_ids:
                    continue
                try:
                    close  = float(item["Close"].replace(",", ""))
                    change = float(item["Change"].strip().replace(",", "").replace("+", ""))
                    prev   = close - change
                    change_pct = round(change / prev * 100, 2) if prev != 0 else 0.0
                    vol    = int(item["TradingShares"].replace(",", "")) // 1000
                    # Date field is Minguo: '1150627' → 2026-06-27
                    mg = item["Date"]
                    y   = int(mg[:3]) + 1911
                    m   = int(mg[3:5])
                    day = int(mg[5:])
                    d_str = f"{y}-{m:02d}-{day:02d}"
                    day_rows[d_str].append({
                        "stock_id":   sid,
                        "close":      close,
                        "change":     change,
                        "change_pct": change_pct,
                        "volume":     vol,
                        "_date":      d_str,
                    })
                except (ValueError, KeyError):
                    continue

        except Exception as exc:
            logger.debug("TPEx daily %s 失敗: %s", date_param, exc)

        done += 1
        time.sleep(0.3)
        if done % 20 == 0 or done == len(all_dates):
            logger.info("  TPEx daily [%d/%d]", done, len(all_dates))

    return day_rows


def _fetch_twse_one_day(d: date, stock_ids_set: set, sleep_sec: float = 0.6) -> tuple[str, list]:
    """
    用 STOCK_DAY_ALL 抓單日所有 TWSE 上市股收盤，過濾到 stock_ids_set。
    一次 API call 取代原本 n_stocks 次 STOCK_DAY call。
    """
    time.sleep(sleep_sec + random.random() * 0.15)
    try:
        df = fetch_twse_daily_prices(d)
        if df.empty:
            return d.isoformat(), []
        rows = []
        for _, row in df.iterrows():
            sid = str(row["stock_id"]).strip()
            if sid not in stock_ids_set:
                continue
            try:
                rows.append({
                    "stock_id":   sid,
                    "close":      float(row["close"]),
                    "change":     float(row.get("change", 0) or 0),
                    "change_pct": float(row.get("change_pct", 0) or 0),
                    "volume":     int(row.get("volume", 0) or 0),
                    "_date":      d.isoformat(),
                })
            except (ValueError, TypeError):
                continue
        return d.isoformat(), rows
    except Exception as exc:
        logger.debug("TWSE_ALL %s: %s", d, exc)
        return d.isoformat(), []


def _fetch_twse_all_days(
    stock_ids_set: set,
    start: date,
    end: date,
    workers: int = 3,
) -> dict:
    """
    並行逐日用 STOCK_DAY_ALL 抓 TWSE 全市場收盤。
    n_days 次 API call（vs 舊版 n_stocks × n_months 次），快約 50 倍。
    workers 建議 2-4（過高可能觸發 TWSE 限速）。
    """
    day_rows: dict = defaultdict(list)
    all_dates = list(_iter_weekdays(start, end))
    done = 0
    total = len(all_dates)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch_twse_one_day, d, stock_ids_set): d
                   for d in all_dates}
        for fut in as_completed(futures):
            d_str, rows = fut.result()
            for r in rows:
                day_rows[d_str].append(r)
            done += 1
            if done % 30 == 0 or done == total:
                total_records = sum(len(v) for v in day_rows.values())
                logger.info("  TWSE_ALL [%d/%d 日]  已取 %d 筆", done, total, total_records)

    return day_rows


def _fetch_yfinance_history(
    stock_ids: List[str],
    start_date: str,
    end_date: str,
    day_rows: dict,
    batch_size: int = 50,
) -> int:
    """用 yfinance 批量抓 TPEx 上櫃股歷史行情（.TWO suffix），append 到 day_rows。回傳成功股數。"""
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    import requests as _req

    session = _req.Session()
    session.verify = False  # Windows SSL workaround

    ok = fail = 0
    total_batches = (len(stock_ids) + batch_size - 1) // batch_size

    for b_idx in range(0, len(stock_ids), batch_size):
        batch = stock_ids[b_idx:b_idx + batch_size]
        tickers = [f"{sid}.TWO" for sid in batch]

        try:
            # retry up to 3 times; yfinance returns empty df on rate limit (no exception)
            hist = None
            for attempt in range(3):
                try:
                    hist = yf.download(
                        tickers, start=start_date, end=end_date,
                        progress=False, session=session, auto_adjust=True,
                    )
                except Exception as exc:
                    logger.warning("yfinance download error (attempt %d): %s", attempt + 1, exc)
                    hist = None
                if hist is not None and not hist.empty:
                    break
                if attempt < 2:
                    wait = 30 * (attempt + 1)
                    logger.warning("yfinance empty result, rate limit? retry %d/3 in %ds", attempt + 1, wait)
                    time.sleep(wait)

            if hist is None or hist.empty:
                fail += len(batch)
                logger.debug("yfinance batch %d empty", b_idx // batch_size + 1)
                continue

            # yfinance 1.4+ always returns MultiIndex (Price, Ticker)
            for sid, ticker in zip(batch, tickers):
                try:
                    close_s = hist["Close"][ticker].dropna()
                    vol_s   = hist["Volume"][ticker].reindex(close_s.index).fillna(0)
                except KeyError:
                    fail += 1
                    continue
                if close_s.empty:
                    fail += 1
                    continue

                prev_close = close_s.shift(1)
                change_s   = (close_s - prev_close).fillna(0)
                pct_s      = (change_s / prev_close.replace(0, float("nan")) * 100).fillna(0)

                for dt, cl, ch, pct, vol in zip(
                    close_s.index, close_s, change_s, pct_s, vol_s
                ):
                    d = dt.strftime("%Y-%m-%d")
                    day_rows[d].append({
                        "stock_id":   sid,
                        "close":      round(float(cl), 2),
                        "change":     round(float(ch), 2),
                        "change_pct": round(float(pct), 2),
                        "volume":     max(0, int(float(vol)) // 1000),
                        "_date":      d,
                    })
                ok += 1

        except Exception as exc:
            logger.warning("yfinance batch %s~%s: %s", batch[0], batch[-1], exc)
            fail += len(batch)

        batch_num = b_idx // batch_size + 1
        logger.info("  yfinance [%d/%d]  ok=%d  fail=%d", batch_num, total_batches, ok, fail)
        if b_idx + batch_size < len(stock_ids):
            time.sleep(3)  # avoid rate limit between batches

    return ok


def _fetch_finmind_history(
    stock_ids: List[str],
    start_date: str,
    end_date: str,
    day_rows: dict,
    token: str,
    sleep_sec: float = 0.5,
) -> int:
    """用 FinMind TaiwanStockPrice 逐股抓歷史行情，append 到 day_rows。回傳成功股數。"""
    total = len(stock_ids)
    ok = fail = consecutive_fail = 0

    for i, sid in enumerate(stock_ids, 1):
        try:
            resp = requests.get(FINMIND_URL, params={
                "dataset":    "TaiwanStockPrice",
                "data_id":    sid,
                "start_date": start_date,
                "end_date":   end_date,
                "token":      token,
            }, timeout=10)
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

        if i % 50 == 0 or i == total:
            logger.info("  FinMind [%d/%d]  ok=%d  fail=%d", i, total, ok, fail)

        if consecutive_fail >= _CONSECUTIVE_FAIL_LIMIT:
            logger.warning(
                "FinMind 連續失敗 %d 次（可能達到每日上限 600），提早結束（已處理 %d/%d 支）",
                consecutive_fail, i, total,
            )
            break

        time.sleep(sleep_sec)

    logger.info("FinMind 完成：ok=%d  fail=%d  共 %d 支", ok, fail, total)
    return ok


def backfill_twse_monthly(
    stock_ids: List[str],
    months: int = 6,
    output_dir: str = "data/daily_prices",
    workers: int = 5,
    today: date = None,
    clean: bool = True,
    exchange_map: dict = None,
    finmind_token: str = "",
) -> int:
    """
    全市場歷史行情補齊。

    Phase 1: TWSE 上市股 — 逐股月別 STOCK_DAY API（並行，workers 個 thread）
    Phase 2: TPEx 上櫃股 — FinMind TaiwanStockPrice（逐股，需 token，免費帳號每日 600 次）

    exchange_map: {stock_id: "TWSE"|"TPEx"} 預分類，直接從 stock_universe.csv 的 exchange 欄取得。
                  不提供時所有股票走 Phase 1（兼容舊行為）。

    注意：STOCK_DAY_ALL 永遠回傳今天的資料，不能用於歷史。Phase 1 必須用逐股 STOCK_DAY。
    TPEx 官方 OpenAPI 同樣無歷史資料；FinMind 是目前唯一免費的上櫃歷史來源。

    clean=True（預設）：執行前刪除所有現有 CSV，確保乾淨起始點。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if clean:
        old_csvs = list(output_path.glob("*.csv"))
        if old_csvs:
            for f in old_csvs:
                f.unlink()
            logger.info("清除舊 CSV：已刪除 %d 個檔案", len(old_csvs))

    today = today or date.today()
    start = _first_month_start(today, months)

    month_starts: List[date] = []
    y, m = start.year, start.month
    while date(y, m, 1) <= today:
        month_starts.append(date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1

    # 用 exchange_map 預分類；無 map 時全部走 TWSE Phase 1（相容舊行為）
    if exchange_map:
        twse_stocks = [sid for sid in stock_ids if exchange_map.get(sid) == "TWSE"]
        tpex_stocks = [sid for sid in stock_ids if exchange_map.get(sid) != "TWSE"]
        logger.info(
            "預分類完成：TWSE %d 支，TPEx %d 支（共 %d 支股票）",
            len(twse_stocks), len(tpex_stocks), len(stock_ids),
        )
    else:
        twse_stocks = list(stock_ids)
        tpex_stocks = []

    logger.info(
        "逐股月別補齊：%d 支 TWSE  %d 個月（%s ~ %s）",
        len(twse_stocks), len(month_starts), start.isoformat(), today.isoformat(),
    )

    day_rows: dict = defaultdict(list)
    twse_done = 0

    # Phase 1: TWSE 逐股月別（並行）
    logger.info("Phase 1 TWSE 逐股月別 STOCK_DAY：workers=%d ...", workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_stock_months, sid, month_starts): sid
            for sid in twse_stocks
        }
        done = 0
        for fut in as_completed(futures):
            sid, rows = fut.result()
            done += 1
            if rows:
                for r in rows:
                    day_rows[r["_date"]].append(r)
                twse_done += 1
            if done % 50 == 0 or done == len(twse_stocks):
                total_so_far = sum(len(v) for v in day_rows.values())
                logger.info(
                    "  [%d/%d 股]  TWSE成功=%d  目前 %d 筆",
                    done, len(twse_stocks), twse_done, total_so_far,
                )
    logger.info("Phase 1 完成：TWSE %d 支成功（共 %d 支）", twse_done, len(twse_stocks))

    # Phase 2: TPEx 逐股 via FinMind TaiwanStockPrice
    if tpex_stocks:
        if not finmind_token:
            logger.warning("Phase 2 跳過：未提供 finmind_token，TPEx %d 支無法補齊", len(tpex_stocks))
        else:
            logger.info("Phase 2 TPEx via FinMind：%d 支（每日上限 600 次）...", len(tpex_stocks))
            _fetch_finmind_history(
                tpex_stocks, start.isoformat(), today.isoformat(), day_rows, finmind_token
            )

    written = 0
    for d_str, rows in sorted(day_rows.items()):
        if _merge_into_csv(output_path / f"{d_str}.csv", rows, overwrite=True):
            written += 1

    total_records = sum(len(v) for v in day_rows.values())
    logger.info("補齊完成：寫入/更新 %d 日，共 %d 筆", written, total_records)
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
