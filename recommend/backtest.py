"""回測框架（規格 §11 報告欄位、§12 及格所需數字、§6 案例庫自動指標）。"""
import numpy as np
import pandas as pd

from recommend.exits import FEE, TAX, simulate_trade

CASES = [("6672", "2026-09-24"), ("6213", "2026-09-24")]   # §6 C2、C5 必考題
WIN_GAIN, WIN_HORIZON, WIN_DEDUP = 1.0, 30, 40            # 飆股：30 日內 ≥ +100%，同股 40 日內只留一段
CATCH_BEFORE, CATCH_AFTER = 5, 15                          # 起漲 −5～+15 日內有訊號算抓到
BLOWUP_DAYS, BLOWUP_RET = 20, -0.15                        # 踩雷：訊號後 20 日 ≤ −15%


def run_trades(features: pd.DataFrame, signals: pd.DataFrame, exclude_dates=()) -> pd.DataFrame:
    """每個訊號跑出場模擬；exclude_dates 為要排除的訊號日（假交易日、大盤反轉日）。"""
    excl = set(pd.to_datetime(list(exclude_dates)))
    sig = signals[~signals["date"].isin(excl)]
    paths = {sid: g.reset_index(drop=True) for sid, g in
             features[["stock_id", "date", "open", "close", "one_word"]].groupby("stock_id", sort=False)}
    rows = []
    for s in sig.itertuples(index=False):
        path = paths.get(s.stock_id)
        if path is None:
            continue
        pos = path.index[path["date"] == s.date]
        if len(pos) == 0:
            continue
        t = simulate_trade(path, int(pos[0]))
        if t is not None:
            rows.append({**s._asdict(), **t})
    return pd.DataFrame(rows)


def _core(t: pd.DataFrame) -> dict:
    s = t["ret"]
    w, l = s[s > 0], s[s <= 0]
    return {
        "n": len(s),
        "mean_ret": s.mean() if len(s) else np.nan,
        "mean_r": t["r_multiple"].mean() if len(s) else np.nan,
        "win_rate": (s > 0).mean() if len(s) else np.nan,
        "payoff": w.mean() / -l.mean() if len(w) and len(l) else np.nan,
        "pf": w.sum() / -l.sum() if len(l) and l.sum() else np.nan,
    }


def report(trades: pd.DataFrame, split_date: str) -> dict:
    """§11 報告：總表＋集中度＋最差 10%＋最多連虧＋樣本內外＋按月＋分型態。持有中的交易不計。"""
    t = trades[trades["exit_reason"] != "持有中"].sort_values("date").reset_index(drop=True)
    out = _core(t)
    s = t["ret"]
    gains = s[s > 0].sort_values(ascending=False)
    k = max(1, int(np.ceil(len(s) * 0.05)))
    out["top5_share"] = gains.head(k).sum() / gains.sum() if gains.sum() else np.nan
    per_day = t.groupby("date")["ret"].sum()
    out["days"] = len(per_day)
    out["max_day_share"] = per_day.abs().max() / per_day.abs().sum() if len(per_day) else np.nan
    top3 = per_day.sort_values(ascending=False).head(3).index
    out["mean_ex_top3_days"] = t.loc[~t["date"].isin(top3), "ret"].mean()
    out["worst10_mean"] = s.sort_values().head(max(1, int(np.ceil(len(s) * 0.10)))).mean()
    streak = best = 0
    for v in (s <= 0):
        streak = streak + 1 if v else 0
        best = max(best, streak)
    out["max_consec_losses"] = best
    split = pd.Timestamp(split_date)
    out["in_sample"] = _core(t[t["date"] < split])
    out["out_sample"] = _core(t[t["date"] >= split])
    out["by_month"] = pd.DataFrame([{"month": str(m), **_core(g)} for m, g in t.groupby(t["date"].dt.to_period("M"))])
    out["by_type"] = pd.DataFrame([{"type": k_, **_core(g)} for k_, g in t.groupby("type")])
    return out


def winner_episodes(features: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """飆股段：起漲後 30 日內最高收盤 ≥ 起漲收盤 ×2；同股 40 個交易日內只留漲幅最大的一段。"""
    rows = []
    for sid, g in features.groupby("stock_id", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        fwd = g["close"][::-1].rolling(WIN_HORIZON, min_periods=1).max()[::-1].shift(-1) / g["close"] - 1
        cand = g.index[(fwd >= WIN_GAIN) & g["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
        taken = []
        for i in sorted(cand, key=lambda i: -fwd[i]):
            if all(abs(i - t) >= WIN_DEDUP for t in taken):
                taken.append(i)
                rows.append({"stock_id": sid, "start_date": g.at[i, "date"], "gain": fwd[i]})
    return pd.DataFrame(rows, columns=["stock_id", "start_date", "gain"])


def catch_rate(episodes: pd.DataFrame, signals: pd.DataFrame, features: pd.DataFrame) -> float:
    """飆股段中，起漲日 −5～+15 個交易日內有訊號的比例。"""
    if episodes.empty:
        return np.nan
    dates = {sid: g["date"].sort_values().reset_index(drop=True) for sid, g in features.groupby("stock_id")}
    sig = signals.groupby("stock_id")["date"].apply(set).to_dict()
    hits = 0
    for e in episodes.itertuples(index=False):
        d = dates[e.stock_id]
        i = int(d.searchsorted(e.start_date))
        window = set(d.iloc[max(0, i - CATCH_BEFORE): i + CATCH_AFTER + 1])
        hits += bool(window & sig.get(e.stock_id, set()))
    return hits / len(episodes)


def blowup_rate(signals: pd.DataFrame, features: pd.DataFrame, exclude_dates=()) -> float:
    """訊號後隔天開盤進、第 20 個交易日收盤出（扣成本）≤ −15% 的比例。
    口徑跟 run_trades 一致：排除 exclude_dates 的訊號，隔天一字漲停買不到的不算。"""
    excl = set(pd.to_datetime(list(exclude_dates)))
    f = features[["stock_id", "date", "open", "close", "one_word"]].sort_values(["stock_id", "date"]).reset_index(drop=True)
    g = f.groupby("stock_id", sort=False)
    entry = g["open"].shift(-1)
    exit_ = g["close"].shift(-BLOWUP_DAYS)
    f["a20"] = exit_ * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1
    f.loc[g["one_word"].shift(-1, fill_value=False).astype(bool), "a20"] = np.nan
    sig = signals[~signals["date"].isin(excl)]
    m = sig.merge(f[["stock_id", "date", "a20"]], on=["stock_id", "date"], how="left").dropna(subset=["a20"])
    return (m["a20"] <= BLOWUP_RET).mean() if len(m) else np.nan


def case_hits(signals: pd.DataFrame) -> dict:
    keys = set(zip(signals["stock_id"], pd.to_datetime(signals["date"]).dt.strftime("%Y-%m-%d")))
    return {c: c in keys for c in CASES}
