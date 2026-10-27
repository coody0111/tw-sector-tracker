"""推薦頁頁首的大盤資訊（規格 C18）：只顯示，不擋訊號（13.12）。"""
import pandas as pd

from recommend.exits import STOP
from recommend.features import adjusted
from recommend.ticks import limit_down_price

FAIL_LOOKBACK = 10   # 近 10 個交易日的突破訊號
FAIL_MIN_N = 5       # 樣本少於 5 筆不算失敗率


def market_header(features: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp) -> dict:
    f = features.sort_values(["stock_id", "date"]).assign(_ac=lambda x: adjusted(x), _ao=lambda x: adjusted(x, "open"))
    ma20 = f.groupby("stock_id")["_ac"].transform(lambda s: s.rolling(20).mean())   # 還原價
    is_today = f["date"] == day
    today = f[is_today].assign(ma20=ma20[is_today])
    pool = today[today["liq"]]
    ref = today["close"] - today["change"].fillna(0)
    down = today["close"] <= ref.map(lambda r: limit_down_price(r) if r > 0 else -1) + 1e-6
    fail_rate, fail_n = _fail_rate(f, signals, day)
    return {
        "above_ma20_pct": float((pool["_ac"] > pool["ma20"]).mean()) if len(pool) else None,
        "limit_up": int(today["limit_up"].sum()),
        "limit_down": int(down.sum()),
        "fail_rate": fail_rate,
        "fail_n": fail_n,
    }


def _fail_rate(f: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp) -> tuple:
    """day 之前 10 個交易日的訊號，隔天開盤進場後到 day 收盤為止曾收在停損價以下的比例。"""
    days = sorted(f.loc[f["date"] < day, "date"].unique())[-FAIL_LOOKBACK:]
    sig = signals[signals["date"].isin(days)]
    fails = []
    for s in sig.itertuples(index=False):
        p = f[(f["stock_id"] == s.stock_id) & (f["date"] > s.date) & (f["date"] <= day)]
        if p.empty:
            continue
        entry = p["_ao"].iloc[0]
        fails.append(bool((p["_ac"] <= entry * (1 - STOP)).any()))
    if len(fails) < FAIL_MIN_N:
        return None, len(fails)
    return sum(fails) / len(fails), len(fails)
