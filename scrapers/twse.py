import requests
import pandas as pd
from datetime import date

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"


def fetch_daily_prices(trade_date: date) -> pd.DataFrame:
    date_str = trade_date.strftime("%Y%m%d")
    resp = requests.get(
        TWSE_URL,
        params={"response": "json", "date": date_str},
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("stat") != "OK":
        raise ValueError(f"TWSE API returned stat={data.get('stat')}")

    rows = data["data"]
    num_fields = len(data["fields"])

    df = pd.DataFrame(rows)

    if num_fields == 10:
        # New format (2026+): [id, name, shares, amount, open, high, low, close, change, volume_lots]
        close = pd.to_numeric(df.iloc[:, 7].str.replace(",", ""), errors="coerce")
        change = pd.to_numeric(df.iloc[:, 8].str.replace(",", ""), errors="coerce").fillna(0)
        prev_close = close - change
        change_pct = (change / prev_close * 100).round(2)
        volume = (
            pd.to_numeric(df.iloc[:, 9].str.replace(",", ""), errors="coerce")
            .fillna(0).astype(int)
        )
    else:
        # Old format (16 fields): separate sign "+" / "-" and price diff columns
        named = pd.DataFrame(rows, columns=data["fields"])
        sign = named["漲跌(+/-)"].str.strip().map({"+": 1, "-": -1}).fillna(0)
        amount = pd.to_numeric(
            named["漲跌價差"].str.replace(",", ""), errors="coerce"
        ).fillna(0)
        change = sign * amount
        close = pd.to_numeric(named["收盤價"].str.replace(",", ""), errors="coerce")
        prev_close = close - change
        change_pct = (change / prev_close * 100).round(2)
        volume = (
            pd.to_numeric(named["成交股數"].str.replace(",", ""), errors="coerce")
            .fillna(0).astype(int) // 1000
        )

    result = pd.DataFrame({
        "stock_id": df.iloc[:, 0].str.strip(),
        "stock_name": df.iloc[:, 1].str.strip(),
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
    })

    return result.dropna(subset=["close"]).reset_index(drop=True)
