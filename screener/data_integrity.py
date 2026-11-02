"""
資料完整性守門：判斷「近 N 交易日」窗口是不是真的只跨了 N 個交易日。

**這支模組存在的理由**（2026-08-28 金居 8358 事件）：
專案裡到處都是 `ORDER BY date DESC LIMIT N` / `ROW_NUMBER() <= N` 這種寫法，
它數的是 `daily_prices` 裡**實際存在的資料列**，不是真實交易日。只要某幾個
交易日沒抓到，「5 交易日前」就會悄悄跨到更早的日期，算出來的「近5日漲幅」
變成近一個月的漲幅——而且不會報錯。

當時 DB 缺了 8/07~8/24 共 15 個交易日，8358 的「5日漲幅」顯示 +100.37%
（實際是 7/30→8/28 將近一個月），全市場 1040 檔裡有 1035 檔（99.5%）的
5 日窗口被拉長，中位數跨 29 個日曆天。

**判斷方式**（2026-11-03 改）：優先用官方交易日曆（data/trading_calendar.csv，TWSE FMTQIK），
逐日比對缺了哪幾個交易日——只缺 1 天也抓得到。日曆沒涵蓋的日子（還沒抓到的月份）才退回舊規則：
N 個交易日正常會跨掉 `ceil(N/5)*2` 個週末日，再給連假緩衝，超過就是中間有洞
（舊規則只抓得到 12 個日曆天以上的大洞，code review 2026-11-03）。
"""
import logging
import math
from datetime import date, timedelta
from typing import Callable, Iterable, List, Optional, Tuple

from scrapers.trading_calendar import calendar_status

logger = logging.getLogger(__name__)

# 連假緩衝（日曆天）。台股最長連假是農曆春節，約 5~9 個日曆天沒有交易日。
# 取 9 天：寧可對真連假放行（少數窗口略微失真），也不要把正常資料誤判成有洞。
_HOLIDAY_BUFFER_DAYS = 9
PARTIAL_RATIO = 0.8          # 某天行情筆數 < 近期每日筆數中位數 × 80% ＝只抓到一部分（2026-10-27 盤中只有 560/1035 檔）

IsTrading = Callable[[date], Optional[bool]]     # 交易日 True／休市 False／日曆沒涵蓋 None


def trading_days_between(start: date, end: date, is_trading: IsTrading = calendar_status) -> Optional[List[date]]:
    """日曆上 start（不含）到 end（不含）之間的交易日；中間有任何一天日曆沒涵蓋就回 None（呼叫端退回舊規則）。"""
    out, d = [], start + timedelta(days=1)
    while d < end:
        status = is_trading(d)
        if status is None:
            return None
        if status:
            out.append(d)
        d += timedelta(days=1)
    return out


def max_span_days(n_trading_days: int) -> int:
    """N 個交易日「合理」會跨掉幾個日曆天（上限，含週末與連假緩衝）。

    N 個交易日至少跨 N 天，每滿 5 個交易日會夾一個週末（+2 天），
    再加連假緩衝。例：5→16、10→23、20→37。
    超過這個跨度，代表窗口中間有交易日缺漏。
    """
    if n_trading_days < 1:
        raise ValueError("n_trading_days must be >= 1")
    weekend_days = math.ceil(n_trading_days / 5) * 2
    return n_trading_days + weekend_days + _HOLIDAY_BUFFER_DAYS


def window_is_reliable(
    date_now: Optional[date], date_then: Optional[date], n_trading_days: int,
    is_trading: IsTrading = calendar_status,
) -> bool:
    """這個「近 N 交易日」窗口可不可信（中間沒有交易日缺漏）。

    date_now  = 窗口最新一筆的日期（rn=1）
    date_then = 窗口起點的日期（rn=N+1）
    任一為 None（資料不足）一律視為不可信。
    有日曆時：(date_then, date_now] 之間的官方交易日數要剛好是 N，多出來就是中間缺了資料。
    """
    if date_now is None or date_then is None:
        return False
    span = (date_now - date_then).days
    if span < 0:
        return False
    between = trading_days_between(date_then, date_now, is_trading)
    if between is not None and is_trading(date_now) is not None:
        return len(between) + int(bool(is_trading(date_now))) <= n_trading_days
    return span <= max_span_days(n_trading_days)


def find_gaps(dates: Iterable[date], is_trading: IsTrading = calendar_status) -> List[Tuple[date, date]]:
    """在一串交易日期裡找出斷層，回傳 [(斷層前一天, 斷層後一天), ...]。

    有日曆時：相鄰兩天之間只要夾著任何一個官方交易日就是斷層（只缺 1 天也算）。
    日曆沒涵蓋時退回舊規則：正常最多隔一個週末（週五→週一 = 3 天）再給連假緩衝，超過才算。
    輸入不需先排序；少於 2 個日期時回空清單。
    """
    ordered = sorted(d for d in dates if d is not None)
    if len(ordered) < 2:
        return []
    limit = 3 + _HOLIDAY_BUFFER_DAYS
    gaps = []
    for prev, cur in zip(ordered, ordered[1:]):
        between = trading_days_between(prev, cur, is_trading)
        if (between is not None and between) or (between is None and (cur - prev).days > limit):
            gaps.append((prev, cur))
    return gaps


def missing_days(gaps: List[Tuple[date, date]], is_trading: IsTrading = calendar_status) -> List[date]:
    """斷層裡缺的官方交易日（日曆沒涵蓋的斷層不列）。"""
    out = []
    for a, b in gaps:
        out += trading_days_between(a, b, is_trading) or []
    return out


def _stale_days(latest: Optional[date], today: date, is_trading: IsTrading) -> List[date]:
    """latest 之後、今天（含）以前，日曆上已確認的交易日（＝行情該有卻沒有）。"""
    if latest is None:
        return []
    out, d = [], latest + timedelta(days=1)
    while d <= today:
        if is_trading(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def check_price_continuity(con, lookback_days: int = 90, is_trading: IsTrading = calendar_status,
                           today: Optional[date] = None) -> dict:
    """檢查 daily_prices 最近 lookback_days 個日曆天：缺了哪些交易日、有沒有只抓到一部分的日子、最新一天是否落後。

    con 是既有的 DuckDB connection（呼叫端負責開關）。
    回傳 {"ok", "latest", "gaps", "missing", "partial", "stale", "message"}。
    給 main.py 開跑時做前置體檢用——資料有洞就該讓人看見，而不是安靜地
    產出一份「近5日漲幅 +100%」的報告。
    """
    today = today or date.today()
    since = today - timedelta(days=lookback_days)
    rows = con.execute(
        "SELECT date, count(*) FROM daily_prices WHERE date >= ? GROUP BY date ORDER BY date",
        [since],
    ).fetchall()
    dates = [r[0] for r in rows]
    gaps = find_gaps(dates, is_trading)
    missing = missing_days(gaps, is_trading)
    latest = dates[-1] if dates else None
    stale = _stale_days(latest, today, is_trading)
    counts = sorted(r[1] for r in rows)
    median = counts[len(counts) // 2] if counts else 0
    partial = [(d, n) for d, n in rows if n < median * PARTIAL_RATIO]

    problems = []
    if not dates:
        problems.append(f"daily_prices 最近 {lookback_days} 天完全沒有資料")
    if gaps:
        detail = "、".join(str(d) for d in missing) if missing else "、".join(f"{a}→{b}" for a, b in gaps)
        problems.append(f"缺 {len(missing) or len(gaps)} 個交易日：{detail}")
    if stale:
        problems.append(f"最新只到 {latest}，之後還有 {len(stale)} 個交易日沒有行情（{'、'.join(map(str, stale))}）")
    if partial:
        problems.append("只抓到一部分的日子：" + "、".join(f"{d}（{n}/{median} 筆）" for d, n in partial))
    if problems:
        message = ("daily_prices " + "；".join(problems) + "。近N日類指標會算錯或顯示無資料，"
                   "請跑 `python main.py --backfill-yf 20 --workers 3` 補齊（跑完會自動 reimport）。")
    else:
        message = f"daily_prices 連續性正常（最新 {latest}，共 {len(dates)} 個交易日）"

    return {"ok": not problems, "latest": latest, "gaps": gaps, "missing": missing, "partial": partial,
            "stale": stale, "message": message}
