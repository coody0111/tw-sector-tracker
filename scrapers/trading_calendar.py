"""
交易日行事曆：以 TWSE 官方 FMTQIK（每日市場成交資訊）為準，存成 data/trading_calendar.csv。

為什麼需要（2026-10-24）：config.TAIWAN_HOLIDAYS 是手打的，跟 FMTQIK 比漏了 11 天、
2020～2024 完全沒有，排程與回補把休市日當成交易日，寫進了行情複本與外資持股假資料
（見 bug-reports.md 2026-10-22、2026-10-24）。

檔案格式：date,is_trading — 「已確認」的每個日曆日一列（1＝交易日、0＝休市）。
- 已經過完的月份：整月每一天都有一列。
- 當月：只寫到 FMTQIK 已公布的最後一個交易日；之後的日子還不知道，不寫。
- 檔案裡沒有的日子 → calendar_status() 回 None，由呼叫端退回週末＋假日清單判斷。
"""
import logging
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# 用絕對路徑：排程程序（scripts/run_scheduled.py）的工作目錄不一定是專案根目錄
CALENDAR_PATH = Path(__file__).resolve().parent.parent / "data" / "trading_calendar.csv"


def _month_end(month_start: date) -> date:
    nxt = date(month_start.year + month_start.month // 12, month_start.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def month_status(month_start: date, trading_days: list, as_of: date) -> dict:
    """某月 FMTQIK 的交易日清單 → {日期: 是否交易日}，只含已能確認的日子。

    as_of：抓資料的基準日。月底 < as_of 視為整月已過、每天都能確認；
    否則（當月）只確認到清單裡最後一個交易日。"""
    days = {d for d in trading_days if d.year == month_start.year and d.month == month_start.month}
    end = _month_end(month_start)
    if end >= as_of:
        if not days:
            return {}
        end = max(days)
    out, d = {}, month_start
    while d <= end:
        out[d] = d in days
        d += timedelta(days=1)
    return out


def merge_status(status: dict, path: Path | None = None) -> int:
    """把 {日期: 是否交易日} 併進行事曆檔（同一天以新的為準），回傳寫入後總列數。"""
    path = path or CALENDAR_PATH
    rows = pd.DataFrame({"date": [d.isoformat() for d in status], "is_trading": [int(v) for v in status.values()]})
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str})
        rows = pd.concat([old, rows], ignore_index=True)
    rows = rows.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    _load.cache_clear()
    return len(rows)


def merge_trading_days(trading_days: list, as_of: date, path: Path | None = None) -> int:
    """把一批 FMTQIK 交易日（可跨多個整月，例如每日流程抓的 4 個月 TAIEX）併進行事曆。"""
    months = sorted({date(d.year, d.month, 1) for d in trading_days})
    status = {}
    for m in months:
        status.update(month_status(m, trading_days, as_of))
    return merge_status(status, path) if status else 0


@lru_cache(maxsize=4)
def _load(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"date": str})
    return dict(zip(df["date"], df["is_trading"].astype(bool)))


def calendar_status(d: date, path: Path | None = None) -> bool | None:
    """行事曆裡這天是不是交易日；行事曆沒涵蓋這天回 None。"""
    return _load(str(path or CALENDAR_PATH)).get(d.isoformat())


def update_calendar(start_month: date, today: date = None, path: Path | None = None,
                    sleep_sec: float = 1.0) -> int:
    """從 start_month 逐月抓 FMTQIK 到今天，已整月確認過的月份跳過。回傳本次抓了幾個月。
    TWSE 擋頁時停下、保留已抓到的部分（下次重跑會從缺的月份接著抓）。"""
    from scrapers.chips import TWSEBlockedError
    from scrapers.taiex import _fetch_taiex_month

    today = today or date.today()
    path = path or CALENDAR_PATH
    known = _load(str(path))
    fetched = 0
    m = date(start_month.year, start_month.month, 1)
    while m <= today:
        end = _month_end(m)
        if end < today and end.isoformat() in known:
            m = end + timedelta(days=1)
            continue
        try:
            rows = _fetch_taiex_month(m)
        except TWSEBlockedError as exc:
            logger.error("FMTQIK 被擋，行事曆停在 %s 之前：%s", m.isoformat(), exc)
            break
        merge_status(month_status(m, [r["date"] for r in rows], today), path)
        fetched += 1
        logger.info("行事曆：%s 已更新", m.strftime("%Y-%m"))
        m = end + timedelta(days=1)
        time.sleep(sleep_sec)
    return fetched
