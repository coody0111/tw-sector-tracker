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

_PRICE_LOOKBACK_DAYS = 11  # 涵蓋cum3(3天)、streak(視資料而定)、量能參與(今日+5天)所需的查詢窗口
_RS_WEIGHT = 0.30
_BREADTH_WEIGHT = 0.25
_CONTINUATION_WEIGHT = 0.20
_VOLUME_WEIGHT = 0.15
_CHIPS_WEIGHT = 0.10
_CONTINUATION_CAP_DAYS = 5  # 延續性因子封頂天數：連漲5天(以上)=滿分


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


def _calc_chips_factor(
    universe_df: pd.DataFrame,
    inst_df: pd.DataFrame,
    margin_df: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    """
    計算「觀察分」5因子中的籌碼確認因子原始值：chips_raw（外資買超檔數比例）、
    partial_coverage（跨交易所資料涵蓋是否不全）。

    獨立重寫版本的跨交易所涵蓋度判斷邏輯，刻意不呼叫 calc_meta_chips_signals()
    （見設計 spec §2 的取捨說明——效能與隔離性換維護成本）。

    inst_df 需含 stock_id/date/foreign_net，呼叫端只傳 institutional 表最新一天的資料。
    margin_df 需含 stock_id/date，呼叫端只傳 margin 表**自己**最新一天的資料（margin
    跟 institutional 發布日可能不同步，不能共用同一個 today）。
    universe_df 需含 stock_id/meta_sector/exchange。

    Returns
    -------
    {meta_name: {
        "chips_raw": float | None,
        "partial_coverage": bool,
    }}
    """
    universe = universe_df[["stock_id", "meta_sector", "exchange"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)

    meta_all_exchanges: Dict[str, set] = {
        name: set(grp.dropna().unique())
        for name, grp in universe.groupby("meta_sector")["exchange"]
    }
    meta_stock_count_by_exchange = universe.groupby(["meta_sector", "exchange"])["stock_id"].count()
    all_metas = set(universe["meta_sector"].dropna().unique())

    inst = inst_df.copy()
    inst["stock_id"] = inst["stock_id"].astype(str)
    inst_merged = inst.merge(universe, on="stock_id", how="inner")
    inst_merged = inst_merged.dropna(subset=["foreign_net", "meta_sector"])
    # 防呆：即使呼叫端不小心傳了超過一天的資料進來，也只用最新一天，避免chips_raw
    # 悄悄超過1.0（呼應calc_meta_chips_signals()裡all_dates[-1]的自我修正做法）。
    if not inst_merged.empty:
        inst_merged = inst_merged[inst_merged["date"] == inst_merged["date"].max()]

    margin = margin_df.copy()
    margin["stock_id"] = margin["stock_id"].astype(str)
    margin_merged = margin.merge(universe, on="stock_id", how="inner")
    if not margin_merged.empty:
        margin_merged = margin_merged[margin_merged["date"] == margin_merged["date"].max()]
    margin_covered_by_meta: Dict[str, set] = {
        name: set(grp["exchange"].dropna().unique())
        for name, grp in margin_merged.groupby("meta_sector")
    }

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        meta_inst = inst_merged[inst_merged["meta_sector"] == meta_name]
        covered_exchanges = meta_inst["exchange"].dropna().unique().tolist()

        if covered_exchanges and meta_name in meta_stock_count_by_exchange.index.get_level_values(0):
            total_stocks = int(
                meta_stock_count_by_exchange.loc[meta_name]
                .reindex(covered_exchanges).fillna(0).sum()
            )
        else:
            total_stocks = 0

        buy_count = int((meta_inst["foreign_net"] > 0).sum())
        # chips_raw是None（不是0）代表「完全沒資料，不知道」；跟calc_meta_chips_signals()的
        # foreign_buy_ratio在同樣情況回0不同——這裡刻意選None，讓Task3能正確排除這個因子
        # 不計入reweight，而不是誤判成「這族群外資0%買超」。
        chips_raw = round(buy_count / total_stocks, 4) if total_stocks > 0 else None

        expected_exchanges = meta_all_exchanges.get(meta_name, set())
        inst_partial = bool(expected_exchanges - set(covered_exchanges))
        margin_partial = bool(expected_exchanges - margin_covered_by_meta.get(meta_name, set()))
        partial_coverage = inst_partial or margin_partial

        results[meta_name] = {"chips_raw": chips_raw, "partial_coverage": partial_coverage}

    return results


def calc_meta_observation_scores(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Any]]:
    """
    首頁與逆轟頁共用的「觀察分」，決定族群優先展開順序（非最終買賣動作）。

    完全獨立實作：不呼叫 processors/performance.py 的 calc_cumulative_meta()/
    calc_universe_performance()/calc_meta_signals()/calc_meta_chips_signals()，
    單一 DuckDB 連線查完 daily_prices/institutional/margin 後在記憶體算完。刻意的
    設計決定，換取效能（不用開4次連線）與跟既有4支函式的完全隔離；代價是
    partial_coverage 等邏輯與 calc_meta_chips_signals() 重複一份，兩邊之後各自
    修正不會自動同步，見設計 spec §2。

    Returns
    -------
    {meta_name: {
        "observation_score": float | None,  # 0~100，5因子全不可用時 None
        "score_coverage": float,            # 0~1，實際可用權重比例
        "rs_raw": float | None,             # cum3差值（%），供UI顯示原始值，非0~1
        "breadth_raw": float | None,        # 今日上漲比例（0~1，本身就是最終用於加權的值）
        "continuation_raw": int | None,     # streak天數（原始整數，未封頂，供UI顯示）
        "volume_raw": float | None,         # 集合量比（原始值，非0~1）
        "chips_raw": float | None,          # foreign_buy_ratio（0~1，本身就是最終用於加權的值）
        "partial_coverage": bool,           # 籌碼資料是否涵蓋不全（chips_raw為None時的可能原因）
    }}
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        price_dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {_PRICE_LOOKBACK_DAYS}"
        ).fetchdf()
        if price_dates_df.empty:
            return {}
        min_price_date = price_dates_df["date"].min()
        price_df = con.execute(
            "SELECT stock_id, date, change_pct, volume FROM daily_prices WHERE date >= ?",
            [min_price_date],
        ).fetchdf()

        inst_latest = con.execute("SELECT MAX(date) FROM institutional").fetchone()[0]
        if inst_latest is not None:
            inst_df = con.execute(
                "SELECT stock_id, date, foreign_net FROM institutional WHERE date = ?",
                [inst_latest],
            ).fetchdf()
        else:
            inst_df = pd.DataFrame(columns=["stock_id", "date", "foreign_net"])

        margin_latest = con.execute("SELECT MAX(date) FROM margin").fetchone()[0]
        if margin_latest is not None:
            margin_df = con.execute(
                "SELECT stock_id, date FROM margin WHERE date = ?",
                [margin_latest],
            ).fetchdf()
        else:
            margin_df = pd.DataFrame(columns=["stock_id", "date"])
    finally:
        con.close()

    price_factors = _calc_price_based_factors(universe_df, price_df)
    chips_factors = _calc_chips_factor(universe_df, inst_df, margin_df)

    all_metas = set(universe_df["meta_sector"].dropna().unique()) | set(price_factors.keys())
    if not all_metas:
        return {}

    rs_series = pd.Series(
        {m: price_factors.get(m, {}).get("rs_raw") for m in all_metas}, dtype="float64"
    )
    volume_series = pd.Series(
        {m: price_factors.get(m, {}).get("volume_raw") for m in all_metas}, dtype="float64"
    )
    rs_rank = rs_series.rank(pct=True, ascending=True)
    volume_rank = volume_series.rank(pct=True, ascending=True)

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in all_metas:
        pf = price_factors.get(meta_name, {})
        cf = chips_factors.get(meta_name, {"chips_raw": None, "partial_coverage": False})

        rs_raw = pf.get("rs_raw")
        breadth_raw = pf.get("breadth_raw")
        continuation_raw = pf.get("continuation_raw")
        volume_raw = pf.get("volume_raw")
        chips_raw = cf.get("chips_raw")
        partial_coverage = bool(cf.get("partial_coverage", False))

        weighted_sum = 0.0
        coverage = 0.0

        if rs_raw is not None and pd.notna(rs_rank.get(meta_name)):
            weighted_sum += _RS_WEIGHT * float(rs_rank[meta_name])
            coverage += _RS_WEIGHT
        if breadth_raw is not None:
            weighted_sum += _BREADTH_WEIGHT * breadth_raw
            coverage += _BREADTH_WEIGHT
        if continuation_raw is not None:
            continuation_score = (
                min(max(continuation_raw, 0), _CONTINUATION_CAP_DAYS) / _CONTINUATION_CAP_DAYS
            )
            weighted_sum += _CONTINUATION_WEIGHT * continuation_score
            coverage += _CONTINUATION_WEIGHT
        if volume_raw is not None and pd.notna(volume_rank.get(meta_name)):
            weighted_sum += _VOLUME_WEIGHT * float(volume_rank[meta_name])
            coverage += _VOLUME_WEIGHT
        if chips_raw is not None and not partial_coverage:
            weighted_sum += _CHIPS_WEIGHT * chips_raw
            coverage += _CHIPS_WEIGHT

        observation_score = round(100 * weighted_sum / coverage, 1) if coverage > 0 else None

        results[meta_name] = {
            "observation_score": observation_score,
            "score_coverage": round(coverage, 2),
            "rs_raw": rs_raw,
            "breadth_raw": breadth_raw,
            "continuation_raw": continuation_raw,
            "volume_raw": volume_raw,
            "chips_raw": chips_raw,
            "partial_coverage": partial_coverage,
        }

    return results
