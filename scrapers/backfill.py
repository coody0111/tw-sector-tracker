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

import certifi
import pandas as pd
import requests
import yfinance as yf

# Windows SSL fix for yfinance (curl_cffi)
os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

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


def _fetch_stock_months(sid: str, month_starts: list) -> tuple[str, list, bool, int]:
    """
    抓取單支股票的所有月份資料。
    回傳 (stock_id, rows_list, is_twse, months_ok)
    months_ok: 成功取得資料的月份數（用來偵測 Phase 1 部分失敗）
    """
    rows = []
    stock_fail = 0
    is_twse = False
    months_ok = 0

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
            months_ok += 1
            stock_fail = 0  # reset on success

        except Exception as exc:
            stock_fail += 1
            logger.debug("  %s %s 失敗: %s", sid, date_str, exc)
            if stock_fail >= 2 and not is_twse:
                break

        time.sleep(0.4)  # 每次 request 後稍等，避免被 TWSE 封鎖

    return sid, rows, is_twse, months_ok


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


def backfill_twse_monthly(
    stock_ids: List[str],
    months: int = 6,
    output_dir: str = "data/daily_prices",
    workers: int = 3,
    today: date = None,
) -> int:
    """
    TWSE STOCK_DAY_ALL + TPEx st43 逐日全市場補齊（快速版）。

    Phase 1: TWSE 用 STOCK_DAY_ALL，每日一次 API 取所有上市股（n_days 次）
    Phase 2: TPEx 用 OpenAPI 逐日全市場（n_days 次），補上櫃股
    workers 控制 Phase 1 並行數，建議 3-4，約 8-12 分鐘完成 18 個月。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    today = today or date.today()
    start = _first_month_start(today, months)
    stock_ids_set = {str(s) for s in stock_ids}

    all_days = list(_iter_weekdays(start, today))
    logger.info(
        "TWSE+TPEx 全市場逐日補齊：%d 支股票  %d 個交易日（%s ~ %s）  workers=%d",
        len(stock_ids), len(all_days), start.isoformat(), today.isoformat(), workers,
    )

    day_rows: dict = defaultdict(list)

    # Phase 1: TWSE STOCK_DAY_ALL（並行逐日，每 call 取所有上市股）
    logger.info("Phase 1 TWSE STOCK_DAY_ALL：%d 個交易日，workers=%d ...", len(all_days), workers)
    twse_rows = _fetch_twse_all_days(stock_ids_set, start, today, workers=workers)
    for d_str, rows in twse_rows.items():
        day_rows[d_str].extend(rows)

    twse_covered: set = {(r["_date"], r["stock_id"]) for rows in day_rows.values() for r in rows}
    logger.info("Phase 1 完成：取得 %d 股票×日 筆", len(twse_covered))

    # Phase 2: TPEx 逐日全市場（補充上櫃股）
    logger.info("Phase 2 TPEx 逐日：%d 個交易日 ...", len(all_days))
    tpex_rows = _fetch_tpex_all_days(stock_ids_set, start, today)
    added = 0
    for d_str, rows in tpex_rows.items():
        for r in rows:
            if (r["_date"], r["stock_id"]) not in twse_covered:
                day_rows[r["_date"]].append(r)
                added += 1
    tpex_covered: set = {(r["_date"], r["stock_id"]) for rows in tpex_rows.values() for r in rows}
    logger.info("Phase 2 完成：補充 TPEx %d 筆", added)

    # Phase 3: 個股補漏（STOCK_DAY_ALL 和 TPEx 都未涵蓋的上市股 → 用逐股月別 API）
    all_covered = twse_covered | tpex_covered
    covered_stocks = {sid for (_, sid) in all_covered}
    # 只補 TWSE 上市股（4位數字代號，上櫃已由 Phase 2 涵蓋）
    missing_twse = [s for s in stock_ids_set if s not in covered_stocks and s.isdigit() and len(s) == 4]
    if missing_twse:
        logger.info("Phase 3 個股補漏：%d 支 TWSE 股票未被 STOCK_DAY_ALL 涵蓋，改用逐股月別 API ...", len(missing_twse))
        month_starts = []
        y, m = start.year, start.month
        while date(y, m, 1) <= today:
            month_starts.append(date(y, m, 1))
            m += 1
            if m > 12:
                m = 1
                y += 1

        for sid in missing_twse:
            _, rows, is_twse, _ = _fetch_stock_months(sid, month_starts)
            if rows:
                for r in rows:
                    r["stock_id"] = sid
                    d_str = r.pop("_date")
                    r["_date"] = d_str
                    day_rows[d_str].append(r)
                logger.info("  %s: 補齊 %d 筆", sid, len(rows))
            else:
                logger.debug("  %s: 逐股 API 也無資料", sid)
    else:
        logger.info("Phase 3：無需補漏")

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


def backfill_yfinance(
    universe_path: str = "data/stock_universe.csv",
    months: int = 18,
    db_path: str = "data/screener.db",
    output_dir: str = "data/daily_prices",
    batch_size: int = 50,
) -> int:
    """
    用 Yahoo Finance 補齊歷史行情，無需 token，支援 18+ 個月。

    Exchange 對應：
      TWSE → {id}.TW
      TPEx  → {id}.TWO
      未知  → 先試 .TW 再試 .TWO

    直接 upsert 進 DuckDB（含 open/high/low），同時同步 daily_prices CSV。
    """
    import duckdb

    univ = pd.read_csv(universe_path, dtype={"stock_id": str})
    exch_map: dict[str, str] = {}
    for _, row in univ.iterrows():
        sid = str(row["stock_id"])
        ex = str(row.get("exchange", "")).upper()
        if "TPEX" in ex or "OTC" in ex or ex == "TWO":
            exch_map[sid] = f"{sid}.TWO"
        else:
            exch_map[sid] = f"{sid}.TW"

    all_sids = list(exch_map.keys())
    logger.info("Yahoo Finance 補齊：%d 支股票  最近 %d 個月  batch=%d", len(all_sids), months, batch_size)

    import math
    period_str = f"{months}mo"
    rows_all: list[dict] = []

    def _yf_fetch(tickers_str: str, sids_in_batch: list[str]) -> list[dict]:
        try:
            raw = yf.download(
                tickers_str,
                period=period_str,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.warning("yf.download 失敗: %s", exc)
            return []

        if raw.empty:
            return []

        # yfinance >= 0.2.x: columns are always MultiIndex (Price, Ticker)
        is_multi = isinstance(raw.columns, pd.MultiIndex)
        available_tickers = set(raw.columns.get_level_values(1)) if is_multi else set()

        results = []
        for sid in sids_in_batch:
            ticker = exch_map[sid]
            try:
                if is_multi:
                    if ticker not in available_tickers:
                        logger.debug("  %s: 無資料 (%s)", sid, ticker)
                        continue
                    df_s = raw.xs(ticker, axis=1, level=1).copy()
                else:
                    df_s = raw.copy()

                if df_s.empty:
                    logger.debug("  %s: empty after xs (%s)", sid, ticker)
                    continue

                df_s = df_s.dropna(subset=["Close"])
                df_s = df_s[df_s["Volume"] > 0]
                if df_s.empty:
                    continue

                closes = df_s["Close"].values.astype(float)
                changes = [0.0] + list(closes[1:] - closes[:-1])
                prev_closes = [closes[0]] + list(closes[:-1])
                change_pcts = [
                    round(ch / pc * 100, 2) if pc != 0 else 0.0
                    for ch, pc in zip(changes, prev_closes)
                ]

                for i, (dt_idx, row_s) in enumerate(df_s.iterrows()):
                    dt_str = dt_idx.date().isoformat() if hasattr(dt_idx, "date") else str(dt_idx)[:10]
                    results.append({
                        "stock_id":   sid,
                        "date":       dt_str,
                        "open":       round(float(row_s.get("Open") or 0), 4),
                        "high":       round(float(row_s.get("High") or 0), 4),
                        "low":        round(float(row_s.get("Low") or 0), 4),
                        "close":      round(float(row_s["Close"]), 4),
                        "volume":     int(row_s["Volume"]) // 1000,
                        "change":     round(changes[i], 4),
                        "change_pct": change_pcts[i],
                    })
            except Exception as exc:
                logger.debug("  %s 解析失敗: %s", sid, exc)

        return results

    n_batches = math.ceil(len(all_sids) / batch_size)
    for b in range(n_batches):
        batch = all_sids[b * batch_size:(b + 1) * batch_size]
        tickers_str = " ".join(exch_map[s] for s in batch)
        batch_rows = _yf_fetch(tickers_str, batch)
        rows_all.extend(batch_rows)
        logger.info("  batch [%d/%d]  取得 %d 筆", b + 1, n_batches, len(batch_rows))
        time.sleep(0.5)

    if not rows_all:
        logger.info("Yahoo Finance 無資料回傳，DuckDB 不更新。")
        return 0

    df_new = pd.DataFrame(rows_all)
    df_new["date"] = pd.to_datetime(df_new["date"]).dt.date

    # upsert DuckDB
    con = duckdb.connect(db_path)
    con.register("_yf_new", df_new)
    con.execute("DELETE FROM daily_prices WHERE (stock_id, date) IN (SELECT stock_id, date FROM _yf_new)")
    con.execute("""
        INSERT INTO daily_prices (stock_id, date, open, high, low, close, volume, change, change_pct)
        SELECT stock_id, date, open, high, low, close, volume, change, change_pct FROM _yf_new
    """)
    total = len(df_new)
    con.close()

    # 同步寫 CSV（維持現有格式，讓 reimport_db 可重建；失敗不中斷）
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_ok = csv_fail = 0
    for d_str, grp in df_new.groupby(df_new["date"].astype(str)):
        csv_rows = [
            {
                "stock_id":   r["stock_id"],
                "close":      r["close"],
                "change":     r["change"],
                "change_pct": r["change_pct"],
                "volume":     r["volume"],
            }
            for _, r in grp.iterrows()
        ]
        try:
            _merge_into_csv(output_path / f"{d_str}.csv", csv_rows, overwrite=True)
            csv_ok += 1
        except OSError as exc:
            csv_fail += 1
            logger.debug("CSV 寫入失敗 %s: %s", d_str, exc)

    if csv_fail:
        logger.warning("CSV 同步：成功 %d 日，失敗 %d 日（DuckDB 已更新，CSV 可用 --reimport 補）", csv_ok, csv_fail)

    logger.info("Yahoo Finance 補齊完成：upsert %d 筆進 DuckDB", total)
    return total


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
