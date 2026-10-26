"""
上市除權息／減資／變更面額的官方參考價（事件表），給官方行情回補算漲跌用。

為什麼（2026-10-26，bug-reports 🟡1）：MI_INDEX 在這些日子漲跌給 'X'，回補只能用前收反推，
算出假漲跌（6669 2026-09-02 −66.54%，官方是 −0.19%；2364 2021-10-08 減資恢復 +612%）。
官方另有三張表給「參考價」，漲跌＝收盤 − 參考價：
- exRight/TWT49U   除權除息計算結果表（第 4 欄除權息參考價；日期「115年09月02日」）
- reducation/TWTAUU 減資恢復買賣參考價（第 4 欄恢復買賣參考價；日期「110/10/08」）
- change/TWTB8U    變更面額恢復買賣參考價（同上）
三張都能用日期區間查，半年一查，2020 起約 42 個請求。上櫃有「次日參考價」，不用這張表。

漲跌基準 base（2026-10-26 Debugger 實查）：官方漲停價大多由參考價算，但現金增資除權等事件改用「開盤競價基準」
（6225 2026-08-18 用參考價會算出 +62%，實際一字漲停 +9.91%）。規則：limit_up_price(參考價) 等於官方漲停價就用參考價，
否則用開盤競價基準。

存成 data/corporate_events.csv（stock_id, date, pre_close, ref, limit_up, open_base, base, src）；
之後算還原價（階段 0-3）也能用：還原因子＝ref ÷ pre_close。
"""
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from recommend.ticks import limit_up_price
from scrapers.chips import _HEADERS_TWSE, _check_twse_response

logger = logging.getLogger(__name__)

EVENTS_PATH = Path(__file__).resolve().parent.parent / "data" / "corporate_events.csv"
# (路徑, 名稱, 漲停價欄, 開盤競價基準欄)；三張表第 0 欄日期、1 欄代號、3 欄前收、4 欄參考價
EVENT_SOURCES = (
    ("exRight/TWT49U", "除權息", 7, 9),
    ("reducation/TWTAUU", "減資", 5, 7),
    ("change/TWTB8U", "變更面額", 5, 7),
)
_URL = "https://www.twse.com.tw/rwd/zh/{path}"
COLUMNS = ["stock_id", "date", "pre_close", "ref", "limit_up", "open_base", "base", "src"]


def _roc_date(s: str) -> str | None:
    """'115年09月02日'、'110/10/08' → ISO 日期；認不得回 None。"""
    m = re.match(r"\s*(\d{2,3})\D+(\d{1,2})\D+(\d{1,2})", str(s))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return date(y + 1911, mo, d).isoformat()


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def _base(ref: float, limit_up: float | None, open_base: float | None) -> float:
    """漲跌基準：參考價算出的漲停價跟官方一致就用參考價，否則用開盤競價基準（缺的話退回參考價）。"""
    if limit_up is None or abs(limit_up_price(ref) - limit_up) < 1e-6 or not open_base:
        return ref
    return open_base


def parse_events(data: dict, src: str, i_limit: int, i_open: int) -> list:
    """第 0 欄日期、1 欄代號（尾端有空白）、3 欄前收、4 欄參考價；漲停價、開盤競價基準欄位依表而不同。"""
    if data.get("stat") != "OK":
        return []
    out = []
    for r in data.get("data") or []:
        day, pre, ref = _roc_date(r[0]), _num(r[3]), _num(r[4])
        if not (day and ref and ref > 0):
            continue
        limit = _num(r[i_limit]) if len(r) > i_limit else None
        open_base = _num(r[i_open]) if len(r) > i_open else None
        out.append({"stock_id": str(r[1]).strip(), "date": day, "pre_close": pre, "ref": ref, "limit_up": limit,
                    "open_base": open_base, "base": _base(ref, limit, open_base), "src": src})
    return out


def _half_years(start: date, end: date):
    d = start
    while d <= end:
        stop = min(end, date(d.year, 6, 30) if d.month <= 6 else date(d.year, 12, 31))
        yield d, stop
        d = stop + timedelta(days=1)


def fetch_events(start: date, end: date, sleep_sec: float = 4.0) -> list:
    """start～end 三張表全抓；被擋或網路錯誤直接拋出（呼叫端決定要不要停）。"""
    from scrapers.official_prices import _get_with_retry

    rows = []
    for path, src, i_limit, i_open in EVENT_SOURCES:
        for a, b in _half_years(start, end):
            resp = _get_with_retry(_URL.format(path=path), {"startDate": a.strftime("%Y%m%d"),
                                                           "endDate": b.strftime("%Y%m%d"), "response": "json"},
                                   _HEADERS_TWSE)
            _check_twse_response(resp)
            rows += parse_events(resp.json(), src, i_limit, i_open)
            time.sleep(sleep_sec)
    return rows


def merge_events(rows: list, path: Path = EVENTS_PATH) -> pd.DataFrame:
    """併進事件表；同一股同一天只留一筆（後抓的蓋前面）。回傳合併後的表。"""
    new = pd.DataFrame(rows, columns=COLUMNS)
    if path.exists():
        new = pd.concat([pd.read_csv(path, dtype={"stock_id": str}), new], ignore_index=True)
    out = new.drop_duplicates(["stock_id", "date"], keep="last").sort_values(["date", "stock_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return out.reset_index(drop=True)


def update_events(start: date, end: date, path: Path = EVENTS_PATH) -> pd.DataFrame:
    rows = fetch_events(start, end)
    out = merge_events(rows, path)
    logger.info("上市事件參考價：這次抓到 %d 筆，事件表共 %d 筆（%s）", len(rows), len(out), path)
    return out


def load_event_refs(path: Path = EVENTS_PATH) -> dict:
    """{(ISO 日期, 股號): 漲跌基準 base}；沒有事件表回空 dict（回補退回舊算法）。"""
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"stock_id": str})
    base = df["base"].fillna(df["ref"]) if "base" in df.columns else df["ref"]
    return {(d, s): float(b) for d, s, b in zip(df["date"], df["stock_id"], base)}
