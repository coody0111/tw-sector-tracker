import pandas as pd
from typing import List, Dict, Any


def detect_changes(
    today_df: pd.DataFrame,
    yesterday_df: pd.DataFrame,
    sector_type: str,
    today_date: str,
) -> List[Dict[str, Any]]:
    if yesterday_df.empty or today_df.empty:
        return []

    def key_set(df: pd.DataFrame) -> Dict[str, set]:
        result = {}
        for _, row in df[df["sector_type"] == sector_type].iterrows():
            result.setdefault(row["sector_name"], set()).add(str(row["stock_id"]))
        return result

    today_map = key_set(today_df)
    yesterday_map = key_set(yesterday_df)
    all_sectors = set(today_map) | set(yesterday_map)

    name_lookup = {
        str(row["stock_id"]): row["stock_name"]
        for _, row in today_df.iterrows()
    }

    changes = []
    for sector in all_sectors:
        today_stocks = today_map.get(sector, set())
        yesterday_stocks = yesterday_map.get(sector, set())

        for stock_id in today_stocks - yesterday_stocks:
            changes.append({
                "date": today_date,
                "sector_type": sector_type,
                "sector_name": sector,
                "stock_id": stock_id,
                "stock_name": name_lookup.get(stock_id, ""),
                "action": "added",
            })

        for stock_id in yesterday_stocks - today_stocks:
            changes.append({
                "date": today_date,
                "sector_type": sector_type,
                "sector_name": sector,
                "stock_id": stock_id,
                "stock_name": name_lookup.get(stock_id, ""),
                "action": "removed",
            })

    return changes
