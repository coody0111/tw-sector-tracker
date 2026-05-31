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

    df = pd.DataFrame(data["data"], columns=data["fields"])

    sign = df["漲跌(+/-)"].str.strip().map({"+": 1, "-": -1}).fillna(0)
    amount = pd.to_numeric(
        df["漲跌價差"].str.replace(",", ""), errors="coerce"
    ).fillna(0)
    change = sign * amount

    close = pd.to_numeric(df["收盤價"].str.replace(",", ""), errors="coerce")
    prev_close = close - change
    change_pct = (change / prev_close * 100).round(2)

    volume = (
        pd.to_numeric(df["成交股數"].str.replace(",", ""), errors="coerce")
        .fillna(0)
        .astype(int)
        // 1000
    )

    result = pd.DataFrame({
        "stock_id": df["證券代號"].str.strip(),
        "stock_name": df["證券名稱"].str.strip(),
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
    })

    return result.dropna(subset=["close"]).reset_index(drop=True)
