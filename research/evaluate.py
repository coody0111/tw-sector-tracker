"""因子評估：RankIC、IC IR、命中率、分位多空、族群聚合、樣本外切分。"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_XS = 5  # 當日橫截面至少要這麼多檔才算，否則該日不計


def _align_valid(factor: pd.DataFrame, fwd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """對齊索引/欄位，並把任一邊為 NaN 的格子都設成 NaN。"""
    f, r = factor.align(fwd, join="inner", axis=None)
    both = f.notna() & r.notna()
    return f.where(both), r.where(both)


def rank_ic(factor: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """每日 RankIC（Spearman）= 因子橫截面排名 vs 未來報酬排名的相關。

    以「排名後的 Pearson 相關」實作，等價於 Spearman，且不需要 scipy。
    """
    f, r = _align_valid(factor, fwd)
    rf = f.rank(axis=1)
    rr = r.rank(axis=1)

    n = rf.notna().sum(axis=1)
    # 逐列去均值後的 Pearson
    cf = rf.sub(rf.mean(axis=1), axis=0)
    cr = rr.sub(rr.mean(axis=1), axis=0)
    cov = (cf * cr).sum(axis=1)
    denom = np.sqrt((cf**2).sum(axis=1) * (cr**2).sum(axis=1))

    ic = cov / denom.replace(0, np.nan)
    return ic.where(n >= MIN_XS)


def quantile_spread(factor: pd.DataFrame, fwd: pd.DataFrame, q: int = 5) -> float:
    """分位多空價差：最高分組 vs 最低分組的未來平均報酬差（對全期取平均）。"""
    f, r = _align_valid(factor, fwd)
    pct = f.rank(axis=1, pct=True)
    valid = f.notna().sum(axis=1) >= max(MIN_XS, q)

    top = r.where(pct > 1 - 1 / q).mean(axis=1)
    bot = r.where(pct <= 1 / q).mean(axis=1)
    return float((top - bot).where(valid).mean())


def to_sector(
    factor: pd.DataFrame, fwd: pd.DataFrame, smap: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """個股層聚合成族群層。

    族群因子 = 成員**中位數**（對離群值穩健）
    族群報酬 = 成員**等權平均**（＝實際等權買進該族群的報酬）
    """
    cols = [c for c in factor.columns if c in smap.index]
    groups = smap.reindex(cols)
    sec_f = factor[cols].T.groupby(groups).median().T
    sec_r = fwd[cols].T.groupby(groups).mean().T
    return sec_f.sort_index(axis=1), sec_r.sort_index(axis=1)


def summarize(ic: pd.Series, spread: float) -> dict:
    ic = ic.dropna()
    if ic.empty:
        return dict(mean_ic=np.nan, ic_ir=np.nan, hit_rate=np.nan, spread=spread, n_days=0)
    mean, sd = ic.mean(), ic.std()
    return dict(
        mean_ic=float(mean),
        ic_ir=float(mean / sd) if sd and not np.isclose(sd, 0) else np.nan,
        hit_rate=float((ic > 0).mean()),
        spread=spread,
        n_days=int(ic.size),
    )


def evaluate_factor(
    name: str,
    factor: pd.DataFrame,
    fwds: dict[int, pd.DataFrame],
    smap: pd.Series,
    split: pd.Timestamp,
) -> list[dict]:
    """一個因子 × {個股,族群} × 各天期 × {樣本內,樣本外} 的所有列。"""
    rows = []
    for h, fwd in fwds.items():
        layers = {"stock": (factor, fwd)}
        layers["sector"] = to_sector(factor, fwd, smap)

        for layer, (f, r) in layers.items():
            periods = {
                "in_sample": (f[f.index < split], r[r.index < split]),
                "out_sample": (f[f.index >= split], r[r.index >= split]),
                "full": (f, r),
            }
            for period, (fp, rp) in periods.items():
                if fp.empty:
                    continue
                stats = summarize(rank_ic(fp, rp), quantile_spread(fp, rp))
                rows.append(
                    dict(factor=name, layer=layer, horizon=h, period=period, **stats)
                )
    return rows
