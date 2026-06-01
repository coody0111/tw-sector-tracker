import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from scrapers.moneydj import scrape_industry_sectors, scrape_concept_sectors
from scrapers.twse import fetch_daily_prices
from processors.changes import detect_changes
from processors.performance import calc_sector_performance
from storage.csv_writer import CsvWriter

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


def run(trade_date: date = None, limit: int = None) -> None:
    if trade_date is None:
        trade_date = date.today()

    limit_info = f" (limit={limit})" if limit else ""
    logger.info("=== TW Sector Tracker — %s%s ===", trade_date.isoformat(), limit_info)
    writer = CsvWriter(base_dir="data")

    # 1. Read yesterday's sector data for change detection
    yesterday_industry = writer.read_sector_stocks("industry")
    yesterday_concept = writer.read_sector_stocks("concept")

    # 2. Scrape MoneyDJ
    logger.info("Scraping MoneyDJ industry sectors...")
    industry_stocks = scrape_industry_sectors(limit=limit)
    logger.info("  -> %d records", len(industry_stocks))

    logger.info("Scraping MoneyDJ concept sectors...")
    concept_stocks = scrape_concept_sectors(limit=limit)
    logger.info("  -> %d records", len(concept_stocks))

    all_records = [
        {"sector_type": s.sector_type, "sector_name": s.sector_name,
         "sector_code": s.sector_code, "stock_id": s.stock_id, "stock_name": s.stock_name}
        for s in industry_stocks + concept_stocks
    ]

    # 3. Fetch TWSE prices
    logger.info("Fetching TWSE daily prices for %s...", trade_date.isoformat())
    try:
        prices_df = fetch_daily_prices(trade_date)
        logger.info("  -> %d stocks", len(prices_df))
    except Exception as exc:
        logger.error("TWSE fetch failed: %s. Continuing without prices.", exc)
        prices_df = None

    # 4. Write sector stocks
    writer.write_sector_stocks(all_records, trade_date)
    logger.info("Sector stocks written.")

    # 5. Write daily prices
    if prices_df is not None:
        writer.write_daily_prices(prices_df, trade_date)
        logger.info("Daily prices written.")

    # 6. Detect changes
    import pandas as pd
    today_df = pd.DataFrame(all_records)
    if not today_df.empty:
        today_df.insert(0, "date", trade_date.isoformat())

    changes = []
    if not yesterday_industry.empty:
        changes += detect_changes(today_df, yesterday_industry, "industry", trade_date.isoformat())
    if not yesterday_concept.empty:
        changes += detect_changes(today_df, yesterday_concept, "concept", trade_date.isoformat())

    if changes:
        writer.append_changes(changes)
        logger.info("%d composition changes detected and logged.", len(changes))
    else:
        logger.info("No composition changes detected.")

    # 7. Calculate and write performance
    if prices_df is not None and not today_df.empty:
        perf = calc_sector_performance(today_df, prices_df)
        writer.write_sector_performance(perf, trade_date)
        logger.info("Sector performance written (%d sectors).", len(perf))

    logger.info("=== Done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TW Sector Tracker")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of sectors per type (for testing)")
    args = parser.parse_args()
    run(limit=args.limit)
