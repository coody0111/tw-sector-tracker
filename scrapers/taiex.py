"""
大盤加權指數（TAIEX）抓取：TWSE 官方 FMTQIK 每日市場成交統計。

FMTQIK endpoint（`www.twse.com.tw/rwd/zh/afterTrading/FMTQIK`）回傳「當月」每個
交易日一列，欄位：
  日期 / 成交股數 / 成交金額 / 成交筆數 / 發行量加權股價指數 / 漲跌點數
其中「發行量加權股價指數」= TAIEX 收盤，「漲跌點數」= 當日漲跌（可負）。
漲跌百分比 API 沒有直接給，用 prev_close = close - change 反推。

封鎖偵測沿用 `scrapers/chips.py::TWSEBlockedError` 的慣例：合法回應一律是 200 + JSON，
擋頁（WAF block／IP 限流）是導向 + text/html，一律當擋頁處理，不吞掉錯誤。
"""
import json
import urllib3
import requests
from datetime import date

from scrapers.chips import TWSEBlockedError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TAIEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/javascript,*/*;q=0.01",
    "Referer": "https://www.twse.com.tw/zh/trading/historical/fmtqik.html",
}


def _to_float(val) -> float | None:
    """把 '47,018.99' / '-274.83' 轉 float；空值/'--'/無法解析回 None。"""
    try:
        s = str(val).replace(",", "").strip()
        if not s or s in ("--", "-"):
            return None
        return float(s)
    except (ValueError, AttributeError, TypeError):
        return None


def _roc_to_date(roc: str) -> date | None:
    """民國日期字串 '115/07/01' → date(2026, 7, 1)。格式不符回 None。"""
    try:
        y, m, d = str(roc).strip().split("/")
        return date(int(y) + 1911, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _parse_taiex_response(raw, content_type: str) -> list[dict]:
    """解析 FMTQIK 回應 → [{date, close, change, change_pct}, ...]（當月所有交易日）。

    純解析函式（不含網路）。content-type 不是 JSON、stat != OK、或結構不符
    （缺必要欄位）一律視為擋頁 → 拋 TWSEBlockedError，不要把擋頁誤當成「當月無資料」。
    """
    if "json" not in (content_type or "").lower():
        raise TWSEBlockedError(
            f"TWSE 疑似封鎖此 IP（content-type={content_type!r}），並非合法 JSON 回應"
        )

    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise TWSEBlockedError(f"TAIEX 回應無法解析為 JSON（疑似擋頁）：{exc}") from exc

    if data.get("stat") != "OK":
        raise TWSEBlockedError(f"TWSE FMTQIK 回傳 stat={data.get('stat')!r}（非 OK，疑似擋頁）")

    fields = data.get("fields") or []
    rows = data.get("data") or []
    try:
        i_date = fields.index("日期")
        i_close = fields.index("發行量加權股價指數")
        i_change = fields.index("漲跌點數")
    except ValueError as exc:
        raise TWSEBlockedError(
            f"TWSE FMTQIK 回應缺少預期欄位（疑似擋頁或格式變更）：fields={fields}"
        ) from exc

    out = []
    for r in rows:
        d = _roc_to_date(r[i_date])
        close = _to_float(r[i_close])
        change = _to_float(r[i_change])
        if d is None or close is None:
            continue
        # prev_close = close - change；change 為 None 時無法算百分比
        if change is None:
            change_pct = None
        else:
            prev_close = close - change
            change_pct = round(change / prev_close * 100, 2) if prev_close else None
        out.append({
            "date": d,
            "close": close,
            "change": change,
            "change_pct": change_pct,
        })
    return out


def fetch_taiex_index(trade_date: date) -> dict:
    """抓 trade_date 當天的大盤加權指數，回傳 {date, close, change, change_pct}。

    FMTQIK 一次回傳整個月，這裡取「日期 <= trade_date 的最新一筆」——當天資料
    尚未發布（盤中或收盤資料延遲）時，自動退到當月已發布的最近一個交易日，
    呼叫端不必自己處理『今天還沒公布』的情況。當月完全沒有 <= trade_date 的資料
    時（例如月初第一個交易日資料還沒出）拋 ValueError。
    """
    date_str = trade_date.strftime("%Y%m%d")
    resp = requests.get(
        TAIEX_URL,
        params={"response": "json", "date": date_str},
        headers=_HEADERS,
        timeout=30,
        verify=False,
    )
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    rows = _parse_taiex_response(resp.text, ctype)

    candidates = [r for r in rows if r["date"] <= trade_date]
    if not candidates:
        raise ValueError(f"FMTQIK 當月無 <= {trade_date.isoformat()} 的 TAIEX 資料")
    return max(candidates, key=lambda r: r["date"])
