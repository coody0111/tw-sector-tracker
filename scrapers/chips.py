"""
籌碼面資料抓取：
- 三大法人：TWSE T86（上市）
- 融資融券：FinMind API（上市+上櫃）
"""
import os
import requests
import pandas as pd
from datetime import date
from dotenv import load_dotenv

load_dotenv()

TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")

_HEADERS_TWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
}


class TWSEBlockedError(RuntimeError):
    """TWSE 回傳資安擋頁（WAF block／IP 被限流），不是合法的『尚未發布』回應。"""


def _check_twse_response(resp) -> None:
    """偵測 TWSE 擋頁：合法回應一律是 200 + JSON，擋頁是 30x 導向 + text/html。"""
    ctype = resp.headers.get("Content-Type", "")
    if resp.status_code != 200 or "json" not in ctype.lower():
        raise TWSEBlockedError(
            f"TWSE 疑似封鎖此 IP（status={resp.status_code}, content-type={ctype!r}），"
            "並非資料尚未發布"
        )


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
        headers=_HEADERS_TWSE,
        timeout=30,
        verify=False,
    )
    _check_twse_response(resp)
    data = resp.json()

    if data.get("stat") != "OK" or not data.get("data"):
        raise ValueError(f"TWSE T86 returned stat={data.get('stat')} for {trade_date}")

    rows = []
    for row in data["data"]:
        if len(row) < 19:  # T86 偶爾回傳欄位不足的列，直接跳過
            continue
        rows.append({
            "stock_id":    str(row[0]).strip(),
            "date":        trade_date.isoformat(),
            "foreign_net": _parse_num(row[4]),   # 外資買賣超
            "trust_net":   _parse_num(row[10]),  # 投信買賣超
            "dealer_net":  _parse_num(row[11]),  # 自營商買賣超
            "total_net":   _parse_num(row[18]),  # 三大法人合計
        })

    return pd.DataFrame(rows)


_TWSE_MARGN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"


def fetch_margin_all_twse(trade_date: date) -> pd.DataFrame:
    """
    TWSE MI_MARGN — 一次取得全部上市股票融資融券資料。
    欄位：stock_id, date, margin_balance, margin_change, short_balance, short_change
    """
    date_str = trade_date.strftime("%Y%m%d")
    resp = requests.get(
        _TWSE_MARGN_URL,
        params={"date": date_str, "selectType": "ALL", "response": "json"},
        headers=_HEADERS_TWSE,
        timeout=20,
        verify=False,
    )
    _check_twse_response(resp)
    data = resp.json()

    if data.get("stat") != "OK":
        raise ValueError(f"MI_MARGN stat={data.get('stat')} for {trade_date}")

    # tables[1] 是個股彙總；tables[0] 是市場統計
    tables = data.get("tables", [])
    stock_table = next((t for t in tables if len(t.get("data", [])) > 10), None)
    if not stock_table:
        raise ValueError(f"MI_MARGN: 找不到個股資料表 for {trade_date}")

    rows = []
    for row in stock_table["data"]:
        if len(row) < 13:
            continue
        sid = str(row[0]).strip()
        if not sid:
            continue
        try:
            margin_bal  = _parse_num(row[6])
            prev_margin = _parse_num(row[5])
            short_bal   = _parse_num(row[12])
            prev_short  = _parse_num(row[11])
        except (IndexError, ValueError):
            continue
        rows.append({
            "stock_id":       sid,
            "date":           trade_date.isoformat(),
            "margin_balance": margin_bal,
            "margin_change":  margin_bal - prev_margin,
            "short_balance":  short_bal,
            "short_change":   short_bal - prev_short,
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
