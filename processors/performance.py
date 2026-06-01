import pandas as pd
from typing import List, Dict, Any


def calc_sector_performance(
    sectors_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> List[Dict[str, Any]]:
    merged = sectors_df.merge(
        prices_df[["stock_id", "change_pct"]],
        on="stock_id",
        how="left",
    )

    results = []
    for (sector_type, sector_name), group in merged.groupby(["sector_type", "sector_name"]):
        valid = group["change_pct"].dropna()
        if valid.empty:
            continue
        results.append({
            "sector_type": sector_type,
            "sector_name": sector_name,
            "avg_change_pct": round(valid.mean(), 2),
            "up_count": int((valid > 0).sum()),
            "down_count": int((valid < 0).sum()),
            "flat_count": int((valid == 0).sum()),
        })

    return sorted(results, key=lambda r: r["avg_change_pct"], reverse=True)
