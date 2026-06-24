"""
巨量換手訊號簡易回測

對 DuckDB 中每個有效交易日跑一次 scan_volume_turnover()，
然後查 D+1、D+3、D+5 的報酬，計算勝率與期望值。
"""
import logging
from typing import List, Dict, Any

import duckdb
import pandas as pd

from screener.signals import scan_volume_turnover

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"


def run_backtest(
    db_path: str = _DB_PATH,
    lookback: int = 126,
    hold_days: list = None,
) -> pd.DataFrame:
    """
    對 DuckDB 中所有交易日逐日掃描訊號，並計算後續報酬。

    Returns
    -------
    DataFrame，每列一個訊號，含：
        signal_date, stock_id, entry_close, change_pct, vol_multiple,
        ret_d1, ret_d3, ret_d5   (報酬率 %，無資料為 NaN)
        win_d3, win_d5           (True/False)
    """
    if hold_days is None:
        hold_days = [1, 3, 5]

    con = duckdb.connect(db_path, read_only=True)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date"
    ).fetchall()]

    # 取所有行情供後續查報酬
    all_prices = con.execute(
        "SELECT stock_id, date, close FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    all_prices["date"] = pd.to_datetime(all_prices["date"])
    # 建立 (stock_id, date) → close 的快查 dict
    price_map: dict = {
        (row.stock_id, row.date): row.close
        for row in all_prices.itertuples()
    }
    # 每支股票的有序日期清單
    stock_dates: dict = {}
    for sid, grp in all_prices.groupby("stock_id"):
        stock_dates[sid] = sorted(grp["date"].tolist())

    rows = []
    for d in dates:
        d_str = str(d)[:10]
        signals = scan_volume_turnover(d_str, lookback=lookback, db_path=db_path)
        if not signals:
            continue

        d_ts = pd.Timestamp(d_str)
        for sig in signals:
            sid = sig["stock_id"]
            entry = sig["close"]
            row = {
                "signal_date":  d_str,
                "stock_id":     sid,
                "entry_close":  entry,
                "change_pct":   sig["change_pct"],
                "vol_multiple": sig["vol_multiple"],
                "vol_days":     sig["vol_window_days"],
            }
            # 查後續報酬
            dates_for_stock = stock_dates.get(sid, [])
            future = [t for t in dates_for_stock if t > d_ts]
            for n in hold_days:
                if len(future) >= n:
                    fut_close = price_map.get((sid, future[n - 1]))
                    ret = round((fut_close - entry) / entry * 100, 2) if fut_close else None
                else:
                    ret = None
                row[f"ret_d{n}"] = ret

            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for n in hold_days:
        col = f"ret_d{n}"
        if col in df.columns:
            df[f"win_d{n}"] = df[col].apply(lambda x: x > 0 if x is not None else None)

    return df


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
