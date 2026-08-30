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

**判斷方式**：不需要交易日曆來源。N 個交易日正常會跨掉 `ceil(N/5)*2` 個
週末日，再給連假緩衝，就能界定合理跨度上限；超過就是中間有洞。
"""
import logging
import math
from datetime import date, timedelta
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 連假緩衝（日曆天）。台股最長連假是農曆春節，約 5~9 個日曆天沒有交易日。
# 取 9 天：寧可對真連假放行（少數窗口略微失真），也不要把正常資料誤判成有洞。
_HOLIDAY_BUFFER_DAYS = 9


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
    date_now: Optional[date], date_then: Optional[date], n_trading_days: int
) -> bool:
    """這個「近 N 交易日」窗口可不可信（中間沒有交易日缺漏）。

    date_now  = 窗口最新一筆的日期（rn=1）
    date_then = 窗口起點的日期（rn=N+1）
    任一為 None（資料不足）一律視為不可信。
    """
    if date_now is None or date_then is None:
        return False
    span = (date_now - date_then).days
    if span < 0:
        return False
    return span <= max_span_days(n_trading_days)


def find_gaps(dates: Iterable[date]) -> List[Tuple[date, date]]:
    """在一串交易日期裡找出斷層，回傳 [(斷層前一天, 斷層後一天), ...]。

    判斷依據：相鄰兩個交易日之間，正常最多隔一個週末（週五→週一 = 3 天），
    再給連假緩衝。超過就是中間有交易日沒抓到。
    輸入不需先排序；少於 2 個日期時回空清單。
    """
    ordered = sorted(d for d in dates if d is not None)
    if len(ordered) < 2:
        return []
    limit = 3 + _HOLIDAY_BUFFER_DAYS
    return [
        (prev, cur)
        for prev, cur in zip(ordered, ordered[1:])
        if (cur - prev).days > limit
    ]


def check_price_continuity(con, lookback_days: int = 90) -> dict:
    """檢查 daily_prices 最近 lookback_days 個日曆天有沒有交易日缺漏。

    con 是既有的 DuckDB connection（呼叫端負責開關）。
    回傳 {"ok": bool, "latest": date|None, "gaps": [(前, 後), ...], "message": str}。
    給 main.py 開跑時做前置體檢用——資料有洞就該讓人看見，而不是安靜地
    產出一份「近5日漲幅 +100%」的報告。
    """
    since = date.today() - timedelta(days=lookback_days)
    rows = con.execute(
        "SELECT DISTINCT date FROM daily_prices WHERE date >= ? ORDER BY date",
        [since],
    ).fetchall()
    dates = [r[0] for r in rows]
    gaps = find_gaps(dates)
    latest = dates[-1] if dates else None

    if not dates:
        message = f"daily_prices 最近 {lookback_days} 天完全沒有資料"
    elif gaps:
        detail = "、".join(f"{a}→{b}（缺 {(b - a).days - 1} 個日曆天）" for a, b in gaps)
        message = (
            f"daily_prices 有 {len(gaps)} 處交易日缺漏：{detail}。"
            "近N日類指標會跨過這些洞、算出偏大的漲跌幅，"
            "請先跑 `python main.py --backfill-yf 20 --workers 3` 再 `--reimport` 補齊。"
        )
    else:
        message = f"daily_prices 連續性正常（最新 {latest}，共 {len(dates)} 個交易日）"

    return {"ok": not gaps and bool(dates), "latest": latest, "gaps": gaps, "message": message}
