import argparse
import logging
import subprocess
import sys
import pandas as pd
from datetime import date
from pathlib import Path

from scrapers.moneydj import scrape_industry_sectors
from scrapers.finmind import fetch_prices_for_stocks
from processors.changes import detect_changes
from processors.performance import calc_sector_performance
from storage.csv_writer import CsvWriter
from export.html_generator import generate as generate_html

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


def _push_html(trade_date: date) -> None:
    try:
        subprocess.run(["git", "add", "docs/index.html"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"update: sector performance {trade_date.isoformat()}"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("Pushed to GitHub Pages.")
        else:
            logger.info("No HTML changes to push.")
    except Exception as exc:
        logger.warning("Git push failed: %s", exc)


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


def run(trade_date: date = None) -> None:
    """每日執行：讀取已存族群 → 抓 TWSE+TPEx 行情 → 計算績效 → 更新網站（約 10 秒）"""
    if trade_date is None:
        trade_date = date.today()

    logger.info("=== TW Sector Tracker — %s ===", trade_date.isoformat())
    writer = CsvWriter(base_dir="data")

    # 1. 讀取已儲存的族群成份股
    sectors_df = writer.read_sector_stocks("industry")
    if sectors_df.empty:
        logger.error("No sector data found. Run with --update-sectors first.")
        return

    yesterday_df = sectors_df.copy()  # 用於異動偵測
    all_records = sectors_df.drop(columns=["date"], errors="ignore").to_dict("records")
    unique_ids = list(sectors_df["stock_id"].astype(str).unique())
    logger.info("Loaded %d stocks across sectors from saved data.", len(unique_ids))

    # 2. 抓 TWSE + TPEx 行情
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

    # 5. 計算族群績效
    perf = []
    if prices_df is not None and not prices_df.empty and not today_df.empty:
        perf = calc_sector_performance(today_df, prices_df)
        writer.write_sector_performance(perf, trade_date)
        logger.info("Sector performance written (%d sectors).", len(perf))

    # 6. 產生 HTML + 推上 GitHub Pages
    if perf:
        generate_html(trade_date, pd.DataFrame(perf),
                      sectors_df=sectors_df,
                      prices_df=prices_df if prices_df is not None else pd.DataFrame())
        logger.info("HTML generated → docs/index.html")
        _push_html(trade_date)

    logger.info("=== Done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TW Sector Tracker")
    parser.add_argument("--update-sectors", action="store_true",
                        help="Re-scrape MoneyDJ sectors (~15 min). Run weekly.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit sectors for testing (use with --update-sectors)")
    args = parser.parse_args()

    if args.update_sectors:
        update_sectors(limit=args.limit)
    else:
        run()
