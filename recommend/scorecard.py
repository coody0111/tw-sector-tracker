"""推薦成績單（規格 E22）：每筆推薦依規則追蹤到出場，跟回測期望值並列比較。"""
from datetime import datetime

import pandas as pd

from recommend.backtest import _core
from recommend.exits import simulate_trade

_DDL = """
CREATE TABLE IF NOT EXISTS recommendations (
    strategy VARCHAR, stock_id VARCHAR, signal_date DATE, type VARCHAR, routes VARCHAR, n_routes INTEGER,
    signal_close DOUBLE, entry_date DATE, entry_price DOUBLE, exit_date DATE, exit_price DOUBLE,
    exit_reason VARCHAR, ret DOUBLE, r_multiple DOUBLE, mfe DOUBLE, hold_days INTEGER, updated_at TIMESTAMP,
    PRIMARY KEY (strategy, stock_id, signal_date)
)
"""
_NOT_CLOSED = ("持有中", "買不到")   # 不計入成績（還沒出場、隔天一字漲停買不到）


def ensure_table(con) -> None:
    con.execute(_DDL)


def record_signals(con, signals: pd.DataFrame, features: pd.DataFrame) -> int:
    """新訊號寫入（已存在的不重寫），signal_close 取訊號日收盤。回傳新增筆數。"""
    closes = features.set_index(["stock_id", "date"])["close"]
    n = 0
    for s in signals.itertuples(index=False):
        if (s.stock_id, s.date) not in closes.index:
            continue
        exists = con.execute("SELECT count(*) FROM recommendations WHERE strategy=? AND stock_id=? AND signal_date=?",
                             [s.strategy, s.stock_id, s.date]).fetchone()[0]
        if exists:
            continue
        con.execute("INSERT INTO recommendations (strategy, stock_id, signal_date, type, routes, n_routes, signal_close, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [s.strategy, s.stock_id, s.date, s.type, s.routes, int(s.n_routes),
                     float(closes.loc[(s.stock_id, s.date)]), datetime.now()])
        n += 1
    return n


def refresh(con, features: pd.DataFrame) -> int:
    """還沒出場的推薦用最新行情重算出場；隔天一字漲停記「買不到」之後不再算。回傳處理筆數。"""
    open_rows = con.execute("SELECT strategy, stock_id, signal_date FROM recommendations "
                            "WHERE exit_reason IS NULL OR exit_reason = '持有中'").df()
    paths = {sid: g.reset_index(drop=True) for sid, g in
             features[["stock_id", "date", "open", "close", "one_word"]].sort_values("date").groupby("stock_id")}
    for r in open_rows.itertuples(index=False):
        path = paths.get(r.stock_id)
        if path is None:
            continue
        pos = path.index[path["date"] == pd.Timestamp(r.signal_date)]
        if len(pos) == 0 or pos[0] + 1 >= len(path):
            continue                                   # 還沒有隔天的資料
        t = simulate_trade(path, int(pos[0]))
        key = [r.strategy, r.stock_id, r.signal_date]
        if t is None:
            con.execute("UPDATE recommendations SET exit_reason='買不到', updated_at=? "
                        "WHERE strategy=? AND stock_id=? AND signal_date=?", [datetime.now(), *key])
            continue
        con.execute("UPDATE recommendations SET entry_date=?, entry_price=?, exit_date=?, exit_price=?, exit_reason=?, "
                    "ret=?, r_multiple=?, mfe=?, hold_days=?, updated_at=? WHERE strategy=? AND stock_id=? AND signal_date=?",
                    [t["entry_date"], t["entry_price"], t["exit_date"], t["exit_price"], t["exit_reason"], t["ret"],
                     t["r_multiple"], t["mfe"], t["hold_days"], datetime.now(), *key])
    return len(open_rows)


def summary(con, strategy: str) -> dict:
    """已出場的成績總覽＋持有中筆數＋分型態／按月（按推薦月份）。"""
    df = con.execute("SELECT * FROM recommendations WHERE strategy = ?", [strategy]).df()
    closed = df[df["exit_reason"].notna() & ~df["exit_reason"].isin(_NOT_CLOSED)]
    out = _core(closed)
    out["open_n"] = int((df["exit_reason"] == "持有中").sum())
    out["unfilled_n"] = int((df["exit_reason"] == "買不到").sum())
    closed = closed.assign(month=pd.to_datetime(closed["signal_date"]).dt.strftime("%Y-%m"))
    out["by_type"] = [{"type": k, **_core(g)} for k, g in closed.groupby("type")]
    out["by_month"] = [{"month": k, **_core(g)} for k, g in closed.groupby("month")]
    return out


def detail(con, strategy: str, limit: int = 300) -> list:
    """推薦頁明細：最新在前（日期轉字串，payload 才能直接 JSON 化）。"""
    return con.execute(
        "SELECT stock_id, CAST(signal_date AS VARCHAR) AS signal_date, type, entry_price, "
        "CAST(exit_date AS VARCHAR) AS exit_date, exit_price, exit_reason, ret, r_multiple, mfe, hold_days "
        "FROM recommendations WHERE strategy = ? ORDER BY signal_date DESC, stock_id LIMIT ?",
        [strategy, limit]).df().to_dict("records")
