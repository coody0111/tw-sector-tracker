"""突破策略（規格 §7.5）：漲停＋創 90 日高＋籌碼任一路線，分整理型／續攻型。"""
import numpy as np
import pandas as pd

from recommend.strategies.base import SIGNAL_COLUMNS

BOX_MAX = 0.30           # 整理型：前 20 日區間 < 30%
CONT_MAX = 0.70          # 續攻型：區間 30%～70%
CONT_MIN_RUN = 0.20      # 續攻型：前 20 日漲 ≥ 20%
PR_TOP = 0.90
TRUST_DAYS = 6
ROUTES = {
    "法人": lambda f: f["inst5_pr"] >= PR_TOP,
    "外資": lambda f: f["fpct5_pr"] >= PR_TOP,
    "投信": lambda f: f["trust_days10"] >= TRUST_DAYS,
    "大戶": lambda f: f["big1w_pr"] >= PR_TOP,
}


class BreakoutStrategy:
    name = "突破策略"

    def scan(self, features: pd.DataFrame) -> pd.DataFrame:
        f = features
        hits = {k: rule(f).fillna(False).astype(bool) for k, rule in ROUTES.items()}
        n_routes = sum(h.astype(int) for h in hits.values())
        box = f["rng20"] < BOX_MAX
        cont = (f["rng20"] >= BOX_MAX) & (f["rng20"] < CONT_MAX) & (f["ret20_prev"] >= CONT_MIN_RUN)
        # 創新高天數 90（hi90，見 recommend.features；13.9：60～150 日差距屬雜訊）；用還原價比（2026-10-27）
        close = f["aclose"] if "aclose" in f.columns else f["close"]
        ok = f["limit_up"] & (close > f["hi90"]) & f["liq"] & (n_routes >= 1) & (box | cont)
        out = f.loc[ok, ["stock_id", "date"]].copy()
        out["strategy"] = self.name
        out["type"] = np.where(box[ok], "整理", "續攻")
        out["routes"] = [",".join(k for k in ROUTES if hits[k].loc[i]) for i in out.index]
        out["n_routes"] = n_routes[ok].astype(int)
        return out[SIGNAL_COLUMNS].reset_index(drop=True)
