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

# ── 今日追繳(估) 檔數（2026-11-04 Cody：做，只顯示）──────────────────────────
# 個股融資維持率(估) < 130%（weekly_chips.DANGER，同頁面 export/index_generator.py 的「追繳risk」）、有融資、
# 近 20 個交易日（含當天，跟維持率的均價同一段）均成交值 ≥ 1 億的檔數。
# 回測（scratchpad bt_margin_call.py，2025-01～2026-11，444 天）：一半以上的日子 0 檔；≥10 檔只有 16 天，
# 全在 2025-04、2026-07 兩次修正（＋2026-11-03/04）。當天 ≥31 檔的個股之後 20 日 95% 上漲，但獨立事件只有 2 次，
# 個股追繳當天買、用 6% 停損並不賺（多半先被洗掉）。所以只顯示，不擋也不產生訊號。
MARGIN_CALL_WAVE = 10      # ≥10 檔標「追繳潮」
# 說明文字寫明是哪兩次，不寫「2025 年以來 N 次」——再發生一次就會過時（2026-11-04 Debugger 🟡）
PAST_WAVES = "前兩次（2025-04、2026-07）"


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
        px = con.execute("SELECT stock_id, avg(close) AS avg, arg_max(close, date) AS close, "
                         "avg(volume * 1000 * close) AS turnover FROM daily_prices "
                         "WHERE date >= ? AND date <= ? GROUP BY 1", [min(days), d]).df()
        bal = con.execute("SELECT stock_id, margin_balance AS balance FROM margin WHERE date = ?", [d]).df()
    finally:
        con.close()
    m = maintenance(px.merge(bal, on="stock_id").merge(uni, on="stock_id"))
    if m["all"] is None:
        return None
    return {"date": pd.Timestamp(d).date().isoformat(), "all": m["all"], "twse": m["twse"], "tpex": m["tpex"],
            "calls": _margin_calls(m["danger"], px)}


def _margin_calls(danger: list, px: pd.DataFrame) -> int:
    """maintenance() 的 danger（維持率(估) < 130%、有融資）裡，近 20 日（含當天）均成交值達流動性門檻的檔數。"""
    from recommend.features import MIN_TURNOVER20
    liquid = set(px.loc[px["turnover"] >= MIN_TURNOVER20, "stock_id"])
    return sum(1 for r in danger if r["stock_id"] in liquid)


def margin_call_note(r: dict | None) -> str | None:
    """「今日追繳(估) 14 檔」；≥10 檔加追繳潮說明。沒有 calls 欄（舊 payload）回 None。"""
    n = (r or {}).get("calls")
    if n is None:
        return None
    if n >= MARGIN_CALL_WAVE:
        return f"今日追繳(估) {n} 檔＝追繳潮：{PAST_WAVES}之後 20 日多數反彈（樣本少，不是買進訊號）"
    return f"今日追繳(估) {n} 檔"


def margin_note(payload: dict, always: bool = True) -> str | None:
    """「大盤融資維持率(估) 158.2%（10/30）；今日追繳(估) 3 檔。」；低於 150% 加斷頭潮說明、≥10 檔標追繳潮。
    always=False（報告重點／Telegram）時只在低於 150% 或追繳潮才回。"""
    r = payload.get("margin_ratio") or {}
    v = r.get("all")
    if v is None:
        return None
    low = v < MARGIN_LOW
    wave = (r.get("calls") or 0) >= MARGIN_CALL_WAVE
    if not (always or low or wave):
        return None
    head = f"大盤融資維持率(估) {v:.1f}%（{r['date'][5:7]}/{r['date'][8:10]}）"
    if low:
        head += f"：低於 {MARGIN_LOW}%＝斷頭潮，{PAST_WAVES}之後 20 日都反彈（樣本少，不是買進訊號）"
    calls = margin_call_note(r)
    # 兩個都有時，追繳那句保留「追繳潮」字樣、但不重複「樣本少」說明（2026-11-04 Debugger 🟡：原本把追繳潮也拿掉了）
    if calls and low and wave:
        calls = f"今日追繳(估) {r['calls']} 檔＝追繳潮"
    return head + (f"；{calls}" if calls else "") + "。"
