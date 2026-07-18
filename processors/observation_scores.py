"""
族群「觀察分」計算——決定族群優先展開順序，供首頁與逆轟策略頁共用。

設計 spec：docs/superpowers/specs/2026-07-17-meta-observation-scores-design.md

刻意的設計決定：這個模組完全獨立，不呼叫 processors/performance.py 裡任何既有函式
（calc_cumulative_meta/calc_universe_performance/calc_meta_signals/calc_meta_chips_signals），
單一 DuckDB 連線查完 daily_prices/institutional/margin，記憶體裡算完5因子。換取效能（不用開4次
連線）與跟既有4支函式的完全隔離；代價是 partial_coverage 等邏輯與 calc_meta_chips_signals()
重複一份，兩邊之後各自修正不會自動同步（見設計 spec §2）。
"""
from typing import Any, Dict, Optional

import duckdb
import pandas as pd

from streak_utils import calc_streak as _streak


def _calc_price_based_factors(
    universe_df: pd.DataFrame,
    price_df: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    """
    計算「觀察分」5因子中，來自 daily_prices 的4個因子原始值：
    rs_raw（相對強度，族群cum3 - universe cum3）、breadth_raw（今日上漲比例）、
    continuation_raw（連漲天數，原始未封頂）、volume_raw（集合量比）。

    price_df 需含欄位 stock_id/date/change_pct/volume，呼叫端負責只傳入
    最近N個交易日（這支函式不做日期過濾，用 price_df 裡實際出現的所有日期）。
    universe_df 需含 stock_id/meta_sector。

    Returns
    -------
    {meta_name: {
        "rs_raw": float | None,
        "breadth_raw": float | None,
        "continuation_raw": int | None,
        "volume_raw": float | None,
    }}
    """
    if price_df.empty:
        return {}

    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices = price_df.copy()
    prices["stock_id"] = prices["stock_id"].astype(str)

    merged = prices.merge(universe, on="stock_id", how="inner")
    if merged.empty:
        return {}
    all_dates = sorted(merged["date"].unique())
    today = all_dates[-1]
    all_metas = set(merged["meta_sector"].dropna().unique())

    valid_pct = merged.dropna(subset=["change_pct"])
    meta_daily_avg = valid_pct.groupby(["meta_sector", "date"])["change_pct"].mean()
    meta_pivot = meta_daily_avg.unstack(level="date").reindex(columns=all_dates)
    universe_daily_avg = valid_pct.groupby("date")["change_pct"].mean().reindex(all_dates)

    def _cum3(series: pd.Series) -> Optional[float]:
        window_dates = all_dates[-3:]
        if len(window_dates) < 3:
            return None
        values = [series.get(d) for d in window_dates]
        if any(v is None or pd.isna(v) for v in values):
            return None
        factor = 1.0
        for v in values:
            factor *= (1 + float(v) / 100)
        return round((factor - 1) * 100, 2)

    universe_cum3 = _cum3(universe_daily_avg)

    today_valid = valid_pct[valid_pct["date"] == today]
    up_counts = today_valid[today_valid["change_pct"] > 0].groupby("meta_sector").size()
    total_counts = today_valid.groupby("meta_sector").size()

    valid_vol = merged.dropna(subset=["volume"])
    meta_vol_sum = valid_vol.groupby(["meta_sector", "date"])["volume"].sum()
    vol_pivot = meta_vol_sum.unstack(level="date").reindex(columns=all_dates)

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        # 相對強度
        meta_cum3 = _cum3(meta_pivot.loc[meta_name]) if meta_name in meta_pivot.index else None
        rs_raw = (
            round(meta_cum3 - universe_cum3, 2)
            if meta_cum3 is not None and universe_cum3 is not None
            else None
        )

        # 族群廣度
        if meta_name in total_counts.index:
            total = int(total_counts.loc[meta_name])
            up = int(up_counts.get(meta_name, 0))
            breadth_raw = round(up / total, 4) if total > 0 else None
        else:
            breadth_raw = None

        # 延續性（原始streak，未封頂；跳過缺值日，用剩餘有效日照時間順序算，
        # 不強求streak一定要以「今日」為終點——資料不足時流失的只是可能低估天數，不會是None）
        if meta_name in meta_pivot.index:
            meta_series = meta_pivot.loc[meta_name].dropna()
            pct_values = [float(meta_series[d]) for d in all_dates if d in meta_series.index]
            continuation_raw = _streak(pct_values) if pct_values else None
        else:
            continuation_raw = None

        # 成分股量能參與：明確要求「今日」本身有valid volume，避免今日缺值時
        # 誤把「最近一個有量的日子」當成今日、悄悄算出跟今天無關的比值
        if meta_name in vol_pivot.index and pd.notna(vol_pivot.loc[meta_name].get(today)):
            vol_row = vol_pivot.loc[meta_name]
            today_vol = float(vol_row[today])
            prior_dates = [d for d in all_dates[:-1] if d in vol_row.index and pd.notna(vol_row[d])]
            if len(prior_dates) >= 5:
                past_vols = [float(vol_row[d]) for d in prior_dates[-5:]]
                avg_vol = sum(past_vols) / len(past_vols)
                volume_raw = round(today_vol / avg_vol, 2) if avg_vol > 0 else None
            else:
                volume_raw = None
        else:
            volume_raw = None

        results[meta_name] = {
            "rs_raw": rs_raw,
            "breadth_raw": breadth_raw,
            "continuation_raw": continuation_raw,
            "volume_raw": volume_raw,
        }

    return results
