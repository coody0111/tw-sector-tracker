"""
歷史行情補齊

方式：
  1. backfill_twse_monthly()     — TWSE STOCK_DAY + TPEx st43 逐股月別（完整覆蓋上市+上櫃）
  2. backfill_yfinance()         — Yahoo Finance 逐股月別（不需 token，雙市場都支援）
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

import urllib3
import pandas as pd
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"

_HEADERS_TWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
}

# FinMind 連續失敗超過此數就視為 rate-limit 到上限，提早退出
_CONSECUTIVE_FAIL_LIMIT = 30

_csv_lock = threading.Lock()
_block_lock = threading.Lock()


def _looks_like_twse_block(resp) -> bool:
    """偵測 TWSE 資安擋頁（WAF block／IP 被限流），區別於合法的『該月無資料』JSON 回應。
    合法回應一律是 status 200 + JSON content-type，即使 stat != OK 也一樣；
    擋頁則是 30x 導向 + text/html，這裡專門抓這種情況。
    """
    ctype = resp.headers.get("Content-Type", "")
    return resp.status_code != 200 or "json" not in ctype.lower()


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
        try:
            merged.to_csv(path, index=False, encoding="utf-8-sig")
        except OSError as exc:
            logger.warning("寫入 %s 失敗（可能被鎖定，例如 OneDrive 同步中）：%s，跳過該日期", path.name, exc)
            return False
    return True


def _collect_rows_by_date(day_rows: dict, rows: list) -> None:
    """把逐股回傳資料按交易日收集，保留 row 供後續寫入。"""
    for row in rows:
        day_rows[row["_date"]].append(row)


def _clear_price_csvs(output_path: Path) -> None:
    """清除既有行情 CSV；被其他程式鎖定的檔案保留並記錄。"""
    deleted = skipped = 0
    for path in output_path.glob("*.csv"):
        try:
            path.unlink()
            deleted += 1
        except PermissionError:
            skipped += 1
    if deleted or skipped:
        logger.info("清除舊 CSV：刪除 %d 個，跳過 %d 個（被鎖定）", deleted, skipped)


def _write_price_rows(output_path: Path, day_rows: dict) -> tuple[int, int]:
    """寫入按日期分組的行情，回傳（更新日數, 總筆數）。"""
    written = 0
    for date_str, rows in sorted(day_rows.items()):
        if _merge_into_csv(output_path / f"{date_str}.csv", rows, overwrite=True):
            written += 1
    return written, sum(len(rows) for rows in day_rows.values())


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


def _fetch_stock_months(sid: str, month_starts: list, stop_event: threading.Event = None) -> tuple[str, list]:
    """
    抓取單支 TWSE 股票的所有月份資料（只用於已確認為 TWSE 的股票）。
    stop_event：跨 thread 共用，偵測到 TWSE 封鎖時會被設起來，之後所有 thread
    看到就直接跳出、不再送新請求，避免在被封鎖期間繼續狂打。
    回傳 (stock_id, rows_list)
    """
    rows = []

    for mo in month_starts:
        if stop_event is not None and stop_event.is_set():
            break  # 已偵測到封鎖，不再送出新請求

        date_str = mo.strftime("%Y%m%d")
        for attempt in range(3):
            try:
                resp = requests.get(
                    TWSE_STOCK_DAY_URL,
                    params={"stockNo": sid, "date": date_str, "response": "json"},
                    headers=_HEADERS_TWSE,
                    timeout=15,
                    verify=False,
                )
                if _looks_like_twse_block(resp):
                    with _block_lock:
                        if stop_event is not None and not stop_event.is_set():
                            stop_event.set()
                            logger.error(
                                "TWSE 疑似封鎖此 IP（status=%d, content-type=%s），"
                                "中止 Phase 1 剩餘請求，本次不會覆蓋現有歷史資料",
                                resp.status_code, resp.headers.get("Content-Type", ""),
                            )
                    break  # 不重試，換下一個月（stop_event 會讓其他 thread 立即跳出）

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

                    if close <= 0:  # 零成交/停牌股偶爾回傳 close=0，比照 realtime.py 的防呆跳過
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


def _fetch_yfinance_one_stock(
    sid: str,
    ticker: str,
    start_date: str,
    end_date: str,
    max_retries: int = 2,
    pause_state: dict = None,
    pause_every: int = 100,
) -> tuple[str, list]:
    """
    逐支抓單一股票的 yfinance 歷史行情（ticker 已含 .TW/.TWO 後綴）。
    用 Ticker.history()（不是批次 yf.download()）+ 隨機延遲 + 失敗重試退避，
    降低被 Yahoo 限流的風險（比對 downloader_tw.py 驗證過的防封鎖手法）。

    抓取範圍會往前多抓 5 個日曆天當緩衝，這樣區間內第一個交易日才有真正的
    前一日收盤價可以算漲跌，不會出現「第一天 change_pct 一律是 0」這種假數值
    （緩衝天數本身不會出現在回傳結果裡，只用來算後面幾天的漲跌）。

    pause_state：跨 thread 共用的 {"lock": threading.Lock(), "count": 0}。
    每完成 pause_every 支，剛好完成那支的 worker 會自己暫停一下，讓限速
    真正作用在 worker 身上（不是像主執行緒 as_completed 迴圈裡暫停那樣，
    完全不影響其他還在跑的 worker 繼續送請求）。

    回傳 (stock_id, rows_list)。
    """
    import random
    import yfinance as yf

    time.sleep(random.uniform(0.5, 1.2))

    buffer_start = (date.fromisoformat(start_date) - timedelta(days=5)).isoformat()
    rows: list = []

    for attempt in range(max_retries + 1):
        try:
            hist = yf.Ticker(ticker).history(start=buffer_start, end=end_date, timeout=15)
            if hist is not None and not hist.empty:
                hist = hist.reset_index()
                closes = hist["Close"].astype(float).tolist()
                for i, row in hist.iterrows():
                    if i == 0:
                        continue  # 緩衝天數的第一筆，沒有更早資料可比較，跳過
                    dt = row["Date"]
                    d_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
                    if d_str < start_date:
                        continue  # 緩衝天數，只用來當前面的 prev_close，不放進輸出
                    close = closes[i]
                    if close <= 0:  # yfinance 偶爾對停牌/冷門股回傳 0，比照 realtime.py 的防呆跳過
                        continue
                    prev = closes[i - 1]
                    change = round(close - prev, 2)
                    change_pct = round(change / prev * 100, 2) if prev else 0.0
                    rows.append({
                        "stock_id":   sid,
                        "close":      round(close, 2),
                        "change":     change,
                        "change_pct": change_pct,
                        "volume":     max(0, int(row.get("Volume") or 0) // 1000),
                        "_date":      d_str,
                    })
                break
        except Exception as exc:
            logger.debug("  yfinance %s (%s) 第%d次失敗: %s", sid, ticker, attempt + 1, exc)
        if attempt < max_retries:
            time.sleep(random.uniform(3, 7))

    if pause_state is not None:
        should_pause = False
        with pause_state["lock"]:
            pause_state["count"] += 1
            if pause_state["count"] % pause_every == 0:
                should_pause = True
        if should_pause:
            time.sleep(random.uniform(5, 10))

    return sid, rows


# 成功率低於此比例，視為疑似被限流，不清空舊 CSV（避免用不完整資料覆蓋現有歷史）
_YFINANCE_MIN_SUCCESS_RATE = 0.5


def backfill_yfinance(
    stock_ids: List[str],
    exchange_map: dict,
    months: int = 19,
    output_dir: str = "data/daily_prices",
    workers: int = 3,
    clean: bool = True,
    today: date = None,
) -> int:
    """
    用 Yahoo Finance 補齊歷史行情，不需要 token，TWSE（.TW）+ TPEx（.TWO）都支援。
    逐支抓（Ticker.history()），搭配隨機延遲、失敗重試退避、每 100 支額外暫停、
    降並發（預設 3），取代舊版批次 yf.download() 容易被 Yahoo 限流擋掉的做法。
    """
    today = today or date.today()
    start = _first_month_start(today, months)
    start_str = start.isoformat()
    end_str = (today + timedelta(days=1)).isoformat()

    def _ticker_for(sid: str) -> str:
        return f"{sid}.TW" if exchange_map.get(sid) == "TWSE" else f"{sid}.TWO"

    logger.info(
        "yfinance 逐股補齊：%d 支股票  %s ~ %s  workers=%d",
        len(stock_ids), start_str, end_str, workers,
    )

    day_rows: dict = defaultdict(list)
    pause_state = {"lock": threading.Lock(), "count": 0}
    ok = 0
    done = 0
    total = len(stock_ids)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _fetch_yfinance_one_stock, sid, _ticker_for(sid), start_str, end_str,
                pause_state=pause_state,
            ): sid
            for sid in stock_ids
        }
        for fut in as_completed(futures):
            sid, rows = fut.result()
            done += 1
            if rows:
                _collect_rows_by_date(day_rows, rows)
                ok += 1
            if done % 50 == 0 or done == total:
                logger.info("  yfinance [%d/%d]  成功=%d", done, total, ok)

    logger.info("yfinance 完成：成功 %d / 共 %d 支", ok, total)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    success_rate = (ok / total) if total else 0.0
    if clean and success_rate < _YFINANCE_MIN_SUCCESS_RATE:
        logger.error(
            "yfinance 成功率過低（%d/%d = %.0f%%），疑似被限流。為避免用不完整資料"
            "覆蓋掉現有歷史，本次跳過清空舊 CSV。",
            ok, total, success_rate * 100,
        )
        clean = False

    if clean:
        _clear_price_csvs(output_path)

    written, total_records = _write_price_rows(output_path, day_rows)
    logger.info("補齊完成：寫入/更新 %d 日，共 %d 筆", written, total_records)
    return written


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
                    if close <= 0:  # FinMind 偶爾對冷門股回傳 close=0（已實測發生過），比照 realtime.py 的防呆跳過
                        continue
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

    clean=True（預設）：Phase 1 成功（未被 TWSE 封鎖）才會刪除現有 CSV 確保乾淨起始點；
                       若偵測到封鎖，為了不讓現有歷史資料比執行前更差，直接放棄本次寫入、
                       完全不動現有 CSV。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

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
    stop_event = threading.Event()

    # Phase 1: TWSE 逐股月別（並行）
    logger.info("Phase 1 TWSE 逐股月別 STOCK_DAY：workers=%d ...", workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_stock_months, sid, month_starts, stop_event): sid
            for sid in twse_stocks
        }
        done = 0
        for fut in as_completed(futures):
            sid, rows = fut.result()
            done += 1
            if rows:
                _collect_rows_by_date(day_rows, rows)
                twse_done += 1
            if done % 50 == 0 or done == len(twse_stocks):
                total_so_far = sum(len(v) for v in day_rows.values())
                logger.info(
                    "  [%d/%d 股]  TWSE成功=%d  目前 %d 筆",
                    done, len(twse_stocks), twse_done, total_so_far,
                )
    logger.info("Phase 1 完成：TWSE %d 支成功（共 %d 支）", twse_done, len(twse_stocks))

    twse_blocked = stop_event.is_set()
    if twse_blocked:
        logger.error(
            "TWSE 疑似封鎖此 IP，Phase 1 未完整取得資料（已成功的部分仍會保留、寫入）。"
            "為避免用不完整資料覆蓋掉還沒抓到的 TWSE 股票，本次跳過清空舊 CSV 這步。"
        )

    # Phase 2: TPEx 逐股 via FinMind TaiwanStockPrice — 跟 TWSE 是不同服務，
    # 不受 TWSE 封鎖影響，就算 Phase 1 被擋也照常執行。
    if tpex_stocks:
        if not finmind_token:
            logger.warning("Phase 2 跳過：未提供 finmind_token，TPEx %d 支無法補齊", len(tpex_stocks))
        else:
            logger.info("Phase 2 TPEx via FinMind：%d 支（每日上限 600 次）...", len(tpex_stocks))
            _fetch_finmind_history(
                tpex_stocks, start.isoformat(), today.isoformat(), day_rows, finmind_token
            )

    if clean and not twse_blocked:
        _clear_price_csvs(output_path)

    written, total_records = _write_price_rows(output_path, day_rows)
    logger.info("補齊完成：寫入/更新 %d 日，共 %d 筆", written, total_records)
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
    from scrapers.chips import fetch_margin_all_twse, TWSEBlockedError
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
        except TWSEBlockedError as exc:
            logger.error(
                "  [%d/%d] %s 疑似被 TWSE 封鎖：%s，提早中止剩餘 %d 日",
                i, len(trade_days), d_str, exc, len(trade_days) - i,
            )
            break
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
    from scrapers.chips import fetch_institutional, TWSEBlockedError
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

        except TWSEBlockedError as exc:
            logger.error(
                "  [%d/%d] %s 疑似被 TWSE 封鎖：%s，提早中止剩餘 %d 日",
                i, len(trade_days), d_str, exc, len(trade_days) - i,
            )
            break
        except Exception as exc:
            logger.warning("  [%d/%d] %s 失敗: %s", i, len(trade_days), d_str, exc)

        time.sleep(sleep_sec)

    logger.info("法人補齊完成：成功寫入 %d 個交易日", written)
    return written
