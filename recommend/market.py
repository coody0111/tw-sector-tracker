"""推薦頁頁首的大盤資訊（規格 C18）：只顯示，不擋訊號（13.12）。"""
import pandas as pd

from recommend.exits import STOP
from recommend.features import adjusted
from recommend.ticks import limit_down_price

FAIL_LOOKBACK = 10   # 近 10 個交易日的突破訊號
FAIL_MIN_N = 5       # 樣本少於 5 筆不算失敗率


def ma60_note(payload: dict) -> str | None:
    """加權收在季線下的提醒（Cody 2026-11-01 選「標」）：只提醒、不擋訊號，成績單照記；缺資料不提醒。"""
    if payload.get("taiex_above_ma60") is not False:
        return None
    gap = payload.get("taiex_ma60_gap")
    return "加權在季線下，暫停新倉。" if gap is None else f"加權在季線下（低 {abs(gap) * 100:.1f}%），暫停新倉。"


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


# ── 大盤融資維持率(估)（2026-11-03 Cody：做）──────────────────────────────
# 回測（scratchpad bt_margin.py，2024-12-31～2026-10-30，439 天）：中位數約 180%；低於 150% 只有 8 天、
# 來自 2 次事件（2025-04 關稅、2026-07 底），之後 20 日加權都漲 8～18%。樣本太少，只顯示、不擋訊號。
MARGIN_LOW = 150
MARGIN_LOOKBACK = 5        # 往回找最近一天兩邊市場融資都到齊的日子


def market_margin_ratio(day, db_path: str | None = None, universe_path: str | None = None) -> dict | None:
    """day（含）以前最近一個融資到齊日的大盤融資維持率(估)：全部／上市／上櫃。算不出來回 None。
    公式同每週籌碼報告（recommend.weekly_chips.maintenance）：融資市值合計 ÷ 以 20 日均價估的融資金額合計。"""
    import duckdb

    from recommend.data import DB_PATH, UNIVERSE_PATH
    from recommend.weekly_chips import AVG_DAYS, maintenance
    from screener.data_integrity import market_day_complete

    uni = pd.read_csv(universe_path or UNIVERSE_PATH, dtype=str, encoding="utf-8-sig")[["stock_id", "stock_name", "exchange"]]
    ids = {ex: set(uni.loc[uni["exchange"] == ex, "stock_id"]) for ex in ("TWSE", "TPEx")}
    con = duckdb.connect(db_path or DB_PATH, read_only=True)
    try:
        dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM margin WHERE date <= ? ORDER BY date DESC LIMIT ?",
                                           [str(day)[:10], MARGIN_LOOKBACK]).fetchall()]
        d = next((x for x in dates if all(market_day_complete(con, "margin", x, ids[ex]) for ex in ids)), None)
        if d is None:
            return None
        days = [r[0] for r in con.execute("SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
                                          [d, AVG_DAYS]).fetchall()]
        px = con.execute("SELECT stock_id, avg(close) AS avg, arg_max(close, date) AS close FROM daily_prices "
                         "WHERE date >= ? AND date <= ? GROUP BY 1", [min(days), d]).df()
        bal = con.execute("SELECT stock_id, margin_balance AS balance FROM margin WHERE date = ?", [d]).df()
    finally:
        con.close()
    m = maintenance(px.merge(bal, on="stock_id").merge(uni, on="stock_id"))
    if m["all"] is None:
        return None
    return {"date": pd.Timestamp(d).date().isoformat(), "all": m["all"], "twse": m["twse"], "tpex": m["tpex"]}


def margin_note(payload: dict, always: bool = True) -> str | None:
    """「大盤融資維持率(估) 158.2%（10/30）。」；低於 150% 加斷頭潮說明。always=False 時只在低於 150% 才回。"""
    r = payload.get("margin_ratio") or {}
    v = r.get("all")
    if v is None:
        return None
    low = v < MARGIN_LOW
    if not (always or low):
        return None
    head = f"大盤融資維持率(估) {v:.1f}%（{r['date'][5:7]}/{r['date'][8:10]}）"
    if low:
        return head + f"：低於 {MARGIN_LOW}%＝斷頭潮，2025 年以來 2 次之後 20 日都反彈（樣本少，不是買進訊號）。"
    return head + "。"
