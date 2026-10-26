"""推薦卡片欄位與提醒（規格 C16、C18）：提醒只顯示、不擋訊號。"""
import pandas as pd

from recommend.exits import STOP

BIAS_HOT = 0.30   # MA10 乖離 ≥ 30% 顯示「乖離大」（13.10：當規則會變差，只提醒）


def build_cards(features: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp, rally_pct: float | None = None) -> list:
    """每筆訊號一張卡：現價、推薦後漲跌、乖離、季線、提醒、是否失效（現價 ≤ 推薦日收盤 × 0.94）。"""
    f = features.sort_values(["stock_id", "date"])
    g = f.groupby("stock_id")["close"]
    f = f.assign(ma10=g.transform(lambda s: s.rolling(10).mean()), ma60=g.transform(lambda s: s.rolling(60).mean()))
    today = f[f["date"] == day].set_index("stock_id")
    closes = f.set_index(["stock_id", "date"])["close"]
    cards = []
    for s in signals.itertuples(index=False):
        if s.stock_id not in today.index:
            continue
        t = today.loc[s.stock_id]
        sig_close = float(closes.loc[(s.stock_id, s.date)])
        close = float(t["close"])
        since = close / sig_close - 1
        bias10 = close / t["ma10"] - 1 if pd.notna(t["ma10"]) else None
        below60 = bool(pd.notna(t["ma60"]) and close < t["ma60"])
        alerts = []
        if bias10 is not None and bias10 >= BIAS_HOT:
            alerts.append("乖離大")
        if below60:
            alerts.append("季線下")
        if rally_pct is not None and since >= rally_pct:
            alerts.append("已漲多")
        prev = close - (t["change"] if pd.notna(t["change"]) else 0)
        cards.append({
            "stock_id": s.stock_id, "stock_name": t["stock_name"], "meta_sector": t["meta_sector"],
            "strategy": s.strategy, "type": s.type, "routes": s.routes, "n_routes": int(s.n_routes),
            "signal_date": pd.Timestamp(s.date).date().isoformat(), "signal_close": sig_close,
            "close": close, "change_pct": round((close / prev - 1) * 100, 2) if prev else None,
            "since_signal_pct": round(since * 100, 2), "bias10": None if bias10 is None else round(bias10 * 100, 1),
            "below_ma60": below60, "alerts": alerts,
            "vr": _round(t.get("vr"), 2), "rng20": _round(t.get("rng20"), 3, 100),
            "ret20_prev": _round(t.get("ret20_prev"), 3, 100),
            "status": "失效" if close <= sig_close * (1 - STOP) else "有效",
        })
    return cards


def _round(v, nd: int, scale: float = 1):
    """卡片上的量比、前 20 日區間／漲幅（%）；缺值給 None。"""
    return None if v is None or pd.isna(v) else round(float(v) * scale, nd)


def group_by_sector(cards: list) -> list:
    """依族群分組，檔數多的在前，同數依族群名稱。"""
    groups: dict = {}
    for c in cards:
        groups.setdefault(c["meta_sector"], []).append(c)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"sector": k, "count": len(v), "cards": v} for k, v in ordered]
