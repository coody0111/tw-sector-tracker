import requests
import pandas as pd
from datetime import date

TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"


def fetch_daily_prices(trade_date: date) -> pd.DataFrame:
    resp = requests.get(TPEX_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError(f"TPEx returned empty data")

    df = pd.DataFrame(data)

    # TPEx API 只回傳當日資料，直接使用（不做日期過濾）
    if df.empty:
        raise ValueError("TPEx: empty DataFrame")

    close = pd.to_numeric(df["Close"].str.replace(",", ""), errors="coerce")
    change = pd.to_numeric(df["Change"].str.replace(",", ""), errors="coerce").fillna(0)
    prev_close = close - change
    change_pct = (change / prev_close * 100).round(2)
    volume = (
        pd.to_numeric(df["TradingShares"].str.replace(",", ""), errors="coerce")
        .fillna(0).astype(int) // 1000
    )

    result = pd.DataFrame({
        "stock_id": df["SecuritiesCompanyCode"].str.strip(),
        "stock_name": df["CompanyName"].str.strip(),
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
    })

    return result.dropna(subset=["close"]).reset_index(drop=True)
