import pandas as pd
import duckdb
from pathlib import Path
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
            "cum1": _cum(all_dates[-1:]),
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


def calc_stock_sparklines(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 11,
) -> Dict[str, list]:
    """每支個股近 N 日漲跌幅 list，供 HTML 個股展開 sparkline 使用。"""
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {lookback}"
        ).fetchdf()
        prices_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices"
        ).fetchdf()
        con.close()
    except Exception:
        return {}

    if prices_df.empty or len(dates_df) < 2:
        return {}

    all_dates = sorted(dates_df["date"].tolist())
    stock_ids = set(universe_df["stock_id"].astype(str))
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)
    prices_df = prices_df[prices_df["stock_id"].isin(stock_ids)]

    pivot = (
        prices_df.dropna(subset=["change_pct"])
        .groupby(["stock_id", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )

    return {sid: [round(float(pivot.loc[sid, d]), 2) for d in all_dates] for sid in pivot.index}


def get_margin_divergence(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 10,
    margin_thresh: float = 3.0,
    price_thresh: float = 2.0,
) -> Dict[str, Any]:
    """
    融資增減趨勢 vs 股價背離警示。
    比較最近 lookback 個交易日的融資餘額趨勢與股價趨勢。

    回傳 {
        "bearish": [{stock_id, stock_name, meta_sector, margin_pct, price_pct, days}, ...],
        "bullish": [...],
        "days_used": int,
    }
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_row = con.execute(
            "SELECT DISTINCT date FROM margin ORDER BY date DESC LIMIT ?", [lookback]
        ).fetchdf()
        if dates_row.empty or len(dates_row) < 2:
            con.close()
            return {"bearish": [], "bullish": [], "days_used": 0}

        dates = sorted(dates_row["date"].tolist())
        min_date = dates[0]

        margin_df = con.execute(
            "SELECT stock_id, date, margin_balance FROM margin WHERE date >= ? AND margin_balance > 0",
            [min_date],
        ).fetchdf()
        price_df = con.execute(
            "SELECT stock_id, date, close FROM daily_prices WHERE date >= ? AND close > 0",
            [min_date],
        ).fetchdf()
        con.close()
    except Exception:
        return {"bearish": [], "bullish": [], "days_used": 0}

    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    margin_df["stock_id"] = margin_df["stock_id"].astype(str)
    price_df["stock_id"] = price_df["stock_id"].astype(str)

    margin_pivot = (
        margin_df.groupby(["stock_id", "date"])["margin_balance"].mean()
        .unstack(level="date").reindex(columns=dates)
    )
    price_pivot = (
        price_df.groupby(["stock_id", "date"])["close"].mean()
        .unstack(level="date").reindex(columns=dates)
    )

    bearish, bullish = [], []
    sid_info = universe.set_index("stock_id")

    for sid in margin_pivot.index:
        if sid not in sid_info.index:
            continue
        m_row = margin_pivot.loc[sid].dropna()
        p_row = price_pivot.loc[sid].dropna() if sid in price_pivot.index else pd.Series(dtype=float)
        if len(m_row) < 2 or len(p_row) < 2:
            continue

        common_dates = sorted(set(m_row.index) & set(p_row.index))
        if len(common_dates) < 2:
            continue

        m_start, m_end = float(m_row[common_dates[0]]), float(m_row[common_dates[-1]])
        p_start, p_end = float(p_row[common_dates[0]]), float(p_row[common_dates[-1]])
        if m_start <= 0 or p_start <= 0:
            continue

        margin_pct = (m_end - m_start) / m_start * 100
        price_pct = (p_end - p_start) / p_start * 100
        days = len(common_dates)

        row = {
            "stock_id":   sid,
            "stock_name": sid_info.loc[sid, "stock_name"],
            "meta_sector": sid_info.loc[sid, "meta_sector"],
            "margin_pct": round(margin_pct, 2),
            "price_pct":  round(price_pct, 2),
            "days":       days,
            "close":      round(float(p_end), 2),
            "change_pct": None,  # 期間漲跌已在 price_pct 欄顯示
        }

        if margin_pct >= margin_thresh and price_pct <= -price_thresh:
            bearish.append(row)
        elif margin_pct <= -margin_thresh and price_pct >= price_thresh:
            bullish.append(row)

    bearish.sort(key=lambda x: x["margin_pct"] - x["price_pct"], reverse=True)
    bullish.sort(key=lambda x: x["price_pct"] - x["margin_pct"], reverse=True)

    return {
        "bearish": bearish[:20],
        "bullish": bullish[:20],
        "days_used": len(dates),
    }


def get_stock_chips_ranking(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Any]:
    """
    取個股今日籌碼排行，供 chips.html 使用。
    回傳 {
        "foreign_top_buy":  [{stock_id, stock_name, meta_sector, foreign_net, trust_net}, ...],
        "foreign_top_sell": [...],
        "margin_alerts":    [{..., margin_balance, margin_change, pct}, ...],
        "chips_date":       "YYYY-MM-DD",
    }
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        date_row = con.execute("SELECT MAX(date) AS d FROM institutional").fetchone()
        if not date_row or not date_row[0]:
            con.close()
            return {}
        latest_date = date_row[0]
        inst_df = con.execute(
            "SELECT stock_id, foreign_net, trust_net FROM institutional WHERE date = ?",
            [latest_date],
        ).fetchdf()
        margin_df = con.execute(
            "SELECT stock_id, margin_balance, margin_change FROM margin WHERE date = ?",
            [latest_date],
        ).fetchdf()
        price_df = con.execute(
            "SELECT stock_id, close, change_pct FROM daily_prices WHERE date = ?",
            [latest_date],
        ).fetchdf()
        if price_df.empty:
            latest_price_date = con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
            if latest_price_date:
                price_df = con.execute(
                    "SELECT stock_id, close, change_pct FROM daily_prices WHERE date = ?",
                    [latest_price_date],
                ).fetchdf()
        con.close()
    except Exception:
        return {}

    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)

    if not price_df.empty:
        price_df["stock_id"] = price_df["stock_id"].astype(str)
        price_map: Dict[str, dict] = price_df.set_index("stock_id")[["close", "change_pct"]].to_dict("index")
    else:
        price_map = {}

    import re as _re

    foreign_top_buy: list = []
    foreign_top_sell: list = []
    if not inst_df.empty:
        inst_df["stock_id"] = inst_df["stock_id"].astype(str)
        # inner join: 只顯示 universe 內（有族群）的股票
        merged = inst_df.merge(universe, on="stock_id", how="inner").dropna(subset=["foreign_net"])
        merged = merged[merged["stock_id"].str.match(r'^[1-9]\d{3}$')]
        merged["foreign_net"] = merged["foreign_net"].astype(int)
        merged["trust_net"] = merged["trust_net"].fillna(0).astype(int)
        sorted_df = merged.sort_values("foreign_net", ascending=False)

        def _row(r: pd.Series) -> dict:
            px = price_map.get(r["stock_id"], {})
            return {
                "stock_id":    r["stock_id"],
                "stock_name":  r["stock_name"],
                "meta_sector": r["meta_sector"],
                "foreign_net": int(r["foreign_net"]),
                "trust_net":   int(r["trust_net"]),
                "close":       px.get("close"),
                "change_pct":  px.get("change_pct"),
            }

        foreign_top_buy = [_row(r) for _, r in sorted_df.head(10).iterrows()]
        sell_df = sorted_df[sorted_df["foreign_net"] < 0].tail(10).iloc[::-1]
        foreign_top_sell = [_row(r) for _, r in sell_df.iterrows()]

    margin_alerts: list = []
    if not margin_df.empty:
        margin_df["stock_id"] = margin_df["stock_id"].astype(str)
        # inner join: 只顯示 universe 內（有族群）的股票
        mm = margin_df.merge(universe, on="stock_id", how="inner")
        mm = mm[mm["stock_id"].str.match(r'^[1-9]\d{3}$')]
        mm = mm.dropna(subset=["margin_balance", "margin_change"])
        mm["margin_balance"] = mm["margin_balance"].astype(int)
        mm["margin_change"] = mm["margin_change"].astype(int)
        mask = (mm["margin_balance"] > 0) & (mm["margin_change"] > 0) & (
            mm["margin_change"] / mm["margin_balance"] > 0.05
        )
        alerts = mm[mask].copy()
        alerts["alert_pct"] = (alerts["margin_change"] / alerts["margin_balance"] * 100).round(2)
        for _, r in alerts.sort_values("alert_pct", ascending=False).iterrows():
            px = price_map.get(r["stock_id"], {})
            margin_alerts.append({
                "stock_id":       r["stock_id"],
                "stock_name":     r["stock_name"],
                "meta_sector":    r["meta_sector"],
                "margin_balance": int(r["margin_balance"]),
                "margin_change":  int(r["margin_change"]),
                "alert_pct":      float(r["alert_pct"]),
                "close":          px.get("close"),
                "change_pct":     px.get("change_pct"),
            })

    return {
        "foreign_top_buy":  foreign_top_buy,
        "foreign_top_sell": foreign_top_sell,
        "margin_alerts":    margin_alerts,
        "chips_date":       str(latest_date),
    }


def calc_meta_chips_signals(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 10,
) -> Dict[str, Dict[str, Any]]:
    """
    從 DuckDB institutional + margin 歷史計算 META 層級籌碼訊號。
    回傳 {meta_name: {
        foreign_net_today, trust_net_today,  # 今日合計（原始股數）
        foreign_buy_count, total_stocks,
        foreign_buy_ratio,                    # 外資買超檔數 / META 總檔數（分母只算 today 當天實際有資料的交易所）
        foreign_streak,                       # 正=連買天數, 負=連賣
        trust_streak,
        margin_change_today, margin_balance_today,
        margin_alert,                         # bool
    }}
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            "SELECT DISTINCT date FROM institutional ORDER BY date DESC LIMIT ?",
            [lookback],
        ).fetchdf()
        if dates_df.empty:
            con.close()
            return {}
        min_date = dates_df["date"].min()
        inst_df = con.execute(
            "SELECT stock_id, date, foreign_net, trust_net FROM institutional WHERE date >= ?",
            [min_date],
        ).fetchdf()
        margin_df = con.execute(
            "SELECT stock_id, date, margin_balance, margin_change FROM margin WHERE date >= ?",
            [min_date],
        ).fetchdf()
        con.close()
    except Exception:
        return {}

    if inst_df.empty:
        return {}

    universe = universe_df[["stock_id", "meta_sector", "exchange"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    inst_df["stock_id"] = inst_df["stock_id"].astype(str)

    inst_merged = inst_df.merge(universe, on="stock_id", how="inner")
    inst_merged = inst_merged.dropna(subset=["foreign_net", "meta_sector"])
    if inst_merged.empty:
        return {}

    all_dates = sorted(inst_merged["date"].unique().tolist())
    today = all_dates[-1]
    today_inst = inst_merged[inst_merged["date"] == today]

    foreign_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["foreign_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )
    trust_pivot = (
        inst_merged.groupby(["meta_sector", "date"])["trust_net"].sum()
        .unstack(level="date").reindex(columns=all_dates).fillna(0)
    )

    margin_by_meta: Dict[str, Any] = {}
    if not margin_df.empty:
        margin_df["stock_id"] = margin_df["stock_id"].astype(str)
        margin_merged = margin_df.merge(universe, on="stock_id", how="inner")
        today_margin = margin_merged[margin_merged["date"] == today]
        if not today_margin.empty:
            for meta_name, grp in today_margin.groupby("meta_sector"):
                mc = int(grp["margin_change"].sum())
                mb = int(grp["margin_balance"].sum())
                margin_by_meta[meta_name] = {
                    "margin_change_today": mc,
                    "margin_balance_today": mb,
                    "margin_alert": mb > 0 and mc / mb > 0.05,
                }

    # institutional/margin 現在同時有 TWSE（T86/MI_MARGN）跟 TPEx（tpex_3insti_daily_trading/
    # tpex_mainboard_margin_balance）來源，理想狀況分母可以算整個族群成分股數。
    # 但 TPEx 這兩支官方 API 只能抓「當下」、沒有日期參數，發布時間可能跟 TWSE 錯開一天；
    # 若 TPEx 當天抓取失敗（main.py 的 try/except 只會 log warning、不阻擋），或單純兩所發布
    # 日期不同步，institutional 表當天就可能只有單一交易所的資料。分母若仍固定用「TWSE+TPEx
    # 全族群成分股數」，分子（buy_count）卻只能來自實際有資料的那個交易所，比例會被系統性低估
    # ——尤其是上櫃佔比高的族群。改成分母只算「today 這天實際有資料的交易所」涵蓋的成分股數，
    # 跟分子的交易所範圍保持一致；等兩所資料都到齊，分母會自動回到全族群。
    meta_stock_count_by_exchange = (
        universe.groupby(["meta_sector", "exchange"])["stock_id"].count()
    )

    def _streak(vals: list) -> int:
        if not vals:
            return 0
        today_dir = 1 if vals[-1] > 0 else (-1 if vals[-1] < 0 else 0)
        if today_dir == 0:
            return 0
        count = 1
        for v in reversed(vals[:-1]):
            d = 1 if v > 0 else (-1 if v < 0 else 0)
            if d == today_dir:
                count += 1
            else:
                break
        return count * today_dir

    signals: Dict[str, Dict[str, Any]] = {}
    for meta_name in foreign_pivot.index:
        f_row = foreign_pivot.loc[meta_name]
        t_row = trust_pivot.loc[meta_name]

        foreign_net_today = int(f_row.get(today, 0))
        trust_net_today = int(t_row.get(today, 0))

        meta_today = today_inst[today_inst["meta_sector"] == meta_name]
        covered_exchanges = meta_today["exchange"].dropna().unique().tolist()
        if covered_exchanges and meta_name in meta_stock_count_by_exchange.index.get_level_values(0):
            total_stocks = int(
                meta_stock_count_by_exchange.loc[meta_name]
                .reindex(covered_exchanges).fillna(0).sum()
            )
        else:
            total_stocks = 0
        buy_count = int((meta_today["foreign_net"] > 0).sum())

        foreign_streak = _streak([float(f_row.get(d, 0)) for d in all_dates])
        trust_streak = _streak([float(t_row.get(d, 0)) for d in all_dates])

        m = margin_by_meta.get(meta_name, {})
        signals[meta_name] = {
            "foreign_net_today": foreign_net_today,
            "trust_net_today": trust_net_today,
            "foreign_buy_count": buy_count,
            "total_stocks": total_stocks,
            "foreign_buy_ratio": round(buy_count / total_stocks, 2) if total_stocks > 0 else 0,
            "foreign_streak": foreign_streak,
            "trust_streak": trust_streak,
            "margin_change_today": m.get("margin_change_today", 0),
            "margin_balance_today": m.get("margin_balance_today", 0),
            "margin_alert": m.get("margin_alert", False),
        }

    return signals
