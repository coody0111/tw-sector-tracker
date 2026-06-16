"""
籌碼面資料抓取：
- 三大法人：TWSE T86（上市）
- 融資融券：FinMind API（上市+上櫃）
"""
import requests
import pandas as pd
from datetime import date

TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiY29keWxpdTAxMTEiLCJlbWFpbCI6ImxlYXJuY29keTFAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.neT8oLd-W13Mfp3m8Y8XRnihhF_YO8aQ4HCzm11P7fg"


def _parse_num(val: str) -> int:
    """把 '1,234,567' 或 '-1,234,567' 轉成整數。"""
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0


def fetch_institutional(trade_date: date) -> pd.DataFrame:
    """
    抓 TWSE 三大法人資料，回傳 DataFrame。
    欄位：stock_id, date, foreign_net, trust_net, dealer_net, total_net
    """
    date_str = trade_date.strftime("%Y%m%d")
    resp = requests.get(
        TWSE_T86_URL,
        params={"response": "json", "date": date_str, "selectType": "ALLBUT0999"},
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("stat") != "OK" or not data.get("data"):
        raise ValueError(f"TWSE T86 returned stat={data.get('stat')} for {trade_date}")

    rows = []
    for row in data["data"]:
        rows.append({
            "stock_id":    str(row[0]).strip(),
            "date":        trade_date.isoformat(),
            "foreign_net": _parse_num(row[4]),   # 外資買賣超
            "trust_net":   _parse_num(row[10]),  # 投信買賣超
            "dealer_net":  _parse_num(row[11]),  # 自營商買賣超
            "total_net":   _parse_num(row[18]),  # 三大法人合計
        })

    return pd.DataFrame(rows)


def fetch_margin(stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
    """
    抓單支股票的融資融券資料（FinMind）。
    欄位：stock_id, date, margin_balance, margin_change, short_balance, short_change
    """
    resp = requests.get(
        FINMIND_URL,
        params={
            "dataset":    "TaiwanStockMarginPurchaseShortSale",
            "data_id":    stock_id,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date":   end_date.strftime("%Y-%m-%d"),
            "token":      FINMIND_TOKEN,
        },
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200 or not data.get("data"):
        return pd.DataFrame()

    rows = []
    for row in data["data"]:
        rows.append({
            "stock_id":      stock_id,
            "date":          row["date"],
            "margin_balance": int(row["MarginPurchaseTodayBalance"]),
            "margin_change":  int(row["MarginPurchaseTodayBalance"]) - int(row["MarginPurchaseYesterdayBalance"]),
            "short_balance":  int(row["ShortSaleTodayBalance"]),
            "short_change":   int(row["ShortSaleTodayBalance"]) - int(row["ShortSaleYesterdayBalance"]),
        })

    return pd.DataFrame(rows)


def fetch_margin_all_today(trade_date: date, stock_ids: list) -> pd.DataFrame:
    """
    批量抓所有股票今日融資融券（逐支查詢，適合每日增量更新）。
    """
    frames = []
    for sid in stock_ids:
        try:
            df = fetch_margin(sid, trade_date, trade_date)
            if not df.empty:
                frames.append(df)
        except Exception:
            continue

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
