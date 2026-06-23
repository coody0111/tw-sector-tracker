import pandas as pd
import duckdb
from typing import List, Dict, Any, Optional
from config import META_SECTORS, get_meta_sector, META_PRIORITY_LIST


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


def calc_universe_performance(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """
    基於 stock_universe.csv（每股只歸一個 META）計算族群績效。
    每支股票不重複計算，徹底解決跨族群重疊問題。

    回傳格式與 calc_meta_performance 相同，額外附 stock_ids 供 HTML 展開卡片用。
    """
    universe = universe_df.copy()
    prices = prices_df.copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices["stock_id"] = prices["stock_id"].astype(str)

    merged = universe.merge(
        prices[["stock_id", "change_pct"]],
        on="stock_id",
        how="left",
    )

    meta_order = [m for m, _ in META_PRIORITY_LIST] + ["其他電子"]

    results = []
    for meta_name, group in merged.groupby("meta_sector"):
        valid = group["change_pct"].dropna()
        if valid.empty:
            continue
        results.append({
            "meta_name":      meta_name,
            "sub_names":      sorted(group["sub_sector"].dropna().unique().tolist()),
            "avg_change_pct": round(valid.mean(), 2),
            "up_count":       int((valid > 0).sum()),
            "down_count":     int((valid < 0).sum()),
            "flat_count":     int((valid == 0).sum()),
            "stock_ids":      group["stock_id"].tolist(),
        })

    results.sort(key=lambda r: (
        meta_order.index(r["meta_name"]) if r["meta_name"] in meta_order else 999
    ))
    return results


def calc_cumulative_meta(universe_df: pd.DataFrame, db_path: str = "data/screener.db") -> List[Dict[str, Any]]:
    """
    從 DuckDB daily_prices 計算各 META 族群最近 3/5/7 交易日累積漲跌幅。
    回傳 list of dict: meta_name, cum3, cum5, cum7
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 8"
        ).fetchdf()
        prices_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices"
        ).fetchdf()
        con.close()
    except Exception:
        return []

    if prices_df.empty or len(dates_df) < 3:
        return []

    all_dates = sorted(dates_df["date"].tolist())
    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    merged = prices_df.merge(universe, on="stock_id", how="inner")
    merged = merged.dropna(subset=["change_pct", "meta_sector"])

    daily_avg = merged.groupby(["meta_sector", "date"])["change_pct"].mean()
    pivot = daily_avg.unstack(level="date").reindex(columns=all_dates).fillna(0)

    results = []
    for meta_name in pivot.index:
        row = pivot.loc[meta_name]

        def _cum(cols, r=row):
            valid = [c for c in cols if c in pivot.columns]
            if not valid:
                return 0.0
            f = 1.0
            for c in valid:
                f *= (1 + r[c] / 100)
            return round((f - 1) * 100, 2)

        results.append({
            "meta_name": meta_name,
            "cum3": _cum(all_dates[-3:]),
            "cum5": _cum(all_dates[-5:]) if len(all_dates) >= 5 else None,
            "cum7": _cum(all_dates[-7:]) if len(all_dates) >= 7 else None,
        })

    return results


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


def calc_meta_signals(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 11,
) -> Dict[str, Dict[str, Any]]:
    """
    從 DuckDB 計算各 META 族群的技術訊號：
    - daily_pct: 近 10 日每日平均漲跌幅 list（舊→新）
    - dates: 對應日期 list（str "M/D"）
    - streak: 正=連漲天數, 負=連跌天數（含今日）
    - vol_ratio: 今日量能 / 近5日均量
    - yesterday_rank: 昨日排名（依昨日 avg_pct）
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {lookback}"
        ).fetchdf()
        prices_df = con.execute(
            "SELECT stock_id, date, change_pct, volume FROM daily_prices"
        ).fetchdf()
        con.close()
    except Exception:
        return {}

    if prices_df.empty or len(dates_df) < 2:
        return {}

    all_dates = sorted(dates_df["date"].tolist())
    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    merged = prices_df.merge(universe, on="stock_id", how="inner")
    merged = merged.dropna(subset=["meta_sector"])

    pct_pivot = (
        merged.dropna(subset=["change_pct"])
        .groupby(["meta_sector", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )

    vol_pivot = (
        merged.dropna(subset=["volume"])
        .groupby(["meta_sector", "date"])["volume"].sum()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )

    if len(all_dates) >= 2:
        yest_col = all_dates[-2]
        yest_pcts = pct_pivot[yest_col].to_dict()
        yest_ranked = sorted(yest_pcts.items(), key=lambda x: -x[1])
        yesterday_rank = {meta: i + 1 for i, (meta, _) in enumerate(yest_ranked)}
    else:
        yesterday_rank = {}

    signals: Dict[str, Dict[str, Any]] = {}
    for meta_name in pct_pivot.index:
        pct_row = pct_pivot.loc[meta_name]
        vol_row = vol_pivot.loc[meta_name] if meta_name in vol_pivot.index else None

        daily_pct = [round(float(pct_row[d]), 2) for d in all_dates]
        date_labels = [f"{d.month}/{d.day}" for d in all_dates]

        streak = 1
        today_dir = 1 if daily_pct[-1] > 0 else (-1 if daily_pct[-1] < 0 else 0)
        if today_dir != 0:
            for p in reversed(daily_pct[:-1]):
                this_dir = 1 if p > 0 else (-1 if p < 0 else 0)
                if this_dir == today_dir:
                    streak += 1
                else:
                    break
        else:
            streak = 0
        streak_signed = streak * today_dir

        vol_ratio: Optional[float] = None
        if vol_row is not None and len(all_dates) >= 6:
            today_vol = float(vol_row[all_dates[-1]])
            past_vols = [float(vol_row[d]) for d in all_dates[-6:-1] if float(vol_row[d]) > 0]
            if past_vols and today_vol > 0:
                avg_vol = sum(past_vols) / len(past_vols)
                if avg_vol > 0:
                    vol_ratio = round(today_vol / avg_vol, 2)

        signals[meta_name] = {
            "daily_pct": daily_pct,
            "dates": date_labels,
            "streak": streak_signed,
            "vol_ratio": vol_ratio,
            "yesterday_rank": yesterday_rank.get(meta_name),
        }

    return signals
