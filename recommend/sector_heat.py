"""族群熱度（規格 docs/superpowers/specs/2026-10-27-sector-heat-report.md）。

熱度分數＝「近 21 日漲幅」與「法人買超占比」當天在所有族群中的百分位平均（0～100）。
依據（bt_sector_heat.py，2025-01～2026-10）：組合 IC 0.127、前 20% 族群之後 20 日 +5.6%（全體 +4.0%）。
大戶週增、外資持股變化只顯示、不計分（族群層級沒有預測力，2026-10-27 Cody 選 A）。
"""
import numpy as np
import pandas as pd

from recommend.features import adjusted
from recommend.leaders import SECTOR_RULE, _status

MIN_MEMBERS = 5          # 同推薦頁族群前 10
DAILY_CLIP = 0.11        # 族群指數單日報酬上限（同 leaders）
COMPARE_DAYS = 5         # 跟 5 個交易日前比升溫／降溫（草案）
TOP_N = 10
LEADERS_PER_SECTOR = 3
REQUIRED = {"foreign_net", "trust_net", "total_shares", "fpct5", "big1w", "liq", "limit_up", "meta_sector"}


def _prepare(features: pd.DataFrame) -> pd.DataFrame:
    """個股層級的欄位：還原日報酬、MA20、5 日法人買超金額、市值。"""
    f = features.sort_values(["stock_id", "date"]).copy()
    f["_ac"] = adjusted(f)
    g = f.groupby("stock_id", sort=False)
    f["_dr"] = g["_ac"].pct_change().clip(-DAILY_CLIP, DAILY_CLIP)
    f["_ma20"] = g["_ac"].transform(lambda s: s.rolling(20).mean())
    net = f["foreign_net"].fillna(0) + f["trust_net"].fillna(0)
    f["_net5"] = net.groupby(f["stock_id"]).transform(lambda s: s.rolling(5).sum())
    f["_mcap"] = f["close"] * f["total_shares"]
    return f


def _wavg(x: pd.Series, w: pd.Series):
    ok = x.notna() & w.notna() & (w > 0)
    return float(np.average(x[ok], weights=w[ok])) if ok.any() else None


def _pct(x) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x) * 100, 2)


def _day_table(f: pd.DataFrame, days: list, i: int) -> pd.DataFrame:
    """days[i] 這天每個族群的指標（成員＝當天有流動性、族群 ≥ 5 檔）。"""
    day = days[i]
    today = f[(f["date"] == day) & f["liq"].fillna(False).astype(bool) & (f["meta_sector"].fillna("") != "")]
    window = f[f["date"].isin(days[max(0, i - 21):i + 1])]
    dr = window.pivot(index="date", columns="stock_id", values="_dr").sort_index()
    rows = []
    for sector, m in today.groupby("meta_sector"):
        if len(m) < MIN_MEMBERS:
            continue
        idx = (1 + dr[m["stock_id"]].iloc[1:].mean(axis=1).fillna(0)).cumprod().to_numpy()
        idx = np.concatenate([[1.0], idx])
        ret5 = idx[-1] / idx[-6] - 1 if len(idx) >= 6 else None
        ret21 = idx[-1] / idx[0] - 1 if len(idx) >= 22 else None
        from_high = idx[-1] / idx[-21:].max() - 1
        rng5 = idx[-5:].max() / idx[-5:].min() - 1
        rows.append({
            "sector": sector, "n": int(len(m)),
            "ret5": ret5, "ret21": ret21,
            "inst_ratio": m["_net5"].mul(m["close"]).sum() / m["_mcap"].sum() * 100 if m["_mcap"].sum() > 0 else None,
            "inst_breadth": float((m["_net5"] > 0).mean()),
            "above_ma20": float((m["_ac"] > m["_ma20"]).mean()),
            "limit_up": int(m["limit_up"].sum()),
            "foreign_chg": _wavg(m["fpct5"], m["_mcap"]),
            "big_chg": _wavg(m["big1w"], m["_mcap"]),
            "status": _status(from_high, rng5, SECTOR_RULE),
        })
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["score"] = (t["ret21"].rank(pct=True) + t["inst_ratio"].rank(pct=True)) / 2 * 100
    t["rank"] = t["score"].rank(ascending=False, method="first").astype(int)
    return t.sort_values("rank").reset_index(drop=True)


def _members(f: pd.DataFrame, day, sector: str) -> list:
    """成員依近 21 日（還原）漲幅排行，給展開與「帶頭 3 檔」。"""
    m = f[(f["meta_sector"] == sector) & f["liq"].fillna(False).astype(bool)]
    out = []
    for sid, s in m[m["date"] <= day].groupby("stock_id"):
        s = s.sort_values("date")
        if s["date"].iloc[-1] != day or len(s) < 22:
            continue
        c = s["_ac"].to_numpy()
        out.append({"stock_id": sid, "stock_name": s["stock_name"].iloc[-1], "close": float(s["close"].iloc[-1]),
                    "ret21": round((c[-1] / c[-22] - 1) * 100, 1), "net5_lots": int(s["_net5"].iloc[-1] // 1000)})
    out.sort(key=lambda r: -r["ret21"])
    return [{"rank": i + 1, **r} for i, r in enumerate(out)]


def sector_heat(features: pd.DataFrame, day) -> dict:
    """{"date", "compare_date", "sectors": 全部族群（含 members）, "top": 前 10, "heating": 剛轉熱, "cooling": 退燒中}。"""
    day = pd.Timestamp(day)
    empty = {"date": day.date().isoformat(), "compare_date": None, "sectors": [], "top": [], "heating": [], "cooling": []}
    if not REQUIRED <= set(features.columns):
        return empty                                   # 沒有籌碼欄位（測試用的精簡資料）
    f = _prepare(features[features["date"] <= day])
    days = sorted(f["date"].unique())
    if len(days) < 22 + COMPARE_DAYS:
        return empty
    now = _day_table(f, days, len(days) - 1)
    before = _day_table(f, days, len(days) - 1 - COMPARE_DAYS)
    prev_rank = dict(zip(before["sector"], before["rank"])) if not before.empty else {}
    sectors = []
    for r in now.to_dict("records"):
        members = _members(f, day, r["sector"])
        sectors.append({
            "sector": r["sector"], "rank": int(r["rank"]), "prev_rank": prev_rank.get(r["sector"]),
            "score": round(float(r["score"]), 1), "n": r["n"],
            "ret5": _pct(r["ret5"]), "ret21": _pct(r["ret21"]),
            "inst_ratio": None if r["inst_ratio"] is None else round(float(r["inst_ratio"]), 2),
            "inst_breadth": _pct(r["inst_breadth"]), "above_ma20": _pct(r["above_ma20"]),
            "limit_up": r["limit_up"],
            "foreign_chg": None if r["foreign_chg"] is None else round(r["foreign_chg"], 2),
            "big_chg": None if r["big_chg"] is None else round(r["big_chg"], 2),
            "status": r["status"], "leaders": members[:LEADERS_PER_SECTOR], "members": members,
        })
    top = [s for s in sectors if s["rank"] <= TOP_N]
    top_now = {s["sector"] for s in top}
    top_before = {s for s, r in prev_rank.items() if r <= TOP_N}
    return {
        "date": day.date().isoformat(), "compare_date": pd.Timestamp(days[-1 - COMPARE_DAYS]).date().isoformat(),
        "sectors": sectors, "top": top,
        "heating": [s for s in top if s["sector"] not in top_before],
        "cooling": [{"sector": s, "prev_rank": r, "rank": next((x["rank"] for x in sectors if x["sector"] == s), None)}
                    for s, r in sorted(prev_rank.items(), key=lambda kv: kv[1]) if r <= TOP_N and s not in top_now],
    }
