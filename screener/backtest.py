"""
通用訊號回測框架

對 DuckDB 中每個有效交易日跑一次傳入的 scanner callable，
以 D+1 開盤價進場，計算多天期（預設 5/10/14 日）後的收盤報酬。
"""
import logging
from typing import Callable, List, Dict, Any

import duckdb
import pandas as pd

from screener.signals import scan_volume_turnover

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"


def _build_price_index(db_path: str):
    """
    讀出整張 daily_prices，建立 (stock_id, date) → open/close 的快查 dict，
    以及每支股票的有序交易日清單，供 _forward_return 查詢用。
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT stock_id, date, open, close FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    close_map = {(r.stock_id, r.date): r.close for r in df.itertuples()}
    open_map = {(r.stock_id, r.date): r.open for r in df.itertuples()}
    stock_dates = {sid: sorted(g["date"].tolist()) for sid, g in df.groupby("stock_id")}
    return close_map, open_map, stock_dates


def _forward_return(close_map, open_map, stock_dates, sid, d_ts, horizon):
    """
    以訊號日 d_ts 的 D+1 開盤價進場（缺值時退回 D+1 收盤），
    以 D+1+horizon 收盤價出場，回傳 (entry_price, ret_pct)。
    資料不足時回傳 (None, None)。
    """
    future = [t for t in stock_dates.get(sid, []) if t > d_ts]
    if len(future) < horizon + 1:          # 需要 D+1(進場) 與 D+1+horizon(出場)
        return None, None
    entry_date, exit_date = future[0], future[horizon]
    entry = open_map.get((sid, entry_date))
    if entry is None or pd.isna(entry):    # open 缺(import 丟掉)→退回 D+1 收盤
        entry = close_map.get((sid, entry_date))
    exit_close = close_map.get((sid, exit_date))
    if entry is None or pd.isna(entry) or entry == 0 or exit_close is None or pd.isna(exit_close):
        return entry, None
    return entry, round((exit_close - entry) / entry * 100, 2)


def run_backtest(
    scanner: Callable[[str, str], List[Dict[str, Any]]],
    db_path: str = _DB_PATH,
    horizons=(5, 10, 14),
) -> pd.DataFrame:
    """
    對 DuckDB 中所有交易日逐日呼叫 scanner(date_str, db_path)，
    並以 D+1 開盤進場計算多天期報酬。

    Parameters
    ----------
    scanner : Callable[[str, str], list[dict]]
        (date_str, db_path) -> [{"stock_id": ..., "close": ...}, ...]

    Returns
    -------
    DataFrame，每列一個訊號，含：
        signal_date, stock_id, entry_price, ret_5, ret_10, ret_14 (依 horizons 而定)
    """
    close_map, open_map, stock_dates = _build_price_index(db_path)
    con = duckdb.connect(db_path, read_only=True)
    dates = [str(r[0])[:10] for r in con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date").fetchall()]
    con.close()

    rows = []
    for d_str in dates:
        picks = scanner(d_str, db_path)
        if not picks:
            continue
        d_ts = pd.Timestamp(d_str)
        for sig in picks:
            sid = sig["stock_id"]
            row = {"signal_date": d_str, "stock_id": sid, "entry_price": None}
            for h in horizons:
                entry, ret = _forward_return(close_map, open_map, stock_dates, sid, d_ts, h)
                row["entry_price"] = entry
                row[f"ret_{h}"] = ret
            rows.append(row)
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame) -> None:
    if df.empty:
        print("無訊號資料")
        return

    print(f"\n{'='*55}")
    print(f"  巨量換手回測結果  共 {len(df)} 個訊號  視窗 {df['vol_days'].min()}~{df['vol_days'].max()} 日")
    print(f"{'='*55}")
    print(f"  訊號日期範圍: {df['signal_date'].min()} ~ {df['signal_date'].max()}")
    print(f"  平均量倍數:   {df['vol_multiple'].mean():.1f}x")
    print()

    for n in [1, 3, 5]:
        col_ret = f"ret_d{n}"
        col_win = f"win_d{n}"
        if col_ret not in df.columns:
            continue
        sub = df[df[col_ret].notna()]
        if sub.empty:
            continue
        win_rate = sub[col_win].mean() * 100
        avg_ret  = sub[col_ret].mean()
        avg_win  = sub[sub[col_win] == True][col_ret].mean() if (sub[col_win] == True).any() else 0
        avg_loss = sub[sub[col_win] == False][col_ret].mean() if (sub[col_win] == False).any() else 0
        ev       = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
        print(f"  D+{n}  勝率 {win_rate:.0f}%  "
              f"平均報酬 {avg_ret:+.2f}%  "
              f"贏 {avg_win:+.2f}% / 輸 {avg_loss:+.2f}%  "
              f"期望值 {ev:+.2f}%")

    print(f"\n{'─'*55}")
    print("  個別訊號明細:")
    cols = ["signal_date","stock_id","entry_close","change_pct","vol_multiple"] + \
           [c for c in ["ret_d1","ret_d3","ret_d5"] if c in df.columns]
    print(df[cols].to_string(index=False))
