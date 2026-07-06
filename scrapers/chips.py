"""
籌碼面資料抓取：
- 三大法人：TWSE T86（上市）+ TPEx OpenAPI（上櫃）
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


_TPEX_3INSTI_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

_HEADERS_TPEX = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

# TPEx 官方欄位 key 本身就有不一致的空白/命名，照抄避免打錯字漏抓
_TPEX_FOREIGN_EX_DEALER = "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"
_TPEX_FOREIGN_DEALER = "ForeignDealers-Difference"  # 刻意不併入 dealer_net，對齊 TWSE 的捨棄行為（見 fetch_institutional_tpex docstring）
_TPEX_TRUST = "SecuritiesInvestmentTrustCompanies-Difference"
_TPEX_DEALER_SELF = "Dealers-Difference"
_TPEX_TOTAL = "TotalDifference"


def _roc_date_to_iso(roc_str: str) -> str:
    """民國年日期字串（例如 '1150702'）轉 'YYYY-MM-DD'。"""
    roc_year = int(roc_str[:3])
    return f"{roc_year + 1911}-{roc_str[3:5]}-{roc_str[5:7]}"


def fetch_institutional_tpex() -> pd.DataFrame:
    """
    抓 TPEx 上櫃股三大法人資料（tpex_3insti_daily_trading，只回傳當天，無法查歷史日期）。
    回傳欄位跟 fetch_institutional()（TWSE）一致：
      stock_id, date, foreign_net, trust_net, dealer_net, total_net

    口徑對齊 TWSE T86：foreign_net／dealer_net 都不含外資自營商（ForeignDealers-Difference），
    這欄位單獨存在但目前不寫進任何欄位——跟 TWSE 端 fetch_institutional() 一樣，外資自營商
    （row[7]）也是被捨棄、不併入 foreign_net 或 dealer_net。兩邊欄位定義才是真的一致。
    代價：foreign_net+trust_net+dealer_net 不保證等於 total_net（差額是外資自營商），這點
    TWSE 那邊本來就是如此（用 1325 檔驗證 row4+row7+row10+row11==row18，但 row4+row10+row11
    本身不等於 row18）。實測至今外資自營商恆為 0（近一年抽樣），所以目前這個落差沒有實際影響，
    但口徑保持一致比「兩邊都能各自兜出 0 誤差、但定義不同」更重要，之後才不會出現「上市/上櫃
    dealer_net 同名不同義」的問題。
    """
    resp = requests.get(_TPEX_3INSTI_URL, headers=_HEADERS_TPEX, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError("TPEx 三大法人 API 回傳空資料")

    rows = []
    for row in data:
        date_str = row.get("Date", "")
        if not date_str:
            continue
        foreign_ex_dealer = _parse_num(row.get(_TPEX_FOREIGN_EX_DEALER))
        rows.append({
            "stock_id":    str(row.get("SecuritiesCompanyCode", "")).strip(),
            "date":        _roc_date_to_iso(date_str),
            "foreign_net": foreign_ex_dealer,
            "trust_net":   _parse_num(row.get(_TPEX_TRUST)),
            "dealer_net":  _parse_num(row.get(_TPEX_DEALER_SELF)),  # 不含外資自營商，對齊 TWSE row[11]
            "total_net":   _parse_num(row.get(_TPEX_TOTAL)),
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


_TPEX_MARGIN_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"


def fetch_margin_all_tpex() -> pd.DataFrame:
    """
    TPEx 上櫃股票融資融券餘額（tpex_mainboard_margin_balance，只回傳當天，無法查歷史日期）。
    欄位跟 fetch_margin_all_twse() 一致：stock_id, date, margin_balance, margin_change, short_balance, short_change
    單位跟 TWSE MI_MARGN 一致，都是「張」。
    """
    resp = requests.get(_TPEX_MARGIN_URL, headers=_HEADERS_TPEX, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError("TPEx 融資融券 API 回傳空資料")

    rows = []
    for row in data:
        date_str = row.get("Date", "")
        sid = str(row.get("SecuritiesCompanyCode", "")).strip()
        if not date_str or not sid:
            continue
        margin_bal  = _parse_num(row.get("MarginPurchaseBalance"))
        prev_margin = _parse_num(row.get("MarginPurchaseBalancePreviousDay"))
        short_bal   = _parse_num(row.get("ShortSaleBalance"))
        prev_short  = _parse_num(row.get("ShortSaleBalancePreviousDay"))
        rows.append({
            "stock_id":       sid,
            "date":           _roc_date_to_iso(date_str),
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
