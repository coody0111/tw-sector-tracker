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
from scrapers.chips import _HEADERS_TPEX, _HEADERS_TWSE, TPExBlockedError, _check_twse_response

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


# 上櫃除權除息計算結果表（2026-10-27 加，給還原價用）：欄位同上市 TWT49U 的前 5 欄；
# 第 9 欄漲停價、第 11 欄開始交易基準價（漲停用）。日期「110/07/01」，半年一查（實測 2025 上半年 507 筆）。
TPEX_EX_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
TPEX_SRC, TPEX_I_LIMIT, TPEX_I_OPEN = "上櫃除權息", 9, 11


def parse_tpex_events(data: dict) -> list:
    if str(data.get("stat", "")).lower() != "ok" or not data.get("tables"):
        return []
    return parse_events({"stat": "OK", "data": data["tables"][0].get("data") or []}, TPEX_SRC, TPEX_I_LIMIT, TPEX_I_OPEN)


def _fetch_tpex_events(a: date, b: date) -> list:
    from scrapers.official_prices import _get_with_retry

    resp = _get_with_retry(TPEX_EX_URL, {"startDate": a.strftime("%Y/%m/%d"), "endDate": b.strftime("%Y/%m/%d"),
                                         "response": "json"}, _HEADERS_TPEX)
    if resp.status_code != 200 or "json" not in resp.headers.get("Content-Type", "").lower():
        raise TPExBlockedError(f"TPEx 除權息表疑似封鎖（status={resp.status_code}）")
    return parse_tpex_events(resp.json())


def fetch_events(start: date, end: date, sleep_sec: float = 4.0) -> list:
    """start～end：上市三張表＋上櫃除權息表；被擋或網路錯誤直接拋出（呼叫端決定要不要停）。"""
    from scrapers.official_prices import _get_with_retry

    rows = []
    for a, b in _half_years(start, end):
        rows += _fetch_tpex_events(a, b)
        time.sleep(sleep_sec)
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


# ── 補漏：事件表沒涵蓋、漲跌仍超過 ±10.6% 的上市日子，用每日「開盤競價基準」（TWT84U）補 ────────────
# 2026-10-26 修完事件日後仍有 8101 2024-11-19 +450%（減資恢復，三張表都沒列）、2321 東訊等。
# TWT84U 一天一個請求，只查有問題的那幾天。
TWT84U_PATH = "variation/TWT84U"
OUTLIER_PCT = 10.6
NEW_LISTING_DAYS = 5


def parse_twt84u(data: dict, day: str) -> list:
    """TWT84U：第 0 欄代號、2 欄漲停價、3 欄（漲停用的）開盤競價基準。基準是 '--' 的跳過。"""
    if data.get("stat") != "OK":
        return []
    out = []
    for r in data.get("data") or []:
        base, limit = _num(r[3]), _num(r[2])
        if base and base > 0:
            out.append({"stock_id": str(r[0]).strip(), "date": day, "pre_close": None, "ref": base,
                        "limit_up": limit, "open_base": base, "base": base, "src": "開盤競價基準"})
    return out


def outlier_days(prices: pd.DataFrame, twse_ids: set, known: set) -> list:
    """prices：stock_id, date（ISO）, change_pct。找上市、非上市前 5 天、不在事件表（known）裡、
    漲跌幅超過 ±10.6% 的 (日期, 股號)。"""
    p = prices.sort_values(["stock_id", "date"])
    seq = p.groupby("stock_id").cumcount()
    hit = (p["change_pct"].abs() > OUTLIER_PCT) & (seq >= NEW_LISTING_DAYS) & p["stock_id"].isin(twse_ids)
    return sorted((d, s) for s, d in zip(p.loc[hit, "stock_id"], p.loc[hit, "date"]) if (d, s) not in known)


def fetch_outlier_bases(targets: list, sleep_sec: float = 4.0) -> list:
    """targets：[(日期, 股號)]；每個日期查一次 TWT84U，只回傳 targets 裡的股票。"""
    from scrapers.official_prices import _get_with_retry

    wanted: dict = {}
    for day, sid in targets:
        wanted.setdefault(day, set()).add(sid)
    rows = []
    for day, sids in sorted(wanted.items()):
        resp = _get_with_retry(_URL.format(path=TWT84U_PATH),
                               {"date": day.replace("-", ""), "selectType": "ALL", "response": "json"}, _HEADERS_TWSE)
        _check_twse_response(resp)
        rows += [r for r in parse_twt84u(resp.json(), day) if r["stock_id"] in sids]
        time.sleep(sleep_sec)
    return rows
