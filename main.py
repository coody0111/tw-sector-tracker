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
    """回前一個交易日（跳過週末，不處理國定假日）。"""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
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
        subprocess.run(["git", "add", "docs/index.html", "docs/chips.html"], check=True)
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


def backfill_twse(months: int = 6) -> None:
    """TWSE 逐日全市場補齊 — 不受 FinMind quota 限制（覆蓋 TWSE 上市股）"""
    if not UNIVERSE_PATH.exists():
        logger.error("找不到 stock_universe.csv，請先確認資料目錄。")
        return
    universe_df = pd.read_csv(UNIVERSE_PATH, encoding="utf-8-sig", dtype={"stock_id": str})
    stock_ids = universe_df["stock_id"].tolist()
    logger.info("=== TWSE 月別補齊（往前 %d 個月）===", months)
    n = backfill_twse_monthly(stock_ids, months=months)
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

    # 3. 寫入行情
    if prices_df is not None and not prices_df.empty:
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
                for row in inst_results:
                    info = name_map.get(row["stock_id"], {})
                    row["stock_name"] = info.get("stock_name", "")
                    row["meta_sector"] = info.get("meta_sector", "")
            logger.info("法人篩選：%d 檔有籌碼資料", len(inst_results))
        except Exception as exc:
            logger.warning("法人篩選失敗: %s", exc)
            inst_results = []
        generate_chips_html(trade_date, meta_chips, stock_chips, inst_scan=inst_results, margin_divergence=margin_div, cum_data=cum_data, meta_signals=meta_signals)
        logger.info("HTML generated → docs/chips.html")
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
                        help="TWSE 逐日補齊過去 N 個月歷史行情（無 FinMind quota，建議 6）")
    parser.add_argument("--backfill-institutional", type=int, default=0, metavar="DAYS",
                        help="TWSE T86 補齊過去 N 個工作日三大法人資料（建議 60）")
    parser.add_argument("--backfill-margin", type=int, default=0, metavar="DAYS",
                        help="TWSE MI_MARGN 補齊過去 N 個工作日融資融券資料（建議 60）")
    parser.add_argument("--backtest", action="store_true",
                        help="跑巨量換手回測，輸出勝率與期望值統計")
    parser.add_argument("--realtime", action="store_true",
                        help="使用盤中即時行情（mis.twse.com.tw），適合 9:00~13:30 盤中使用")
    args = parser.parse_args()

    if args.update_sectors:
        update_sectors(limit=args.limit)
    elif args.backfill:
        backfill(days=args.backfill)
    elif args.backfill_twse:
        backfill_twse(months=args.backfill_twse)
    elif args.backfill_institutional:
        backfill_inst(days=args.backfill_institutional)
    elif args.backfill_margin:
        backfill_marg(days=args.backfill_margin)
    elif args.backtest:
        df = run_backtest()
        print_backtest_summary(df)
    else:
        run(realtime=args.realtime)
