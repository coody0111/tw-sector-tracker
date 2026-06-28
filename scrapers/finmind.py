import logging
from pathlib import Path
import pandas as pd
from datetime import date

from scrapers.twse import fetch_daily_prices as fetch_twse
from scrapers.tpex import fetch_daily_prices as fetch_tpex

logger = logging.getLogger(__name__)

_NAME_CACHE = Path("data/stock_names.csv")


def fetch_prices_for_stocks(stock_ids: list, trade_date: date) -> pd.DataFrame:
    """Fetch prices from TWSE + TPEx, return only stocks in stock_ids."""
    frames = []

    try:
        twse_df = fetch_twse(trade_date)
        logger.info("  TWSE: %d stocks", len(twse_df))
        frames.append(twse_df)
    except Exception as exc:
        logger.error("TWSE fetch failed: %s", exc)

    try:
        tpex_df = fetch_tpex(trade_date)
        logger.info("  TPEx: %d stocks", len(tpex_df))
        frames.append(tpex_df)
    except Exception as exc:
        logger.error("TPEx fetch failed: %s", exc)

    if not frames:
        raise ValueError(f"Both TWSE and TPEx failed for {trade_date}")

    all_prices = pd.concat(frames, ignore_index=True)
    all_prices = all_prices.drop_duplicates(subset=["stock_id"])

    # 每日更新完整股票名稱快取（涵蓋所有上市/上櫃股票）
    if "stock_name" in all_prices.columns:
        try:
            all_prices[["stock_id", "stock_name"]].dropna().to_csv(_NAME_CACHE, index=False)
        except Exception:
            pass

    if stock_ids:
        all_prices = all_prices[all_prices["stock_id"].isin(stock_ids)]

    return all_prices.reset_index(drop=True)
