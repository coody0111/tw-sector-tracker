import io
import urllib3
import requests
import pandas as pd
from datetime import date

from scrapers.chips import TWSEBlockedError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.twse.com.tw/zh/trading/historical/stock-day.html",
}


def fetch_daily_prices(trade_date: date) -> pd.DataFrame:
    date_str = trade_date.strftime("%Y%m%d")
    resp = requests.get(
        TWSE_URL,
        params={"response": "json", "date": date_str},
        headers=_HEADERS,
        timeout=30,
        verify=False,
    )
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        # 非 JSON 回應有兩種可能：(1) 瀏覽器 UA 觸發的合法 CSV 回應；
        # (2) TWSE 資安擋頁（WAF block／IP 被限流），內容是 HTML。
        # 擋頁一律是 text/html，合法 CSV 不是，用 content-type 先擋一層。
        ctype = resp.headers.get("Content-Type", "")
        if "html" in ctype.lower():
            raise TWSEBlockedError(
                f"TWSE 疑似封鎖此 IP（content-type={ctype!r}），並非合法 CSV 回應"
            )
        text = resp.content.decode("utf-8-sig")
        try:
            return _parse_csv(text)
        except pd.errors.ParserError as exc:
            # content-type 沒標成 html，但內容根本不是合法 CSV，同樣視為擋頁，
            # 不要讓原始的 pandas 解析錯誤看起來像無關的資料格式 bug。
            raise TWSEBlockedError(
                f"TWSE 回應無法解析為 CSV（疑似擋頁）：{exc}"
            ) from exc
    return _parse_json(data)


def _parse_csv(text: str) -> pd.DataFrame:
    """Parse CSV response: 日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數"""
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return pd.DataFrame(columns=["stock_id", "stock_name", "close", "change", "change_pct", "volume", "open", "high", "low"])
    close = pd.to_numeric(df["收盤價"], errors="coerce")
    change = pd.to_numeric(df["漲跌價差"], errors="coerce").fillna(0)
    prev_close = (close - change).replace(0, float("nan"))
    change_pct = (change / prev_close * 100).round(2).fillna(0)
    volume = (
        pd.to_numeric(df["成交股數"], errors="coerce").fillna(0).astype(int) // 1000
    )

    def _ohlc_col(name: str) -> pd.Series:
        if name not in df.columns:
            return pd.Series(float("nan"), index=df.index)
        return pd.to_numeric(df[name], errors="coerce")

    result = pd.DataFrame({
        "stock_id": df["證券代號"].astype(str).str.strip(),
        "stock_name": df["證券名稱"].astype(str).str.strip(),
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "open": _ohlc_col("開盤價"),
        "high": _ohlc_col("最高價"),
        "low": _ohlc_col("最低價"),
    })
    return result.dropna(subset=["close"]).reset_index(drop=True)


def _parse_json(data: dict) -> pd.DataFrame:
    if data.get("stat") != "OK":
        raise ValueError(f"TWSE API returned stat={data.get('stat')}")

    rows = data["data"]
    num_fields = len(data["fields"])
    df = pd.DataFrame(rows)

    if num_fields == 10:
        # Format (2026+): [id, name, shares, amount, open, high, low, close, change, volume_lots]
        open_ = pd.to_numeric(df.iloc[:, 4].str.replace(",", ""), errors="coerce")
        high = pd.to_numeric(df.iloc[:, 5].str.replace(",", ""), errors="coerce")
        low = pd.to_numeric(df.iloc[:, 6].str.replace(",", ""), errors="coerce")
        close = pd.to_numeric(df.iloc[:, 7].str.replace(",", ""), errors="coerce")
        change = pd.to_numeric(df.iloc[:, 8].str.replace(",", ""), errors="coerce").fillna(0)
        prev_close = close - change
        change_pct = (change / prev_close * 100).round(2)
        volume = (
            pd.to_numeric(df.iloc[:, 9].str.replace(",", ""), errors="coerce")
            .fillna(0).astype(int)
        )
    else:
        # Old format (16 fields): separate sign and price diff columns
        named = pd.DataFrame(rows, columns=data["fields"])
        sign = named["漲跌(+/-)"].str.strip().map({"+": 1, "-": -1}).fillna(0)
        amount = pd.to_numeric(
            named["漲跌價差"].str.replace(",", ""), errors="coerce"
        ).fillna(0)
        change = sign * amount
        open_ = pd.to_numeric(named["開盤價"].str.replace(",", ""), errors="coerce")
        high = pd.to_numeric(named["最高價"].str.replace(",", ""), errors="coerce")
        low = pd.to_numeric(named["最低價"].str.replace(",", ""), errors="coerce")
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
        "open": open_,
        "high": high,
        "low": low,
    })
    return result.dropna(subset=["close"]).reset_index(drop=True)
