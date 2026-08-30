"""因子健檢台 CLI：跑 RankIC 總表。

用法：
    python -m research.run_factor_eval
    python -m research.run_factor_eval --end 2026-08-06 --out research/output
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from research import evaluate as ev
from research import factor_data as fd
from research import factors as fx

HORIZONS = (1, 5, 10, 20)


def build_rows(panel, smap, split, names) -> pd.DataFrame:
    fwds = fd.forward_returns(panel, HORIZONS)
    rows: list[dict] = []
    for name in names:
        rows += ev.evaluate_factor(name, fx.FACTORS[name](panel), fwds, smap, split)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="因子健檢台")
    ap.add_argument("--start", default=fd.DEFAULT_START)
    ap.add_argument("--end", default=fd.DEFAULT_END)
    ap.add_argument("--out", default="research/output")
    args = ap.parse_args()

    panel = fd.load_price_panel(start=args.start, end=args.end)
    smap = fd.sector_map()
    days = fd.trading_days(panel)
    split = fd.split_date(panel)

    header = (
        f"資料期間 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}"
        f"（{len(days)} 交易日、{panel['close'].shape[1]} 檔、{smap.nunique()} 族群）\n"
        f"樣本外切分點 {split:%Y-%m-%d}"
        f"（樣本內 {(days < split).sum()} 日 / 樣本外 {(days >= split).sum()} 日）\n"
        "⚠️ 僅約 1.7 年日線、又逢台股 AI 大多頭 → 結論屬「初步、指示性」，非鐵證。"
    )
    print(header, "\n")

    cov = fd.field_coverage(panel)
    print("欄位覆蓋率：" + "、".join(f"{k} {v:.1%}" for k, v in cov.items()))
    usable, skipped = fd.usable_factors(panel, fx.REQUIRES)
    for name, why in skipped.items():
        print(f"  ⚠️ 跳過 {name}：{why}")
    print()

    df = build_rows(panel, smap, split, usable)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv = out_dir / f"factor_eval_{date.today():%Y%m%d}.csv"
    df.to_csv(csv, index=False, encoding="utf-8-sig")

    show = (
        df[(df.horizon == 10) & (df.period != "full")]
        .pivot_table(index=["factor", "layer"], columns="period", values="mean_ic")
        .sort_values("out_sample", ascending=False)
    )
    print("預測未來 10 日的平均 RankIC：")
    print(show.round(4).to_string())
    print(f"\n完整總表 -> {csv}  （{len(df)} 列）")


if __name__ == "__main__":
    main()
