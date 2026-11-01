"""台指期：期交所 OpenAPI 近月一般盤行情與三大法人未平倉。
OpenAPI 只回最新一個交易日，週變化要靠排程每天存進 data/futures_daily.csv 累積（recommend.weekly_chips）。"""
import requests

QUOTES_URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
INSTITUTIONS_URL = "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
_ITEMS = {"外資及陸資": "foreign_net", "投信": "trust_net", "自營商": "dealer_net"}


def _to_int(val) -> int | None:
    try:
        return int(float(str(val).replace(",", "").strip()))
    except ValueError:
        return None


def parse_snapshot(quotes: list, institutions: list) -> dict | None:
    """近月 TX 一般盤（週選與價差單的月份欄不是純數字）＋同一天三大法人臺股期貨未平倉淨額；缺一項回 None。"""
    rows = [q for q in quotes if q.get("Contract", "").strip() == "TX" and q.get("TradingSession") == "一般"
            and q.get("ContractMonth(Week)", "").strip().isdigit()]
    if not rows:
        return None
    q = min(rows, key=lambda x: x["ContractMonth(Week)"].strip())
    raw = q["Date"].strip()
    nets = {_ITEMS[x["Item"].strip()]: _to_int(x["OpenInterest(Net)"]) for x in institutions
            if x.get("ContractCode", "").strip() == "臺股期貨" and x.get("Date", "").strip() == raw and x.get("Item", "").strip() in _ITEMS}
    if len(nets) != len(_ITEMS):
        return None
    return {"date": f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", "contract": q["ContractMonth(Week)"].strip(), "close": _to_int(q["Last"]),
            "settle": _to_int(q["SettlementPrice"]), "change": _to_int(q["Change"]), "volume": _to_int(q["Volume"]),
            "open_interest": _to_int(q["OpenInterest"]), **nets}


def fetch_futures_snapshot() -> dict | None:
    quotes = requests.get(QUOTES_URL, headers=_HEADERS, timeout=30)
    quotes.raise_for_status()
    institutions = requests.get(INSTITUTIONS_URL, headers=_HEADERS, timeout=30)
    institutions.raise_for_status()
    return parse_snapshot(quotes.json(), institutions.json())
