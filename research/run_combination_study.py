"""組合方式研究：過濾器 vs 平均。

回答 quant-notes/factor/combination.md §6 的待驗清單：
  1. 用「切兩半分別算主訊號 RankIC」驗證量比作為過濾器的機制（而不是硬試組合看誰分數高）
  2. 門檻敏感度（30/50/70%），看結論穩不穩
  3. 換手率對照
  4. IC 衰減

用法：python -m research.run_combination_study
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research import evaluate as ev
from research import factor_data as fd
from research import factors as fx

HORIZON = 10


def turnover(score: pd.DataFrame, top: float = 0.2, step: int = 10) -> float:
    """每 step 天換股一次時，前 top 名的平均換手率。"""
    picks = []
    for i in range(0, len(score), step):
        row = score.iloc[i].dropna()
        if row.empty:
            continue
        k = max(1, int(len(row) * top))
        picks.append(set(row.nlargest(k).index))
    if len(picks) < 2:
        return float("nan")
    chg = [1 - len(a & b) / len(a) for a, b in zip(picks, picks[1:]) if a]
    return float(np.mean(chg))


def mean_ic(f: pd.DataFrame, r: pd.DataFrame) -> float:
    return float(ev.rank_ic(f, r).dropna().mean())


def main() -> None:
    panel = fd.load_price_panel()
    smap = fd.sector_map()
    split = fd.split_date(panel)
    fwds = fd.forward_returns(panel, (1, 5, 10, 20))

    mom20 = fx.FACTORS["momentum_20"](panel)
    mom60 = fx.FACTORS["momentum_60"](panel)
    vol = fx.FACTORS["volume_ratio_5over20"](panel)

    days = fd.trading_days(panel)
    print(f"資料 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}｜樣本外切分 {split:%Y-%m-%d}")
    print("以下皆為【族群層】、預測未來 10 日。\n")

    def sector(f, h=HORIZON):
        return ev.to_sector(f, fwds[h], smap)

    def oos(df):
        return df[df.index >= split]

    # --- 1. IC 衰減 ---------------------------------------------------------
    print("=== IC 衰減（樣本外平均 RankIC）===")
    print(f"{'因子':<14}" + "".join(f"{f'{h}日':>10}" for h in (1, 5, 10, 20)))
    for name, f in [("momentum_20", mom20), ("momentum_60", mom60)]:
        cells = []
        for h in (1, 5, 10, 20):
            sf, sr = ev.to_sector(f, fwds[h], smap)
            cells.append(f"{mean_ic(oos(sf), oos(sr)):>10.4f}")
        print(f"{name:<14}" + "".join(cells))

    # --- 2. 機制檢驗：量比高/低兩半，各自算主訊號的 RankIC -------------------
    print("\n=== 機制檢驗：把族群依量比切兩半，分別算「動量」的 RankIC ===")
    print("（若過濾器有道理，動量應在高量組明顯較準；這比硬試組合更能說明機制）")
    sv, _ = sector(vol)
    for name, f in [("momentum_20", mom20), ("momentum_60", mom60)]:
        sf, sr = sector(f)
        v = sv.reindex_like(sf).rank(axis=1, pct=True)
        hi = mean_ic(oos(sf.where(v > 0.5)), oos(sr.where(v > 0.5)))
        lo = mean_ic(oos(sf.where(v <= 0.5)), oos(sr.where(v <= 0.5)))
        print(f"  {name:<14} 高量組 {hi:+.4f}   低量組 {lo:+.4f}   差 {hi - lo:+.4f}")

    # --- 3. 組合方式對照 + 門檻敏感度 + 換手 ---------------------------------
    print("\n=== 組合方式對照（樣本外 RankIC / 換手率，每 10 天換股、前 20%）===")
    for name, f in [("momentum_20", mom20), ("momentum_60", mom60)]:
        sf, sr = sector(f)
        print(f"\n  [{name}]")
        base = mean_ic(oos(sf), oos(sr))
        print(f"    {'純動量（基準）':<26} IC {base:+.4f}   換手 {turnover(oos(sf)):.1%}")

        avg = fx.blend_average(sf, sv.reindex_like(sf), w=0.5)
        print(f"    {'+ 量比 各半平均':<26} IC {mean_ic(oos(avg), oos(sr)):+.4f}"
              f"   換手 {turnover(oos(avg)):.1%}")

        for keep in (0.7, 0.5, 0.3):
            filt = fx.blend_filter(sf, sv.reindex_like(sf), keep_top=keep)
            n_left = filt.notna().sum(axis=1).mean()
            print(f"    {f'× 高量過濾（留前 {keep:.0%}）':<26} IC {mean_ic(oos(filt), oos(sr)):+.4f}"
                  f"   換手 {turnover(oos(filt)):.1%}   平均剩 {n_left:.0f} 族群")


if __name__ == "__main__":
    main()
