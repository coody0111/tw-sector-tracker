"""推薦頁「近 21 天最強」（規格 §10.1）：個股前 20、族群前 10，標拉回中／整理中／上攻中。
回測（13.13）：前 20 名裡「拉回中」（離 21 日高點 ≤ −10%）之後 20 日平均 +7.9%，最好；「整理中」只有 +1.8%
（原本假設它在醞釀下一段，不成立）。頁面改把重點標在拉回中（2026-10-26 Cody）。"""
import pandas as pd

WINDOW = 21                 # 近 21 個交易日
TOP_STOCKS, TOP_SECTORS = 20, 10
MIN_MEMBERS = 5             # 族群至少 5 檔有流動性的成員才排（2026-10-27 Cody：成交值 1 億池變小，3 檔族群易被單一股票拉動）
DAILY_CLIP = 0.11           # 族群指數單日報酬上限：擋掉上市除權／減資日的假漲跌（bug-reports 2026-10-26 🟡1）
STOCK_RULE = {"rng5": 0.08, "pullback": -0.10}    # 整理中：5 日區間 ≤ 8%、量縮；拉回中：離高點 ≤ −10%
SECTOR_RULE = {"rng5": 0.05, "pullback": -0.08}   # 族群：5 日區間 ≤ 5%；拉回中：離高點 ≤ −8%


def _status(from_high: float, rng5: float, rule: dict, vol_shrink: bool = True) -> str:
    if from_high <= rule["pullback"]:
        return "拉回中"
    if rng5 <= rule["rng5"] and vol_shrink:
        return "整理中"
    return "上攻中"


def _pct(x: float) -> float:
    return round(float(x) * 100, 1)


def _window(features: pd.DataFrame, day: pd.Timestamp) -> tuple:
    """day 之前（含）最後 WINDOW+1 個交易日，只留當天有流動性、整段都有資料的股票。"""
    days = sorted(features.loc[features["date"] <= day, "date"].unique())[-(WINDOW + 1):]
    if len(days) < WINDOW + 1:
        return None, None
    w = features[features["date"].isin(days)]
    liquid = set(w.loc[(w["date"] == days[-1]) & w["liq"].fillna(False).astype(bool), "stock_id"])
    full = w.groupby("stock_id")["date"].count()
    keep = liquid & set(full[full == len(days)].index)
    return w[w["stock_id"].isin(keep)].sort_values(["stock_id", "date"]), days


def _stock_rows(w: pd.DataFrame) -> list:
    rows = []
    for sid, s in w.groupby("stock_id", sort=False):
        c, v = s["close"].to_numpy(), s["volume"].to_numpy()
        last5, vol20 = c[-5:], v[-20:].mean()
        from_high = c[-1] / c[-WINDOW:].max() - 1
        rng5 = last5.max() / last5.min() - 1
        vr = v[-5:].mean() / vol20 if vol20 > 0 else None
        rows.append({
            "stock_id": sid, "stock_name": s["stock_name"].iloc[-1], "meta_sector": s["meta_sector"].iloc[-1],
            "ret21": _pct(c[-1] / c[0] - 1), "from_high": _pct(from_high), "rng5": _pct(rng5),
            "vr5_20": None if vr is None else round(float(vr), 2),
            "status": _status(from_high, rng5, STOCK_RULE, vr is not None and vr < 1),
        })
    return rows


def _sector_rows(w: pd.DataFrame) -> list:
    """族群指數＝成員等權平均的日報酬（單日 ±11% 截斷）連乘。"""
    closes = w.pivot(index="date", columns="stock_id", values="close").sort_index()
    rets = closes.pct_change().iloc[1:].clip(-DAILY_CLIP, DAILY_CLIP)
    sectors = w.drop_duplicates("stock_id").set_index("stock_id")["meta_sector"]
    rows = []
    for sector, members in sectors.groupby(sectors):
        if not sector or len(members) < MIN_MEMBERS:
            continue
        idx = (1 + rets[members.index].mean(axis=1)).cumprod()
        idx = pd.concat([pd.Series([1.0]), idx.reset_index(drop=True)]).to_numpy()
        from_high = idx[-1] / idx[-WINDOW:].max() - 1
        rng5 = idx[-5:].max() / idx[-5:].min() - 1
        rows.append({"sector": sector, "n": int(len(members)), "ret21": _pct(idx[-1] - 1),
                     "from_high": _pct(from_high), "rng5": _pct(rng5),
                     "status": _status(from_high, rng5, SECTOR_RULE)})
    return rows


def _top(rows: list, n: int) -> list:
    ranked = sorted(rows, key=lambda r: -r["ret21"])[:n]
    return [{"rank": i + 1, **r} for i, r in enumerate(ranked)]


_MEMBER_KEYS = ("stock_id", "stock_name", "ret21", "from_high", "rng5", "status")


def _attach_members(sectors: list, stock_rows: list) -> list:
    """每個族群附上成員個股依 21 日漲幅排行（推薦頁點族群展開用；2026-10-27 Cody：「族群前 10 點進去要有那些個股排行」）。"""
    by_sector: dict = {}
    for r in sorted(stock_rows, key=lambda r: -r["ret21"]):
        by_sector.setdefault(r["meta_sector"], []).append({k: r[k] for k in _MEMBER_KEYS})
    return [{**s, "members": [{"rank": i + 1, **m} for i, m in enumerate(by_sector.get(s["sector"], []))]}
            for s in sectors]


def leaders(features: pd.DataFrame, day) -> dict:
    """{"stocks": 前 20, "sectors": 前 10（各附 members 成員排行）}；資料不足 22 個交易日時兩邊都是空的。"""
    w, _ = _window(features, pd.Timestamp(day))
    if w is None or w.empty:
        return {"stocks": [], "sectors": []}
    stock_rows = _stock_rows(w)
    return {"stocks": _top(stock_rows, TOP_STOCKS),
            "sectors": _attach_members(_top(_sector_rows(w), TOP_SECTORS), stock_rows)}
