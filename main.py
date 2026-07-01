import argparse
import logging
import subprocess
import sys
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from scrapers.moneydj import scrape_industry_sectors
from scrapers.finmind import fetch_prices_for_stocks
from scrapers.realtime import fetch_realtime_prices
from scrapers.chips import fetch_institutional, fetch_margin_all_twse
from scrapers.backfill import backfill_prices, backfill_twse_monthly, backfill_institutional, backfill_margin
from processors.changes import detect_changes
from processors.performance import calc_sector_performance, calc_meta_performance, calc_universe_performance, calc_cumulative_meta, calc_meta_signals, calc_meta_chips_signals, calc_stock_sparklines, get_stock_chips_ranking, get_margin_divergence
from storage.csv_writer import CsvWriter
from export.html_generator import generate as generate_html
from export.chips_generator import generate as generate_chips_html
from screener.database import init_db, import_csv_prices, import_sector_stocks, get_chips_today
from screener.institutional import scan_institutional
from screener.signals import scan_volume_turnover
from screener.backtest import run_backtest, print_summary as print_backtest_summary

UNIVERSE_PATH = Path("data/stock_universe.csv")


def _prev_trading_day(d: date) -> date:
    """回前一個交易日（跳過週末與國定假日）。"""
    from config import is_trading_day
    d -= timedelta(days=1)
    while not is_trading_day(d.isoformat()):
        d -= timedelta(days=1)
    return d

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
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
            inst_df = fetch_institutional(inst_date)
        except ValueError:
            inst_date = _prev_trading_day(trade_date)
            logger.info("三大法人今日尚未發布，改抓前一交易日 %s", inst_date)
            inst_df = fetch_institutional(inst_date)
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
        marg_date = trade_date
        try:
            margin_df = fetch_margin_all_twse(marg_date)
        except ValueError:
            marg_date = _prev_trading_day(trade_date)
            logger.info("融資融券今日尚未發布，改抓前一交易日 %s", marg_date)
            margin_df = fetch_margin_all_twse(marg_date)
        if not margin_df.empty:
            import duckdb
            con = duckdb.connect("data/screener.db")
            con.execute("DELETE FROM margin WHERE date = ?", [marg_date.isoformat()])
            con.execute("INSERT INTO margin SELECT * FROM margin_df")
            con.close()
            logger.info("融資融券寫入 %d 筆（%s）", len(margin_df), marg_date)
    except Exception as exc:
        logger.warning("融資融券寫入失敗: %s", exc)


def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        subprocess.run(["git", "add"] + files_to_add, check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"update: sector performance {trade_date.isoformat()}"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("Pushed to GitHub Pages.")
        else:
            logger.info("No HTML changes to push.")
    except Exception as exc:
        logger.warning("Git push failed: %s", exc)


def backfill(days: int = 180) -> None:
    """歷史行情補齊 — 用 FinMind 逐股抓，約 15 分鐘（每日 600 次上限）"""
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv，請先確認資料目錄。")
        return
    from scrapers.chips import FINMIND_TOKEN
    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    logger.info("=== 歷史行情補齊（FinMind，往前 %d 日曆天）===", days)
    n = backfill_prices(stock_ids, token=FINMIND_TOKEN, days=days)
    if n > 0:
        init_db()
        imported = import_csv_prices()
        logger.info("DuckDB 更新：共 %d 筆", imported)
    logger.info("=== 補齊完成，共寫入 %d 日 ===", n)


def backfill_twse(months: int = 6, workers: int = 3) -> None:
    """TWSE+TPEx 逐日全市場補齊（快速版，STOCK_DAY_ALL 並行）"""
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv，請先確認資料目錄。")
        return
    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    logger.info("=== TWSE+TPEx 補齊（往前 %d 個月，workers=%d）===", months, workers)
    n = backfill_twse_monthly(stock_ids, months=months, workers=workers)
    if n > 0:
        init_db()
        imported = import_csv_prices()
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


def _backfill_shareholder(weeks: int = 4) -> None:
    """補齊過去 N 週的集保持股分散表。"""
    from scrapers.shareholder import fetch_shareholder_weekly, save_to_db as sh_save, get_available_dates
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    available = get_available_dates()
    target_dates = available[:weeks]
    logger.info("=== 集保補齊 %d 週：%s ===", len(target_dates), target_dates)
    for d_str in target_dates:
        logger.info("  抓 %s ...", d_str)
        rows = fetch_shareholder_weekly(stock_ids, date_str=d_str)
        n = sh_save(rows)
        logger.info("  %s 寫入 %d 筆", d_str, n)
    logger.info("=== 集保補齊完成 ===")


def _update_broker() -> None:
    """抓今日各股券商分點買賣超（需先設定 _TWSE_BROKER_URL）。"""
    from scrapers.broker_branch import fetch_broker_batch, save_to_db as bb_save
    init_db()
    stock_ids = pd.read_csv(UNIVERSE_PATH, dtype=str)["stock_id"].tolist()
    trade_date = date.today()
    logger.info("=== 分點買賣超更新 %s（%d 支股票）===", trade_date, len(stock_ids))
    broker_map = fetch_broker_batch(stock_ids, trade_date)
    n = bb_save(trade_date, broker_map)
    logger.info("=== 分點更新完成，寫入 %d 筆 ===", n)


def _fix_stale_data(months: int = 18, workers: int = 3) -> None:
    """
    一鍵修復假資料：
    Step 1  用 backfill_twse_monthly (TWSE+TPEx 平行) 重抓所有股票的 CSV
    Step 2  reimport_db：清空 DuckDB 後從乾淨 CSV 重建（自動排除假資料列）
    """
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv")
        return

    stock_ids = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})["stock_id"].tolist()
    logger.info("=== Step 1：重抓 TWSE+TPEx 所有 CSV（%d 月，workers=%d）===", months, workers)
    n = backfill_twse_monthly(stock_ids, months=months, workers=workers)
    logger.info("Step 1 完成：更新 %d 個交易日 CSV", n)

    logger.info("=== Step 2：清空 DuckDB 並重建（過濾假資料）===")
    from screener.database import reimport_db
    total = reimport_db()
    logger.info("=== fix-stale 完成：DuckDB 共 %d 筆 ===", total)


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
    logger.info("Loaded %d stocks across sectors from saved data.", len(unique_ids))

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
        logger.info("Fetching prices (TWSE + TPEx)...")
        try:
            prices_df = fetch_prices_for_stocks(unique_ids, trade_date)
            prices_df["stock_id"] = prices_df["stock_id"].astype(str)
            logger.info("  TWSE+TPEx total: %d stocks", len(prices_df))
        except Exception as exc:
            logger.error("Price fetch failed: %s. Continuing without prices.", exc)
            prices_df = None

    # 3. 寫入行情（盤前/非交易日不寫入重複資料）
    prices_are_new = True
    if prices_df is not None and not prices_df.empty:
        prev_day = _prev_trading_day(trade_date)
        prev_csv = Path(f"data/daily_prices/{prev_day.isoformat()}.csv")
        if prev_csv.exists():
            try:
                prev_df = pd.read_csv(prev_csv, dtype={"stock_id": str})
                probe_id = "2330" if "2330" in prices_df["stock_id"].values else prices_df.iloc[0]["stock_id"]
                new_close = prices_df[prices_df["stock_id"] == probe_id]["close"].values
                old_close = prev_df[prev_df["stock_id"] == probe_id]["close"].values if "close" in prev_df.columns else []
                if len(new_close) and len(old_close) and float(new_close[0]) == float(old_close[0]):
                    logger.info("今日行情（%s）與前一交易日（%s）相同，市場尚未更新，切換基準日期", trade_date, prev_day)
                    prices_are_new = False
                    trade_date = prev_day
            except Exception:
                pass

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

        cum_data = calc_cumulative_meta(universe_df) if universe_df is not None else []
        meta_signals = calc_meta_signals(universe_df) if universe_df is not None else {}
        meta_chips = calc_meta_chips_signals(universe_df) if universe_df is not None else {}
        stock_sparklines = calc_stock_sparklines(universe_df) if universe_df is not None else {}
        stock_chips = get_stock_chips_ranking(universe_df) if universe_df is not None else {}
        margin_div = get_margin_divergence(universe_df) if universe_df is not None else {}

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
                      vol_turnover=vol_signals)
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
        try:
            from screener.database import get_shareholder_top
            import duckdb as _ddb
            sh_df = get_shareholder_top()
            if not sh_df.empty:
                universe = pd.read_csv(UNIVERSE_PATH, dtype=str, usecols=["stock_id", "stock_name", "meta_sector"])
                name_map = universe.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
                # 取最近一個交易日的股價
                try:
                    _con = _ddb.connect("data/screener.db", read_only=True)
                    _pdate = _con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
                    _pdf = _con.execute(
                        "SELECT stock_id, close, change_pct FROM daily_prices WHERE date = ?", [_pdate]
                    ).fetchdf() if _pdate else pd.DataFrame()
                    _con.close()
                    sh_price_map = _pdf.set_index("stock_id")[["close", "change_pct"]].to_dict("index") if not _pdf.empty else {}
                except Exception:
                    sh_price_map = {}
                sh_rows = []
                for _, row in sh_df.iterrows():
                    sid = str(row["stock_id"])
                    info = name_map.get(sid, {})
                    px = sh_price_map.get(sid, {})
                    sh_rows.append({
                        "stock_id":    sid,
                        "stock_name":  info.get("stock_name", ""),
                        "meta_sector": info.get("meta_sector", ""),
                        "lv12_15_pct": float(row["lv12_15_pct"]) if row["lv12_15_pct"] is not None else None,
                        "week_chg":    float(row["week_chg"]) if row["week_chg"] is not None else None,
                        "streak":      int(row["streak"]) if row["streak"] is not None else 0,
                        "date":        str(row["date"]),
                        "close":       float(px["close"]) if px.get("close") is not None else None,
                        "change_pct":  float(px["change_pct"]) if px.get("change_pct") is not None else None,
                    })
            else:
                sh_rows = []
        except Exception as exc:
            logger.warning("大戶持倉資料載入失敗: %s", exc)
            sh_rows = []
        generate_chips_html(trade_date, meta_chips, stock_chips, inst_scan=inst_results, margin_divergence=margin_div, cum_data=cum_data, meta_signals=meta_signals, shareholder_data=sh_rows)
        logger.info("HTML generated → docs/chips.html")

        try:
            from screener.patterns import scan_and_track
            from export.patterns_generator import generate as generate_patterns_html
            pattern_results = scan_and_track(trade_date.isoformat())
            # Backfill composite_score into inst_results for stocks that appear in patterns
            comp_map = {r["stock_id"]: r.get("composite_score") for r in pattern_results if r.get("composite_score") is not None}
            for row in inst_results:
                if row["stock_id"] in comp_map:
                    row["composite_score"] = comp_map[row["stock_id"]]
            generate_patterns_html(trade_date, pattern_results, "docs/patterns.html")
            logger.info("HTML generated → docs/patterns.html")
        except Exception as exc:
            logger.warning("patterns 掃描/產 HTML 失敗: %s", exc)

        _push_html(trade_date)

    logger.info("=== Done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TW Sector Tracker")
    parser.add_argument("--update-sectors", action="store_true",
                        help="Re-scrape MoneyDJ sectors (~15 min). Run weekly.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit sectors for testing (use with --update-sectors)")
    parser.add_argument("--backfill", type=int, default=0, metavar="DAYS",
                        help="FinMind 補齊過去 N 日曆天歷史行情（每日 600 次上限）")
    parser.add_argument("--backfill-twse", type=int, default=0, metavar="MONTHS",
                        help="TWSE+TPEx 逐日全市場補齊過去 N 個月歷史行情（建議 18 覆蓋 2025 全年）")
    parser.add_argument("--workers", type=int, default=3, metavar="N",
                        help="backfill-twse 並行 workers 數（預設 3，建議 3-5，過高可能被 TWSE 限速）")
    parser.add_argument("--backfill-institutional", type=int, default=0, metavar="DAYS",
                        help="TWSE T86 補齊過去 N 個工作日三大法人資料（建議 60）")
    parser.add_argument("--backfill-margin", type=int, default=0, metavar="DAYS",
                        help="TWSE MI_MARGN 補齊過去 N 個工作日融資融券資料（建議 60）")
    parser.add_argument("--backtest", action="store_true",
                        help="跑巨量換手回測，輸出勝率與期望值統計")
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
    parser.add_argument("--update-broker", action="store_true",
                        help="抓今日各股券商分點買賣超（需先設定 broker_branch.py 的 _TWSE_BROKER_URL）")
    parser.add_argument("--backfill-yf", type=int, default=0, metavar="MONTHS",
                        help="用 Yahoo Finance 補齊過去 N 個月歷史行情（無需 token，含 OHLCV，建議 18~24）")
    parser.add_argument("--reimport", action="store_true",
                        help="清空 daily_prices 並從所有 CSV 重新匯入（自動過濾假資料），用於修復資料庫錯誤")
    parser.add_argument("--fix-stale", action="store_true",
                        help="一鍵修復假資料：重抓 TWSE+TPEx 所有 CSV（平行），再清空 DuckDB 重建（自動過濾假資料）")
    args = parser.parse_args()

    if args.update_sectors:
        update_sectors(limit=args.limit)
    elif args.backfill:
        backfill(days=args.backfill)
    elif args.backfill_twse:
        backfill_twse(months=args.backfill_twse, workers=args.workers)
    elif args.backfill_institutional:
        backfill_inst(days=args.backfill_institutional)
    elif args.backfill_margin:
        backfill_marg(days=args.backfill_margin)
    elif args.backtest:
        df = run_backtest()
        print_backtest_summary(df)
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
    elif args.update_broker:
        _update_broker()
    elif args.backfill_yf:
        from scrapers.backfill import backfill_yfinance
        init_db()
        n = backfill_yfinance(months=args.backfill_yf)
        logger.info("=== backfill-yf 完成：%d 筆 ===", n)
    elif args.reimport:
        from screener.database import reimport_db
        init_db()
        n = reimport_db()
        logger.info("=== reimport 完成：%d 筆 ===", n)
    elif args.fix_stale:
        _fix_stale_data(workers=args.workers)
    else:
        run(realtime=args.realtime)
