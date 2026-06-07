import yfinance as yf
import pandas as pd
from datetime import date, timedelta
from typing import List


def _extract_row(raw: pd.DataFrame, ticker: str, sid: str, tickers: list) -> dict | None:
    try:
        if len(tickers) == 1:
            close = float(raw["Close"].iloc[0].item())
            prev_close = float(raw["Open"].iloc[0].item())
            volume = int(raw["Volume"].iloc[0].item())
        else:
            close = float(raw["Close"][ticker].iloc[0])
            prev_close = float(raw["Open"][ticker].iloc[0])
            volume = int(raw["Volume"][ticker].iloc[0])

        if pd.isna(close):
            return None

        change = round(close - prev_close, 2)
        change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
        return {
            "stock_id": sid,
            "stock_name": sid,
            "close": close,
            "change": change,
            "change_pct": change_pct,
            "volume": volume // 1000,
        }
    except Exception:
        return None


def fetch_prices_for_stocks(stock_ids: List[str], trade_date: date) -> pd.DataFrame:
    if not stock_ids:
        return pd.DataFrame()

    start = trade_date.strftime("%Y-%m-%d")
    end = (trade_date + timedelta(days=1)).strftime("%Y-%m-%d")

    # Step 1: 全部先試 .TW
    tw_tickers = [f"{sid}.TW" for sid in stock_ids]
    raw_tw = yf.download(tw_tickers, start=start, end=end, progress=False, auto_adjust=True)

    rows = {}
    failed_ids = []

    if not raw_tw.empty:
        for sid in stock_ids:
            row = _extract_row(raw_tw, f"{sid}.TW", sid, tw_tickers)
            if row:
                rows[sid] = row
            else:
                failed_ids.append(sid)
    else:
        failed_ids = list(stock_ids)

    # Step 2: .TW 失敗的改試 .TWO（上櫃）
    if failed_ids:
        two_tickers = [f"{sid}.TWO" for sid in failed_ids]
        raw_two = yf.download(two_tickers, start=start, end=end, progress=False, auto_adjust=True)

        if not raw_two.empty:
            for sid in failed_ids:
                row = _extract_row(raw_two, f"{sid}.TWO", sid, two_tickers)
                if row:
                    rows[sid] = row

    if not rows:
        raise ValueError(f"No data returned for {trade_date} (non-trading day?)")

    return pd.DataFrame(list(rows.values())).reset_index(drop=True)
