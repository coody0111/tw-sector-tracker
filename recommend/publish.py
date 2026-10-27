"""個股推薦發布時點（2026-10-27 Cody：「時間一定要對齊」）。

回測用的是訊號日 D 當天的完整資料：當天三大法人／外資持股，以及含 D 在內最近一份集保。
收盤 15:00 這些還沒公布（10/27 實測 T86、MI_QFIIS 都回「沒有資料」），所以推薦不在收盤出，
改由每天 20:00（＋平日 08:00 保險）的排程檢查：D 的資料都到齊才發布。
- 三大法人、外資持股：上市、上櫃都要有 D 這天
- 集保：資料日是每週最後一個交易日（通常週五，遇假日提前），D 是週最後交易日時要等那週集保公布（通常週末）
"""
from datetime import date, timedelta

import duckdb
import pandas as pd

from recommend.data import DB_PATH, UNIVERSE_PATH

_CHIP_TABLES = (("institutional", "三大法人"), ("foreign_holdings", "外資持股"))
_MARKETS = (("TWSE", "上市"), ("TPEx", "上櫃"))


def is_week_last_trading_day(day: date, is_trading_day) -> bool:
    """下一個交易日落在下一週（ISO 週）→ D 是這週最後一個交易日（集保資料日）。"""
    d = day + timedelta(days=1)
    for _ in range(14):
        if is_trading_day(d.isoformat()):
            return d.isocalendar()[:2] != day.isocalendar()[:2]
        d += timedelta(days=1)
    return True


def _connect(db_path: str):
    return duckdb.connect(db_path, read_only=True)


def latest_price_date(db_path: str = DB_PATH) -> date | None:
    con = _connect(db_path)
    try:
        d = con.execute("SELECT max(date) FROM daily_prices").fetchone()[0]
    finally:
        con.close()
    return None if d is None else pd.Timestamp(d).date()


def shareholder_asof(day: date, db_path: str = DB_PATH) -> str | None:
    """含 D 在內最近一份集保的資料日（＝ run_daily payload 的 shareholder_date）。"""
    con = _connect(db_path)
    try:
        d = con.execute("SELECT max(date) FROM shareholder WHERE date <= ?", [day]).fetchone()[0]
    finally:
        con.close()
    return None if d is None else pd.Timestamp(d).date().isoformat()


def missing_inputs(day: date, is_trading_day, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH) -> list:
    """D 還缺哪些資料（空 list＝可以發布）。例：["上櫃外資持股", "集保"]。"""
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")
    market_ids = {ex: set(uni.loc[uni["exchange"] == ex, "stock_id"]) for ex, _ in _MARKETS}
    missing = []
    con = _connect(db_path)
    try:
        for table, label in _CHIP_TABLES:
            have = set(con.execute(f"SELECT DISTINCT stock_id FROM {table} WHERE date = ?", [day]).df()["stock_id"])
            missing += [f"{name}{label}" for ex, name in _MARKETS if not have & market_ids[ex]]
        sh = con.execute("SELECT max(date) FROM shareholder").fetchone()[0]
    finally:
        con.close()
    if is_week_last_trading_day(day, is_trading_day) and (sh is None or pd.Timestamp(sh).date() < day):
        missing.append("集保")
    return missing
