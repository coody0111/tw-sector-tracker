import pandas as pd
from typing import List, Dict, Any
from config import META_SECTORS, get_meta_sector


def calc_sector_performance(
    sectors_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> List[Dict[str, Any]]:
    sectors = sectors_df.copy()
    prices = prices_df.copy()
    sectors["stock_id"] = sectors["stock_id"].astype(str)
    prices["stock_id"] = prices["stock_id"].astype(str)

    merged = sectors.merge(
        prices[["stock_id", "change_pct"]],
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


def calc_meta_performance(
    perf_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    把小族群績效合併成主族群績效。
    回傳：meta_name, sub_names(list), avg_change_pct, up_count, down_count, flat_count
    """
    # 把有主族群的小族群收集起來；沒有對應主族群的，自己單獨成一組（不丟棄）
    meta_groups: Dict[str, List[Dict]] = {k: [] for k in META_SECTORS}

    for row in perf_list:
        meta = get_meta_sector(row["sector_name"]) or row["sector_name"]
        meta_groups.setdefault(meta, []).append(row)

    results = []
    for meta_name, sub_rows in meta_groups.items():
        if not sub_rows:
            continue
        total_up = sum(r["up_count"] for r in sub_rows)
        total_down = sum(r["down_count"] for r in sub_rows)
        total_flat = sum(r["flat_count"] for r in sub_rows)
        total_stocks = total_up + total_down + total_flat
        if total_stocks == 0:
            continue

        # 加權平均（依股票數量）
        weighted_pct = sum(
            r["avg_change_pct"] * (r["up_count"] + r["down_count"] + r["flat_count"])
            for r in sub_rows
        ) / total_stocks

        results.append({
            "meta_name":     meta_name,
            "sub_names":     [r["sector_name"] for r in sub_rows],
            "avg_change_pct": round(weighted_pct, 2),
            "up_count":      total_up,
            "down_count":    total_down,
            "flat_count":    total_flat,
        })

    return sorted(results, key=lambda r: r["avg_change_pct"], reverse=True)
