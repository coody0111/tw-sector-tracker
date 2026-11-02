"""推薦頁「一字鎖」（2026-11-02 Cody）：近 10 個交易日開高低收同價的漲停（features 的 one_word）。
只列出來給你看，不是策略訊號、沒有回測，也不過濾流動性；頁面顯示量和 20 日均成交值，自己判斷買不買得到。"""
import pandas as pd

WINDOW = 10            # 近 10 個交易日
TURNOVER_DAYS = 20     # 20 日均成交值
ALERT = "一字鎖"       # 訊號卡片：推薦日或今天一字鎖就標


def locked_keys(features: pd.DataFrame, day: pd.Timestamp, window: int = WINDOW) -> set:
    """{(stock_id, 日期 ISO)}：近 window 個交易日的一字鎖。"""
    days = sorted(features.loc[features["date"] <= day, "date"].unique())[-window:]
    hit = features[features["date"].isin(days) & features["one_word"].fillna(False).astype(bool)]
    return {(s, pd.Timestamp(d).date().isoformat()) for s, d in zip(hit["stock_id"], hit["date"])}


def _streak(positions: list) -> int:
    """最後一次一字鎖往回數，連續幾個交易日都是一字鎖。"""
    n = 1
    for a, b in zip(positions[-2::-1], positions[:0:-1]):
        if b - a != 1:
            break
        n += 1
    return n


def one_word_list(features: pd.DataFrame, day: pd.Timestamp, window: int = WINDOW) -> list:
    """每檔一列：次數、連續天數、最後一次日期、當天量（張）、今天收盤、20 日均成交值（億）。
    排序：最後一次越近越前，同一天連續天數多、次數多的在前。"""
    day = pd.Timestamp(day)
    all_days = sorted(features.loc[features["date"] <= day, "date"].unique())
    days = all_days[-window:]
    pos = {pd.Timestamp(d): i for i, d in enumerate(days)}
    w = features[features["date"].isin(days)]
    hit = w[w["one_word"].fillna(False).astype(bool)].sort_values(["stock_id", "date"])
    if hit.empty:
        return []
    recent = features[features["date"].isin(all_days[-TURNOVER_DAYS:]) & features["stock_id"].isin(set(hit["stock_id"]))]
    turnover = (recent["volume"] * 1000 * recent["close"]).groupby(recent["stock_id"]).mean()
    last_close = recent.sort_values("date").groupby("stock_id")["close"].last()
    rows = []
    for sid, g in hit.groupby("stock_id"):
        last = g.iloc[-1]
        rows.append({
            "stock_id": sid, "stock_name": last["stock_name"], "meta_sector": last["meta_sector"],
            "count": len(g), "streak": _streak([pos[pd.Timestamp(d)] for d in g["date"]]),
            "last_date": pd.Timestamp(last["date"]).date().isoformat(), "today": pd.Timestamp(last["date"]) == day,
            "volume": int(last["volume"]), "close": float(last_close[sid]),
            "turnover20": round(float(turnover[sid]) / 1e8, 2),
        })
    rows.sort(key=lambda r: (r["last_date"], r["streak"], r["count"]), reverse=True)
    return rows
