import argparse
import logging
import random
import subprocess
import sys
import time
import pandas as pd
import requests
from datetime import date, timedelta
from pathlib import Path

from scrapers.moneydj import scrape_industry_sectors
from scrapers.daily_prices import fetch_prices_for_stocks
from scrapers.realtime import fetch_realtime_prices
from scrapers.chips import fetch_institutional, fetch_institutional_tpex, fetch_margin_all_twse, fetch_margin_all_tpex, fetch_foreign_holding_twse, fetch_foreign_holding_tpex, TWSEBlockedError
from scrapers.taiex import fetch_taiex_index
from scrapers.backfill import backfill_twse_monthly, backfill_institutional, backfill_margin, backfill_yfinance
from processors.changes import detect_changes
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, calc_stock_sparklines, get_stock_chips_ranking, get_margin_divergence, calc_market_breadth, calc_capital_concentration, classify_market_regime
from storage.csv_writer import CsvWriter
from export.html_generator import generate as generate_html
from export.chips_generator import generate as generate_chips_html
from export.momentum_generator import (
    market_permission, classify_sector_state, build_sector_priority,
    build_decision_table, selloff_risk_zone, build_streak_cards,
    generate as generate_momentum_html,
)
from processors.observation_scores import calc_meta_observation_scores
from screener.database import init_db, import_csv_prices, import_sector_stocks, get_chips_today
from screener.institutional import scan_institutional
from screener.signals import scan_volume_turnover, scan_momentum_health, scan_bullish_alignment_new_high, scan_consecutive_limit_up
from screener.backtest import run_backtest, print_summary as print_backtest_summary, CHIPS_RULES

UNIVERSE_PATH = Path("data/stock_universe.csv")


def _prev_trading_day(d: date) -> date:
    """回前一個交易日（跳過週末與國定假日）。"""
    from config import is_trading_day
    d -= timedelta(days=1)
    while not is_trading_day(d.isoformat()):
        d -= timedelta(days=1)
    return d


def _retry_fetch(fn, *args, retries: int = 3, backoff: tuple = (1.0, 3.0), retry_on=(Exception,), **kwargs):
    """通用重試小幫手：對 retry_on 型別的例外重試 retries 次，每次退避在 backoff 秒數範圍內
    隨機（比照 scrapers/shareholder.py 既有的 TDCC 抓取重試模式，已驗證穩定）。

    背景（debug-tasks.md #6）：TWSE/TPEx 籌碼資料抓取偶發單邊整批失敗（例：2026-07-13
    TPEx 三大法人/融資融券當下完全正常，但當次抓取因暫時性網路問題整批漏掉），且
    institutional/margin 的 TPEx 端 API 只能查「當下」、沒有歷史回補路徑，失敗一次
    當天資料就永久遺失，值得多花幾秒重試。

    retries 次全部失敗時，把最後一次的例外原樣往外拋——呼叫端既有的 except 分支（例如
    TWSE 的『尚未發布』ValueError 判斷、日期回退邏輯）不用跟著改。"""
    last_exc = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except retry_on as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(random.uniform(*backoff))
    raise last_exc

LOG_DIR = Path("logs")


def _logging_handlers() -> list[logging.Handler]:
    """建立 console handler，並在 log 檔可寫時額外啟用 file handler。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        LOG_DIR.mkdir(exist_ok=True)
        handlers.insert(0, logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8"))
    except OSError as exc:
        print(f"Warning: 無法寫入 {LOG_DIR / 'run.log'}，本次只輸出到終端：{exc}", file=sys.stderr)
    return handlers


def _configure_logging() -> None:
    """只在應用程式尚未設定 logging 時建立 handler。"""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=_logging_handlers(),
    )


_configure_logging()
logger = logging.getLogger(__name__)


def _update_chips_db(trade_date: date, stock_ids: list) -> None:
    """每日收盤後更新籌碼資料庫。"""
    try:
        init_db()
        n = import_csv_prices()
        logger.info("DuckDB: 匯入行情 %d 筆", n)
        import_sector_stocks()
    except Exception as exc:
        logger.warning("DuckDB 行情匯入失敗: %s", exc)

    try:
        inst_date = trade_date
        try:
            inst_df = _retry_fetch(fetch_institutional, inst_date,
                                    retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        except TWSEBlockedError as exc:
            logger.warning("三大法人抓取失敗（非『尚未發布』）：%s，本次跳過", exc)
            inst_df = pd.DataFrame()
        except ValueError:
            inst_date = _prev_trading_day(trade_date)
            logger.info("三大法人今日尚未發布，改抓前一交易日 %s", inst_date)
            inst_df = _retry_fetch(fetch_institutional, inst_date,
                                    retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        if not inst_df.empty:
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute("DELETE FROM institutional WHERE date = ?", [inst_date.isoformat()])
            con.execute("INSERT INTO institutional SELECT * FROM inst_df")
            con.close()
            logger.info("三大法人寫入 %d 筆（%s）", len(inst_df), inst_date)
    except Exception as exc:
        logger.warning("三大法人寫入失敗: %s", exc)

    try:
        # TPEx OpenAPI 沒有日期參數，只回傳當下這支 API 認定的「今天」，可能跟 trade_date 對不上
        # （例如 TPEx 還沒更新），所以用回應裡自己的 date 欄位為準，不強套 trade_date。
        # DELETE 只刪這批 TPEx stock_id，避免把上面剛寫入的 TWSE 同日資料誤刪。
        inst_tpex_df = _retry_fetch(fetch_institutional_tpex)
        if not inst_tpex_df.empty:
            resp_dates = inst_tpex_df["date"].unique().tolist()
            if len(resp_dates) > 1:
                logger.warning("TPEx 三大法人回應包含多個日期 %s，只留最新一天", resp_dates)
                inst_tpex_df = inst_tpex_df[inst_tpex_df["date"] == max(resp_dates)]
            resp_date = inst_tpex_df["date"].iloc[0]
            if resp_date != inst_date.isoformat():
                logger.info("TPEx 三大法人目前是 %s（跟 TWSE 端 %s 不同天，可能尚未更新）", resp_date, inst_date)
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute(
                "DELETE FROM institutional WHERE date = ? AND stock_id IN (SELECT stock_id FROM inst_tpex_df)",
                [resp_date],
            )
            con.execute("INSERT INTO institutional SELECT * FROM inst_tpex_df")
            con.close()
            logger.info("TPEx 三大法人寫入 %d 筆（%s）", len(inst_tpex_df), resp_date)
    except Exception as exc:
        logger.warning("TPEx 三大法人寫入失敗: %s", exc)

    try:
        marg_date = trade_date
        try:
            margin_df = _retry_fetch(fetch_margin_all_twse, marg_date,
                                      retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        except TWSEBlockedError as exc:
            logger.warning("融資融券抓取失敗（非『尚未發布』）：%s，本次跳過", exc)
            margin_df = pd.DataFrame()
        except ValueError:
            marg_date = _prev_trading_day(trade_date)
            logger.info("融資融券今日尚未發布，改抓前一交易日 %s", marg_date)
            margin_df = _retry_fetch(fetch_margin_all_twse, marg_date,
                                      retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        if not margin_df.empty:
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute("DELETE FROM margin WHERE date = ?", [marg_date.isoformat()])
            con.execute("INSERT INTO margin SELECT * FROM margin_df")
            con.close()
            logger.info("融資融券寫入 %d 筆（%s）", len(margin_df), marg_date)
    except Exception as exc:
        logger.warning("融資融券寫入失敗: %s", exc)

    try:
        margin_tpex_df = _retry_fetch(fetch_margin_all_tpex)
        if not margin_tpex_df.empty:
            resp_dates = margin_tpex_df["date"].unique().tolist()
            if len(resp_dates) > 1:
                logger.warning("TPEx 融資融券回應包含多個日期 %s，只留最新一天", resp_dates)
                margin_tpex_df = margin_tpex_df[margin_tpex_df["date"] == max(resp_dates)]
            resp_date = margin_tpex_df["date"].iloc[0]
            if resp_date != marg_date.isoformat():
                logger.info("TPEx 融資融券目前是 %s（跟 TWSE 端 %s 不同天，可能尚未更新）", resp_date, marg_date)
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute(
                "DELETE FROM margin WHERE date = ? AND stock_id IN (SELECT stock_id FROM margin_tpex_df)",
                [resp_date],
            )
            con.execute("INSERT INTO margin SELECT * FROM margin_tpex_df")
            con.close()
            logger.info("TPEx 融資融券寫入 %d 筆（%s）", len(margin_tpex_df), resp_date)
    except Exception as exc:
        logger.warning("TPEx 融資融券寫入失敗: %s", exc)

    try:
        fh_date = trade_date
        try:
            fh_df = _retry_fetch(fetch_foreign_holding_twse, fh_date,
                                  retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        except TWSEBlockedError as exc:
            logger.warning("外資持股%%抓取失敗（非『尚未發布』）：%s，本次跳過", exc)
            fh_df = pd.DataFrame()
        except ValueError:
            fh_date = _prev_trading_day(trade_date)
            logger.info("外資持股%%今日尚未發布，改抓前一交易日 %s", fh_date)
            fh_df = _retry_fetch(fetch_foreign_holding_twse, fh_date,
                                  retry_on=(TWSEBlockedError, requests.exceptions.RequestException))
        if not fh_df.empty:
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute("DELETE FROM foreign_holdings WHERE date = ?", [fh_date.isoformat()])
            con.execute("INSERT INTO foreign_holdings SELECT * FROM fh_df")
            con.close()
            logger.info("外資持股%% 寫入 %d 筆（%s）", len(fh_df), fh_date)
    except Exception as exc:
        logger.warning("外資持股%% 寫入失敗: %s", exc)

    try:
        # TPEx 沒有日期參數，只回傳「當下」的排行表；用回應自己的 date 為準，不強套 trade_date。
        # DELETE 只刪這批 TPEx stock_id，避免誤刪上面剛寫入的 TWSE 同日資料。
        fh_tpex_df = _retry_fetch(fetch_foreign_holding_tpex)
        if not fh_tpex_df.empty:
            resp_dates = fh_tpex_df["date"].unique().tolist()
            if len(resp_dates) > 1:
                logger.warning("TPEx 外資持股%% 回應包含多個日期 %s，只留最新一天", resp_dates)
                fh_tpex_df = fh_tpex_df[fh_tpex_df["date"] == max(resp_dates)]
            resp_date = fh_tpex_df["date"].iloc[0]
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute(
                "DELETE FROM foreign_holdings WHERE date = ? AND stock_id IN (SELECT stock_id FROM fh_tpex_df)",
                [resp_date],
            )
            con.execute("INSERT INTO foreign_holdings SELECT * FROM fh_tpex_df")
            con.close()
            logger.info("TPEx 外資持股%% 寫入 %d 筆（%s）", len(fh_tpex_df), resp_date)
    except Exception as exc:
        logger.warning("TPEx 外資持股%% 寫入失敗: %s", exc)


def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        if os.path.exists("docs/momentum.html"):
            files_to_add.append("docs/momentum.html")
        subprocess.run(["git", "add"] + files_to_add, check=True)
        # 只看這幾個產出檔有沒有變動（限定範圍，不受其他 staged 變更影響判斷）
        result = subprocess.run(["git", "diff", "--cached", "--quiet", "--"] + files_to_add)
        if result.returncode == 0:
            logger.info("No HTML changes to push.")
            return
        # 只 commit 這幾個檔（明確限定範圍）——避免把當下其他 staged 的變更（例如手動
        # git add/rm 到一半的東西）一起打包 commit+push 上去
        subprocess.run(
            ["git", "commit", "-m", f"update: sector performance {trade_date.isoformat()}", "--"] + files_to_add,
            check=True,
        )
        # push 前先跟遠端同步：兩台機各自 push 會分岔，先 pull --rebase 把本機這筆接到
        # 遠端最新之後再推。--autostash 保護工作區；若 rebase 撞衝突就中止並保持乾淨，
        # 本機 commit 保留、留給人工處理，不讓自動流程卡在半完成的 rebase
        pull = subprocess.run(["git", "pull", "--rebase", "--autostash"])
        if pull.returncode != 0:
            def _rebase_in_progress() -> bool:
                # worktree-safe：用 git rev-parse --git-path 取正確的 git 目錄
                for name in ("rebase-merge", "rebase-apply"):
                    p = subprocess.run(
                        ["git", "rev-parse", "--git-path", name],
                        capture_output=True, text=True,
                    )
                    if p.returncode == 0 and os.path.isdir(p.stdout.strip()):
                        return True
                return False
            if _rebase_in_progress():
                # 真的有 rebase 卡住（撞衝突）才 abort，保持工作區乾淨
                subprocess.run(["git", "rebase", "--abort"])
                logger.warning(
                    "git pull --rebase 有衝突，已中止 rebase；本機 commit 已保留，"
                    "請手動 `git pull` 解衝突後再 push。"
                )
            else:
                # 非衝突原因失敗（無 upstream／網路斷）：沒有 rebase 可 abort
                logger.warning(
                    "git pull --rebase 失敗（可能無 upstream 或網路問題）；"
                    "本機 commit 已保留，未 push。"
                )
            return
        subprocess.run(["git", "push"], check=True)
        logger.info("Pushed to GitHub Pages.")
    except Exception as exc:
        logger.warning("Git push failed: %s", exc)


def backfill_twse(months: int = 6, workers: int = 3) -> None:
    """TWSE 逐股月別補齊（STOCK_DAY 歷史 API）+ TPEx via FinMind"""
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv，請先確認資料目錄。")
        return
    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    exchange_map = dict(zip(universe_df["stock_id"], universe_df["exchange"])) if "exchange" in universe_df.columns else None
    from scrapers.chips import FINMIND_TOKEN
    logger.info("=== 逐股月別補齊（往前 %d 個月，workers=%d）===", months, workers)
    n = backfill_twse_monthly(
        stock_ids, months=months, workers=workers, clean=True,
        exchange_map=exchange_map, finmind_token=FINMIND_TOKEN,
    )
    if n > 0:
        from screener.database import reimport_db
        init_db()
        imported = reimport_db()
        logger.info("DuckDB 更新：共 %d 筆", imported)
    logger.info("=== 補齊完成，共寫入/更新 %d 日 ===", n)


def backfill_yf(months: int = 19, workers: int = 3) -> None:
    """Yahoo Finance 逐股補齊（TWSE+TPEx 都支援，不需要 token）"""
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv，請先確認資料目錄。")
        return
    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    exchange_map = dict(zip(universe_df["stock_id"], universe_df["exchange"])) if "exchange" in universe_df.columns else {}
    logger.info("=== Yahoo Finance 逐股補齊（往前 %d 個月，workers=%d）===", months, workers)
    n = backfill_yfinance(stock_ids, exchange_map=exchange_map, months=months, workers=workers, clean=True)
    if n > 0:
        from screener.database import reimport_db
        init_db()
        imported = reimport_db()
        logger.info("DuckDB 更新：共 %d 筆", imported)
    logger.info("=== 補齊完成，共寫入/更新 %d 日 ===", n)


def backfill_marg(days: int = 60) -> None:
    """補齊過去 N 個工作日的 TWSE 融資融券資料"""
    logger.info("=== 融資融券補齊（往前 %d 個工作日）===", days)
    n = backfill_margin(days=days)
    logger.info("=== 融資補齊完成，共寫入 %d 個交易日 ===", n)


def backfill_inst(days: int = 60) -> None:
    """補齊過去 N 個工作日的三大法人資料（TWSE T86，每日一次 API）"""
    logger.info("=== 法人資料補齊（往前 %d 個工作日）===", days)
    n = backfill_institutional(days=days)
    logger.info("=== 法人補齊完成，共寫入 %d 個交易日 ===", n)


def _update_shareholder() -> None:
    """抓 TDCC 集保持股分散表最新週，計算大戶持倉比例與週變化並存入 DB。"""
    from scrapers.shareholder import fetch_shareholder_weekly, save_to_db as sh_save
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    logger.info("=== 集保持股分散表更新（%d 支股票）===", len(stock_ids))
    rows = fetch_shareholder_weekly(stock_ids)
    n = sh_save(rows)
    logger.info("=== 集保更新完成，寫入 %d 筆 ===", n)


def _update_insider_holdings() -> None:
    """抓公開資訊觀測站內部人持股（公司派/大股東），計算月變化並存入 DB。"""
    from scrapers.insider_holdings import fetch_insider_holdings_monthly, save_to_db as ih_save
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    logger.info("=== 內部人持股更新（%d 支股票）===", len(stock_ids))
    rows, blocked_ids = fetch_insider_holdings_monthly(stock_ids)
    n = ih_save(rows)
    logger.info("=== 內部人持股更新完成，寫入 %d 筆 ===", n)
    if blocked_ids:
        logger.warning(
            "=== %d 支股票被 MOPS 限流擋掉（非真正查無資料），建議稍後重跑補齊，"
            "不要當成這批股票沒有內部人持股 ===",
            len(blocked_ids),
        )


def _load_insider_ranking_rows(db_path: str = "data/screener.db") -> list[dict]:
    """讀取每檔最新董監持股，獨立建立排行榜資料，不依賴 TDCC 入選名單。"""
    import duckdb as _ddb

    try:
        con = _ddb.connect(db_path, read_only=True)
        insider_df = con.execute("""
            SELECT stock_id, report_date, company_shares, company_chg, company_pledge_pct,
                   major_holder_shares, major_holder_chg, major_holder_pledge_pct
            FROM insider_holdings
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY report_date DESC) = 1
        """).fetchdf()
        price_df = con.execute("""
            SELECT stock_id, close, change_pct
            FROM daily_prices
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
        """).fetchdf()
        con.close()
    except Exception as exc:
        logger.warning("董監持股排行資料載入失敗: %s", exc)
        return []

    if insider_df.empty:
        return []
    universe = pd.read_csv(UNIVERSE_PATH, dtype=str, usecols=["stock_id", "stock_name", "meta_sector"])
    info_map = universe.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
    names_path = Path("data/stock_names.csv")
    if names_path.exists():
        try:
            for row in pd.read_csv(names_path, dtype=str).itertuples():
                info_map.setdefault(str(row.stock_id), {"stock_name": row.stock_name, "meta_sector": ""})
        except Exception:
            pass
    price_df["stock_id"] = price_df["stock_id"].astype(str)
    price_map = price_df.set_index("stock_id")[["close", "change_pct"]].to_dict("index")

    rows = []
    for row in insider_df.itertuples():
        sid = str(row.stock_id)
        info, px = info_map.get(sid, {}), price_map.get(sid, {})
        rows.append({
            "stock_id": sid,
            "stock_name": info.get("stock_name", ""),
            "meta_sector": info.get("meta_sector", ""),
            "report_date": str(row.report_date)[:10],
            "close": None if pd.isna(px.get("close")) else px.get("close"),
            "change_pct": None if pd.isna(px.get("change_pct")) else px.get("change_pct"),
            "company_shares": None if pd.isna(row.company_shares) else int(row.company_shares),
            "company_chg": None if pd.isna(row.company_chg) else int(row.company_chg),
            "company_pledge_pct": None if pd.isna(row.company_pledge_pct) else float(row.company_pledge_pct),
            "major_holder_shares": None if pd.isna(row.major_holder_shares) else int(row.major_holder_shares),
            "major_holder_chg": None if pd.isna(row.major_holder_chg) else int(row.major_holder_chg),
            "major_holder_pledge_pct": None if pd.isna(row.major_holder_pledge_pct) else float(row.major_holder_pledge_pct),
        })
    return rows


def _backfill_shareholder(weeks: int = 4) -> None:
    """補齊最近 N 週視窗內、DB 還缺的集保持股分散表（只補缺的那幾週，不重抓已有的）。"""
    from scrapers.shareholder import (
        fetch_shareholder_weekly, save_to_db as sh_save, get_available_dates,
        get_existing_shareholder_dates, plan_backfill_dates, recompute_all_history,
    )
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    available = get_available_dates()
    existing = get_existing_shareholder_dates()
    # #7：只補「最近 weeks 週視窗內 DB 還缺的那幾週」，不再固定往回數 N 週重抓已有的；
    # 中間缺的一週（例 06-18）只要落在視窗內就會被抓回。由舊到新寫入（save_to_db 的
    # week_chg/streak 拿「DB 現有最新一筆」當基準，順序不能反）。
    target_dates = plan_backfill_dates(available, existing, weeks)
    if not target_dates:
        logger.info("=== 集保：最近 %d 週視窗內無缺週，無需回補 ===", weeks)
        return
    logger.info("=== 集保回補缺週（由舊到新）：%s ===", target_dates)
    for d_str in target_dates:
        logger.info("  抓 %s ...", d_str)
        rows = fetch_shareholder_weekly(stock_ids, date_str=d_str)
        n = sh_save(rows)
        logger.info("  %s 寫入 %d 筆", d_str, n)
    # 填的是中間缺口（例 06-18），缺口後那週（06-26）原本對到更舊的週、且被缺週防護標成
    # NULL；現在缺口補上了，全表重算一次讓每筆 week_chg/streak 接回正確的相鄰週基準。
    updated = recompute_all_history()
    logger.info("=== 集保回補完成，全表重算 week_chg/streak：%d 筆 ===", updated)


def _full_rebuild(months: int = 19, workers: int = 3) -> None:
    """
    一鍵重建歷史行情：
    Step 1  刪舊 CSV + 用 STOCK_DAY 逐股月別重抓（TWSE）+ FinMind（TPEx）
    Step 2  reimport_db：清空 DuckDB 後從乾淨 CSV 重建
    """
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv")
        return

    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    exchange_map = dict(zip(universe_df["stock_id"], universe_df["exchange"])) if "exchange" in universe_df.columns else None
    from scrapers.chips import FINMIND_TOKEN
    logger.info("=== Step 1：逐股月別重抓（%d 月，workers=%d）===", months, workers)
    n = backfill_twse_monthly(
        stock_ids, months=months, workers=workers, clean=True,
        exchange_map=exchange_map, finmind_token=FINMIND_TOKEN,
    )
    logger.info("Step 1 完成：更新 %d 個交易日 CSV", n)

    if n == 0:
        logger.error("Step 1 未寫入任何 CSV，中止重建，DuckDB 維持現狀")
        return

    logger.info("=== Step 2：清空 DuckDB 並重建 ===")
    from screener.database import reimport_db
    total = reimport_db()
    logger.info("=== full-rebuild 完成：DuckDB 共 %d 筆 ===", total)


def update_sectors(limit: int = None) -> None:
    """從 MoneyDJ 更新族群成份股（耗時約 15 分鐘，每週跑一次即可）"""
    writer = CsvWriter(base_dir="data")
    logger.info("=== Updating sectors from MoneyDJ ===")

    industry_stocks = scrape_industry_sectors(limit=limit)
    logger.info("  -> %d records from %d sectors", len(industry_stocks),
                len({s.sector_code for s in industry_stocks}))

    all_records = [
        {"sector_type": s.sector_type, "sector_name": s.sector_name,
         "sector_code": s.sector_code, "stock_id": s.stock_id, "stock_name": s.stock_name}
        for s in industry_stocks
    ]
    writer.write_sector_stocks(all_records, date.today())
    logger.info("Sectors saved to data/sectors/industry_sectors.csv")
    logger.info("=== Done ===")


def run(trade_date: date = None, realtime: bool = False) -> None:
    """每日執行：讀取已存族群 → 抓 TWSE+TPEx 行情 → 計算績效 → 更新網站（約 10 秒）"""
    if trade_date is None:
        trade_date = date.today()
        if trade_date.weekday() >= 5:  # 週六=5, 週日=6 → 退回上週五
            trade_date = _prev_trading_day(trade_date)

    logger.info("=== TW Sector Tracker — %s ===", trade_date.isoformat())
    writer = CsvWriter(base_dir="data")

    # 1. 讀取股票清單（優先用 stock_universe.csv，fallback MoneyDJ sectors）
    universe_df = None
    if UNIVERSE_PATH.exists():
        universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
        unique_ids = universe_df["stock_id"].tolist()
        logger.info("Loaded %d stocks from stock_universe.csv.", len(unique_ids))
        # 仍讀取 sectors_df 供舊版 HTML 函式 fallback
        sectors_df = writer.read_sector_stocks("industry")
    else:
        sectors_df = writer.read_sector_stocks("industry")
        if sectors_df.empty:
            logger.error("No sector data found. Run with --update-sectors first.")
            return
        unique_ids = list(sectors_df["stock_id"].astype(str).unique())
        logger.info("Loaded %d stocks across sectors from saved data.", len(unique_ids))

    yesterday_df = sectors_df.copy() if sectors_df is not None and not sectors_df.empty else pd.DataFrame()
    all_records = sectors_df.drop(columns=["date"], errors="ignore").to_dict("records") if sectors_df is not None and not sectors_df.empty else []

    # 2. 抓 TWSE + TPEx 行情（盤中即時 or 盤後收盤）
    if realtime:
        logger.info("Fetching real-time prices (mis.twse.com.tw)...")
        try:
            prices_df = fetch_realtime_prices(unique_ids)
            prices_df["stock_id"] = prices_df["stock_id"].astype(str)
            logger.info("  即時行情：%d 支", len(prices_df))
        except Exception as exc:
            logger.error("Real-time fetch failed: %s", exc)
            prices_df = None
    else:
        # 盤後 batch 的股價改用 realtime 同源（mis.twse.com.tw），與 --realtime 一致：
        # 收盤後 realtime 回的是收盤集合競價價（time=13:30），等同官方定案收盤，但沒有官方
        # TPEx endpoint 的「盤後定案延遲」問題（不會抓到昨日殘留值），盤中也不會退回昨天。
        # realtime 撈不到（盤前/假日/服務未提供）時，退回官方 TWSE+TPEx 收盤 API。
        logger.info("Fetching prices (realtime 同源 mis.twse.com.tw)...")
        prices_df = None
        try:
            prices_df = fetch_realtime_prices(unique_ids)
            prices_df["stock_id"] = prices_df["stock_id"].astype(str)
            logger.info("  即時同源：%d 支", len(prices_df))
        except Exception as exc:
            logger.warning("realtime 同源抓取失敗，改用官方收盤 API：%s", exc)
            prices_df = None
        if prices_df is None or prices_df.empty:
            logger.info("  realtime 無資料，改用官方 TWSE+TPEx 收盤...")
            try:
                prices_df = fetch_prices_for_stocks(unique_ids, trade_date)
                prices_df["stock_id"] = prices_df["stock_id"].astype(str)
                logger.info("  TWSE+TPEx total: %d stocks", len(prices_df))
            except Exception as exc:
                logger.error("Price fetch failed: %s. Continuing without prices.", exc)
                prices_df = None

    # 完整性保險絲：batch 模式下，探測股 2330（最大權值股，一定在）不在本次結果，
    # 代表 TWSE 抓取失敗/不完整（例如只剩 TPEx 的 518 支）。此時絕不可用殘缺資料覆蓋
    # 原本完整的檔案 + DuckDB + 推上 GitHub Pages——直接中止本次流程，保留既有完整資料，
    # 等 TWSE 恢復後重跑即可。（realtime 走另一條即時來源，不套用這個 batch 保險絲。）
    if not realtime and prices_df is not None and not prices_df.empty \
            and "2330" not in prices_df["stock_id"].values:
        logger.error(
            "🛑 完整性檢查失敗：探測股 2330 不在本次行情（TWSE 抓取失敗/不完整，只有 %d 支）。"
            "中止本次流程——不覆蓋完整檔案、不寫 DuckDB、不 push。請待 TWSE 恢復後重跑 python main.py。",
            len(prices_df),
        )
        return

    # 3. 寫入行情（盤前/非交易日不寫入重複資料）
    # 這道防呆是為了偵測「TWSE 官方收盤資料還沒公布」（批次模式），只適用於盤後批次抓取。
    # --realtime 抓的是當下即時快照，即使探測股價格剛好與前一天收盤相同（例如尚未成交、
    # API 延遲），也仍是「今天」的合法資料，不應該把 trade_date 切回前一天。
    prices_are_new = True
    if not realtime and prices_df is not None and not prices_df.empty:
        prev_day = _prev_trading_day(trade_date)
        prev_csv = Path(f"data/daily_prices/{prev_day.isoformat()}.csv")
        # 探測股固定用 2330（大型權值股，資料最穩定）。如果它不在這次抓到的資料裡
        # （例如 TWSE 抓取失敗/被封鎖，只剩 TPEx 資料），代表這批資料本身就不完整，
        # 不能拿任意一支替代股票來判斷「市場是否更新」——那支股票剛好跟昨天收盤
        # 價格相同純屬巧合，會誤判成「市場沒更新」而錯誤地把整批今日資料當成前一天。
        if prev_csv.exists() and "2330" in prices_df["stock_id"].values:
            try:
                prev_df = pd.read_csv(prev_csv, dtype={"stock_id": str})
                new_close = prices_df[prices_df["stock_id"] == "2330"]["close"].values
                old_close = prev_df[prev_df["stock_id"] == "2330"]["close"].values if "close" in prev_df.columns else []
                if len(new_close) and len(old_close) and float(new_close[0]) == float(old_close[0]):
                    logger.info("今日行情（%s）與前一交易日（%s）相同，市場尚未更新，切換基準日期", trade_date, prev_day)
                    prices_are_new = False
                    trade_date = prev_day
            except Exception:
                pass
        elif prev_csv.exists():
            logger.warning("探測股 2330 不在本次抓到的行情裡（可能 TWSE 抓取失敗或不完整），跳過『市場尚未更新』防呆檢查")

    if prices_are_new and prices_df is not None and not prices_df.empty:
        writer.write_daily_prices(prices_df, trade_date)
        logger.info("Daily prices written.")

    # 4. 偵測成份股異動
    today_df = pd.DataFrame(all_records)
    if not today_df.empty:
        today_df.insert(0, "date", trade_date.isoformat())

    changes = []
    if not yesterday_df.empty:
        changes += detect_changes(today_df, yesterday_df, "industry", trade_date.isoformat())

    if changes:
        writer.append_changes(changes)
        logger.info("%d composition changes detected.", len(changes))
    else:
        logger.info("No composition changes detected.")

    # 5. 計算族群績效 + 主族群績效
    perf = []
    meta_perf = []
    if prices_df is not None and not prices_df.empty:
        if universe_df is not None:
            # 新流程：stock_universe.csv 模式，每股只計一次
            meta_perf = calc_universe_performance(universe_df, prices_df)
            # 用 sub_sector 建立偽 sectors_df，計算小族群績效供分組區使用
            sub_sectors_df = universe_df[["stock_id", "sub_sector"]].rename(
                columns={"sub_sector": "sector_name"}
            ).copy()
            sub_sectors_df["sector_type"] = "industry"
            perf = calc_sector_performance(sub_sectors_df, prices_df)
            writer.write_sector_performance(perf, trade_date)
            # 讓 HTML 分組的個股卡片可展開：用 universe_df 建 sectors_df-like
            sectors_df = universe_df[["stock_id", "stock_name", "sub_sector"]].rename(
                columns={"sub_sector": "sector_name"}
            ).copy()
            sectors_df["sector_type"] = "industry"
            logger.info("Universe performance: %d META groups, %d sub-sectors.", len(meta_perf), len(perf))
        elif not today_df.empty:
            perf = calc_sector_performance(today_df, prices_df)
            meta_perf = calc_meta_performance(perf)
            writer.write_sector_performance(perf, trade_date)
            logger.info("Sector performance written (%d sectors, %d meta).", len(perf), len(meta_perf))

    # 6. 籌碼資料寫入 DuckDB
    _update_chips_db(trade_date, unique_ids)

    # 7. 產生 HTML + 推上 GitHub Pages
    if perf or meta_perf:
        try:
            chips_df = get_chips_today(trade_date.isoformat())
        except Exception:
            chips_df = pd.DataFrame()

        # 大盤分級儀表板：五級方向 + 資金集中度診斷（TAIEX 抓取失敗時整塊不顯示，不擋每日流程）
        market_regime = None
        try:
            from config import TAIEX_HEAVYWEIGHTS
            taiex = fetch_taiex_index(trade_date)
            breadth = calc_market_breadth(prices_df) if prices_df is not None else {}
            conc = calc_capital_concentration(prices_df, TAIEX_HEAVYWEIGHTS) if prices_df is not None else {}
            regime = classify_market_regime(
                taiex.get("change_pct"), breadth.get("breadth_ratio", 0.0), conc.get("divergence")
            )
            market_regime = {
                **regime,
                "taiex_close": taiex.get("close"),
                "taiex_change_pct": taiex.get("change_pct"),
                "taiex_date": taiex.get("date").isoformat() if taiex.get("date") else None,
                **breadth,
                **conc,
                "heavyweight_count": len(TAIEX_HEAVYWEIGHTS),
            }
            logger.info("大盤分級：%s（加權指數 %s，漲跌 %s%%，廣度 %.0f%%）",
                        regime["tier"], taiex.get("close"), taiex.get("change_pct"),
                        breadth.get("breadth_ratio", 0) * 100)
        except TWSEBlockedError as exc:
            logger.warning("TAIEX 指數抓取被擋，大盤分級儀表板本次不顯示：%s", exc)
        except Exception as exc:
            logger.warning("大盤分級計算失敗，本次不顯示：%s", exc)

        cum_data = calc_cumulative_meta(universe_df) if universe_df is not None else []
        meta_signals = calc_meta_signals(universe_df) if universe_df is not None else {}
        meta_chips = calc_meta_chips_signals(universe_df) if universe_df is not None else {}
        stock_sparklines = calc_stock_sparklines(universe_df) if universe_df is not None else {}
        stock_chips = get_stock_chips_ranking(universe_df) if universe_df is not None else {}
        margin_div = get_margin_divergence(universe_df) if universe_df is not None else {}
        # 近5/7/10/14日累積漲跌幅（收盤價比值法），index 族群個股表用；跟 chips.html Section 8 同一算法
        try:
            from screener.database import get_rolling_returns
            rolling_returns = get_rolling_returns((5, 7, 10, 14))
        except Exception:
            rolling_returns = {}

        try:
            vol_signals = scan_volume_turnover(trade_date.isoformat())
            if universe_df is not None and vol_signals:
                name_map = universe_df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
                for s in vol_signals:
                    info = name_map.get(s["stock_id"], {})
                    s["stock_name"] = info.get("stock_name", "")
                    s["meta_sector"] = info.get("meta_sector", "")
            logger.info("巨量換手訊號：%d 檔", len(vol_signals))
        except Exception as exc:
            logger.warning("巨量換手掃描失敗: %s", exc)
            vol_signals = []

        try:
            # universe_df 必須含 exchange 欄位，否則 calc_meta_observation_scores() 內部
            # _calc_chips_factor() 會 KeyError（見 debug-tasks.md 2026-07-18 條目提醒）。
            obs_universe_df = pd.read_csv(
                UNIVERSE_PATH, dtype=str,
                usecols=["stock_id", "stock_name", "meta_sector", "exchange"],
            )
            observation_scores = calc_meta_observation_scores(obs_universe_df)
        except Exception as exc:
            logger.warning("觀察分計算失敗，index.html 排序退回avg_change_pct、momentum頁本次不產生: %s", exc)
            observation_scores = {}

        generate_html(trade_date, pd.DataFrame(perf) if perf else pd.DataFrame(),
                      sectors_df=sectors_df,
                      prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                      chips_df=chips_df,
                      meta_perf=meta_perf,
                      universe_df=universe_df,
                      cum_data=cum_data,
                      meta_signals=meta_signals,
                      meta_chips=meta_chips,
                      stock_sparklines=stock_sparklines,
                      vol_turnover=vol_signals,
                      rolling_returns=rolling_returns,
                      market_regime=market_regime,
                      observation_scores=observation_scores)
        logger.info("HTML generated → docs/index.html")

        try:
            inst_results = scan_institutional(trade_date.isoformat(), lookback=40)
            if universe_df is not None:
                name_map = universe_df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
                # fallback: 從每日全市場名稱快取補齊 universe 以外的股票名字
                name_cache_path = Path("data/stock_names.csv")
                if name_cache_path.exists():
                    try:
                        cache_df = pd.read_csv(name_cache_path, dtype=str)
                        for _, r in cache_df.iterrows():
                            if r["stock_id"] not in name_map:
                                name_map[r["stock_id"]] = {"stock_name": r["stock_name"], "meta_sector": ""}
                    except Exception:
                        pass
                for row in inst_results:
                    info = name_map.get(row["stock_id"], {})
                    row["stock_name"] = info.get("stock_name", "")
                    row["meta_sector"] = info.get("meta_sector", "")
            logger.info("法人篩選：%d 檔有籌碼資料", len(inst_results))
        except Exception as exc:
            logger.warning("法人篩選失敗: %s", exc)
            inst_results = []
        insider_rows = _load_insider_ranking_rows()
        try:
            from screener.database import get_shareholder_top
            import duckdb as _ddb
            sh_df = get_shareholder_top()
            if not sh_df.empty:
                universe = pd.read_csv(UNIVERSE_PATH, dtype=str, usecols=["stock_id", "stock_name", "meta_sector"])
                name_map = universe.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")

                # 價格對齊集保週期：本週/上週各自查對應日期的收盤價（不是「最新交易日」）
                _dates = pd.unique(pd.concat([sh_df["date"], sh_df["prev_date"].dropna()]))
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _pdf = _con.execute(
                        "SELECT stock_id, date, close FROM daily_prices WHERE date IN (SELECT UNNEST(?))",
                        [list(_dates)],
                    ).fetchdf() if len(_dates) else pd.DataFrame()
                    _con.close()
                    _price_map = {(str(r["stock_id"]), str(r["date"])): r["close"] for _, r in _pdf.iterrows()}
                except Exception:
                    _price_map = {}

                # 內部人持股（公司派/大股東）：取每支股票最新一筆月資料
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _ihdf = _con.execute("""
                        SELECT stock_id, company_shares, company_chg, company_pledge_pct,
                               major_holder_shares, major_holder_chg, major_holder_pledge_pct
                        FROM insider_holdings
                        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY report_date DESC) = 1
                    """).fetchdf()
                    _con.close()
                    _insider_map = {str(r["stock_id"]): r for _, r in _ihdf.iterrows()}
                except Exception:
                    _insider_map = {}

                # 近5/7/10/14日累積漲跌幅：共用 get_rolling_returns()（收盤價比值法，錨最新交易日，
                # 不錨集保週期），跟 index 族群個股表用同一個算法確保兩頁「近N日」一致。
                try:
                    from screener.database import get_rolling_returns
                    _roll_map = get_rolling_returns((5, 7, 10, 14))
                except Exception:
                    _roll_map = {}

                sh_rows = []
                for _, row in sh_df.iterrows():
                    sid = str(row["stock_id"])
                    info = name_map.get(sid, {})
                    close = _price_map.get((sid, str(row["date"])))
                    if close is not None and pd.isna(close):
                        close = None  # daily_prices.close 可能是 NULL→nan，洗成 None 免得 _price_cell int(nan) crash
                    prev_close = _price_map.get((sid, str(row["prev_date"]))) if pd.notna(row["prev_date"]) else None
                    if prev_close is not None and pd.isna(prev_close):
                        prev_close = None
                    price_week_chg = (
                        round((close - prev_close) / prev_close * 100, 2)
                        if close is not None and prev_close is not None and prev_close != 0 else None
                    )
                    share_chg = row["share_chg"] if pd.notna(row["share_chg"]) else None
                    insider = _insider_map.get(sid)
                    roll = _roll_map.get(sid, {})

                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "lv12_15_shares": int(row["lv12_15_shares"]) if pd.notna(row["lv12_15_shares"]) else None,
                        "share_chg":   int(share_chg) if share_chg is not None else None,
                        "week_chg":    None if pd.isna(row["week_chg"]) else float(row["week_chg"]),
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(close) if close is not None else None,
                        "change_pct":  price_week_chg,
                        "chg_5d":      roll.get(5),
                        "chg_7d":      roll.get(7),
                        "chg_10d":     roll.get(10),
                        "chg_14d":     roll.get(14),
                        "company_shares":          int(insider["company_shares"]) if insider is not None and pd.notna(insider["company_shares"]) else None,
                        "company_chg":             int(insider["company_chg"]) if insider is not None and pd.notna(insider["company_chg"]) else None,
                        "company_pledge_pct":      float(insider["company_pledge_pct"]) if insider is not None and pd.notna(insider["company_pledge_pct"]) else None,
                        "major_holder_shares":     int(insider["major_holder_shares"]) if insider is not None and pd.notna(insider["major_holder_shares"]) else None,
                        "major_holder_chg":        int(insider["major_holder_chg"]) if insider is not None and pd.notna(insider["major_holder_chg"]) else None,
                        "major_holder_pledge_pct": float(insider["major_holder_pledge_pct"]) if insider is not None and pd.notna(insider["major_holder_pledge_pct"]) else None,
                        "lv12_shares": int(row["lv12_shares"]) if pd.notna(row["lv12_shares"]) else None,
                        "lv12_pct":    float(row["lv12_pct"]) if pd.notna(row["lv12_pct"]) else None,
                        "lv12_chg":    int(row["lv12_chg"]) if pd.notna(row["lv12_chg"]) else None,
                        "lv15_shares": int(row["lv15_shares"]) if pd.notna(row["lv15_shares"]) else None,
                        "lv15_pct":    float(row["lv15_pct"]) if pd.notna(row["lv15_pct"]) else None,
                        "lv15_chg":    int(row["lv15_chg"]) if pd.notna(row["lv15_chg"]) else None,
                    })
            else:
                sh_rows = []
        except Exception as exc:
            logger.warning("大戶持倉資料載入失敗: %s", exc)
            sh_rows = []
        chips_html_written = generate_chips_html(
            trade_date, meta_chips, stock_chips,
            inst_scan=inst_results, margin_divergence=margin_div, cum_data=cum_data,
            meta_signals=meta_signals, shareholder_data=sh_rows, insider_data=insider_rows,
        )
        if chips_html_written:
            logger.info("HTML generated → docs/chips.html")
        else:
            logger.warning("docs/chips.html 沒有更新（meta_chips/stock_chips 皆為空，可能是資料源當天抓取失敗）")

        try:
            from screener.patterns import scan_and_track
            from export.patterns_generator import generate as generate_patterns_html
            pattern_results = scan_and_track(trade_date.isoformat(), margin_divergence_data=margin_div)
            # Backfill composite_score into inst_results for stocks that appear in patterns
            comp_map = {r["stock_id"]: r.get("composite_score") for r in pattern_results if r.get("composite_score") is not None}
            for row in inst_results:
                if row["stock_id"] in comp_map:
                    row["composite_score"] = comp_map[row["stock_id"]]
            generate_patterns_html(trade_date, pattern_results, "docs/patterns.html")
            logger.info("HTML generated → docs/patterns.html")
        except Exception as exc:
            logger.warning("patterns 掃描/產 HTML 失敗: %s", exc)

        momentum_html_written = False
        if observation_scores:
            try:
                momentum_results = scan_momentum_health(trade_date.isoformat())
                bullish_results = scan_bullish_alignment_new_high(trade_date.isoformat())
                limit_up_results = scan_consecutive_limit_up(trade_date.isoformat())

                permission_data = market_permission(
                    market_regime or {},
                    index_date=market_regime.get("taiex_date") if market_regime else None,
                    price_date=trade_date.isoformat(),
                )
                sector_states = {
                    meta_name: classify_sector_state(data)
                    for meta_name, data in observation_scores.items()
                }
                sector_priority = build_sector_priority(observation_scores, top_n=5)
                decision_table = build_decision_table(
                    momentum_results, bullish_results, permission_data["permission"], sector_states,
                )
                risk_zone = (
                    selloff_risk_zone(momentum_results)
                    if permission_data["permission"] == "defensive" else {}
                )
                streak_cards = build_streak_cards(limit_up_results)

                momentum_html_written = generate_momentum_html(
                    trade_date, permission_data, sector_priority, decision_table,
                    risk_zone, streak_cards,
                    index_date=market_regime.get("taiex_date") if market_regime else None,
                    price_date=trade_date.isoformat(),
                    chips_date=trade_date.isoformat(),
                )
            except Exception as exc:
                logger.warning("逆轟策略頁產生失敗: %s", exc)

        if momentum_html_written:
            logger.info("HTML generated → docs/momentum.html")
        elif observation_scores:
            logger.warning("docs/momentum.html 沒有更新（decision_table 為空，可能是當天無掃描命中或資料源失敗）")

        _push_html(trade_date)

    logger.info("=== Done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TW Sector Tracker")
    parser.add_argument("--update-sectors", action="store_true",
                        help="Re-scrape MoneyDJ sectors (~15 min). Run weekly.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit sectors for testing (use with --update-sectors)")
    parser.add_argument("--backfill-twse", type=int, default=0, metavar="MONTHS",
                        help="TWSE 逐股月別補齊過去 N 個月歷史行情（建議 18，會刪舊 CSV 重抓）")
    parser.add_argument("--backfill-yf", type=int, default=0, metavar="MONTHS",
                        help="Yahoo Finance 逐股補齊過去 N 個月歷史行情（TWSE+TPEx 都支援，不需要 token，"
                             "建議 19，會刪舊 CSV 重抓）")
    parser.add_argument("--workers", type=int, default=3, metavar="N",
                        help="backfill-twse / backfill-yf 並行 workers 數（預設 3，過高可能被限速）")
    parser.add_argument("--backfill-institutional", type=int, default=0, metavar="DAYS",
                        help="TWSE T86 補齊過去 N 個工作日三大法人資料（建議 60）")
    parser.add_argument("--backfill-margin", type=int, default=0, metavar="DAYS",
                        help="TWSE MI_MARGN 補齊過去 N 個工作日融資融券資料（建議 60）")
    parser.add_argument("--backtest", action="store_true",
                        help="跑巨量換手回測，輸出勝率與期望值統計")
    parser.add_argument("--backtest-accumulation", action="store_true",
                        help="跑進貨分回測校準，輸出分數分桶超額報酬 + weakening 邊界案例比較")
    parser.add_argument(
        "--backtest-chips", nargs="?", const="all", default=None,
        choices=["all", *CHIPS_RULES],
        help="逐規則回測籌碼頁；可指定規則，省略值時回測全部（含 _streak_only/_price_only 消融對照變體）",
    )
    parser.add_argument("--realtime", action="store_true",
                        help="使用盤中即時行情（mis.twse.com.tw），適合 9:00~13:30 盤中使用")
    parser.add_argument("--backtest-patterns", type=int, default=0, metavar="DAYS",
                        help="跑過去 N 個交易日形態回測，輸出各形態勝率與平均報酬")
    parser.add_argument("--backtest-patterns-rr", type=int, default=0, metavar="DAYS",
                        help="帶停損+時間出場的形態回測，追蹤 MFE 實際後續漲幅。預設持倉 20 日。")
    parser.add_argument("--mfe-qual", type=float, default=30.0, metavar="PCT",
                        help="MFE 合格線（%%），預設 30.0，回測時顯示多少比例的訊號漲幅達標")
    parser.add_argument("--max-dd", type=float, default=None, metavar="PCT",
                        help="自訂最大回撤停損（%%），例如 20 表示回撤 20%% 才停損，不設則用偵測函數預設 stop")
    parser.add_argument("--start-date", type=str, default=None, metavar="YYYY-MM-DD",
                        help="回測起始日（搭配 --backtest-patterns-rr 使用），會額外輸出每筆逐日明細")
    parser.add_argument("--update-shareholder", action="store_true",
                        help="抓 TDCC 集保持股分散表（最新週），計算大戶持倉比例與週變化")
    parser.add_argument("--backfill-shareholder", type=int, default=0, metavar="WEEKS",
                        help="補齊集保持股分散表過去 N 週資料（每支股票一次請求，約 17 分鐘/週）")
    parser.add_argument("--update-insider-holdings", action="store_true",
                        help="抓公開資訊觀測站內部人持股（公司派/大股東），計算月變化")
    parser.add_argument("--reimport", action="store_true",
                        help="清空 daily_prices 並從所有現有 CSV 重新匯入，用於修復資料庫錯誤")
    parser.add_argument("--full-rebuild", action="store_true",
                        help="一鍵重建歷史行情：刪舊 CSV → 逐股月別重抓（TWSE）+ FinMind（TPEx）→ reimport")
    parser.add_argument("--months", type=int, default=19, metavar="N",
                        help="--full-rebuild 往回抓幾個月（預設 19 = 2025-01-01 起）")
    args = parser.parse_args()

    if args.update_sectors:
        update_sectors(limit=args.limit)
    elif args.backfill_twse:
        backfill_twse(months=args.backfill_twse, workers=args.workers)
    elif args.backfill_yf:
        backfill_yf(months=args.backfill_yf, workers=args.workers)
    elif args.backfill_institutional:
        backfill_inst(days=args.backfill_institutional)
    elif args.backfill_margin:
        backfill_marg(days=args.backfill_margin)
    elif args.backtest:
        df = run_backtest(lambda d, p: scan_volume_turnover(d, db_path=p))
        print_backtest_summary(df)
    elif args.backtest_accumulation:
        from screener.patterns import scan_accumulation_score, print_accumulation_calibration
        scanner, cache = scan_accumulation_score()
        df = run_backtest(scanner)
        print_accumulation_calibration(df, cache)
    elif args.backtest_chips:
        from screener.backtest import CHIPS_RULE_CONFIG, run_chips_rule_backtests
        for rule_name, df in run_chips_rule_backtests(args.backtest_chips).items():
            print(f"\n### 籌碼規則：{rule_name}")
            config = CHIPS_RULE_CONFIG[rule_name]
            print_backtest_summary(
                df,
                skip_no_fill=config["skip_no_fill"],
                success_direction=config["success_direction"],
            )
    elif args.backtest_patterns:
        from screener.patterns import backtest_patterns
        backtest_patterns(days=args.backtest_patterns)
    elif args.backtest_patterns_rr:
        from screener.patterns import backtest_patterns_rr
        backtest_patterns_rr(days=args.backtest_patterns_rr, mfe_qual=args.mfe_qual, max_dd=args.max_dd, start_date=args.start_date)
    elif args.update_shareholder:
        _update_shareholder()
    elif args.backfill_shareholder:
        _backfill_shareholder(weeks=args.backfill_shareholder)
    elif args.update_insider_holdings:
        _update_insider_holdings()
    elif args.reimport:
        from screener.database import reimport_db
        init_db()
        n = reimport_db()
        logger.info("=== reimport 完成：%d 筆 ===", n)
    elif args.full_rebuild:
        _full_rebuild(months=args.months, workers=args.workers)
    else:
        run(realtime=args.realtime)
