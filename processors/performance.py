import pandas as pd
import duckdb
from typing import List, Dict, Any, Optional
from config import META_SECTORS, get_meta_sector, META_PRIORITY_LIST
from streak_utils import calc_streak as _streak

_MARGIN_ALERT_MIN_PREV_BALANCE = 1000
_MARGIN_ALERT_MIN_VOLUME_LOTS = 500
_MARGIN_ALERT_RATIO = 0.05


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
) -> Dict[str, dict]:
    """每支個股近 N 日漲跌與成交量歷史，供 HTML 個股卡片及 modal 使用。"""
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
    stock_ids = set(universe_df["stock_id"].astype(str))
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)
    prices_df = prices_df[prices_df["stock_id"].isin(stock_ids)]

    pct_pivot = (
        prices_df.dropna(subset=["change_pct"])
        .groupby(["stock_id", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )
    volume_pivot = (
        prices_df.dropna(subset=["volume"])
        .groupby(["stock_id", "date"])["volume"].sum()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )

    result: Dict[str, dict] = {}
    for sid in pct_pivot.index:
        volumes = [int(volume_pivot.loc[sid, d]) if sid in volume_pivot.index else 0 for d in all_dates]
        prior_volumes = [v for v in volumes[:-1] if v > 0]
        avg_volume = round(sum(prior_volumes) / len(prior_volumes)) if prior_volumes else 0
        today_volume = volumes[-1] if volumes else 0
        result[sid] = {
            "pcts": [round(float(pct_pivot.loc[sid, d]), 2) for d in all_dates],
            "volumes": volumes,
            "dates": [pd.Timestamp(d).strftime("%m/%d") for d in all_dates],
            "avg_volume": avg_volume,
            "vol_ratio": round(today_volume / avg_volume, 2) if avg_volume > 0 else None,
        }
    return result


def get_margin_divergence(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    lookback: int = 10,
    margin_thresh: float = 3.0,
    price_thresh: float = 2.0,
    as_of_date: str | None = None,
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
            "SELECT DISTINCT date FROM margin WHERE (? IS NULL OR date <= ?) ORDER BY date DESC LIMIT ?",
            [as_of_date, as_of_date, lookback],
        ).fetchdf()
        if dates_row.empty or len(dates_row) < 2:
            con.close()
            return {"bearish": [], "bullish": [], "days_used": 0}

        dates = sorted(dates_row["date"].tolist())
        min_date = dates[0]

        margin_df = con.execute(
            "SELECT stock_id, date, margin_balance FROM margin WHERE date >= ? AND (? IS NULL OR date <= ?) AND margin_balance > 0",
            [min_date, as_of_date, as_of_date],
        ).fetchdf()
        price_df = con.execute(
            "SELECT stock_id, date, close FROM daily_prices WHERE date >= ? AND (? IS NULL OR date <= ?) AND close > 0",
            [min_date, as_of_date, as_of_date],
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
        "foreign_top_buy":  [{stock_id, stock_name, meta_sector, foreign_net, trust_net, foreign_pct}, ...],
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
        # institutional / margin 各自 per-stock 取自己最新一筆（不綁單一 MAX 日期）：
        # TWSE/TPEx 發布日不同步、或 margin 比 institutional 晚一天時，單一 MAX(date) 會漏掉
        # 落後那一邊、或整批 margin 歸零。比照 get_chips_today 的 per-stock fallback。
        # 帶回每檔自己那筆的 date：per-stock 取最新時 TWSE/TPEx 進度不同會混用不同交易日，
        # 每列保留 data_date，畫面才能誠實標示、不會把落後一天的數字謊報成同一天（新 🔴 修復）。
        inst_df = con.execute("""
            SELECT stock_id, foreign_net, trust_net, date FROM institutional
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
        """).fetchdf()
        margin_df = con.execute("""
            SELECT stock_id, margin_balance, margin_change, date FROM margin
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
        """).fetchdf()
        try:
            price_df = con.execute("""
                SELECT stock_id, close, change_pct, volume FROM daily_prices
                QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
            """).fetchdf()
        except Exception:
            # 舊資料庫沒有 volume 欄時維持原有排行行為；正式 DB 有欄位才套流動性門檻。
            price_df = con.execute("""
                SELECT stock_id, close, change_pct, 1000000000::BIGINT AS volume FROM daily_prices
                QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
            """).fetchdf()
        # 外資持股%（存量資料，跟 foreign_net 買賣超流量是不同資料源/更新頻率，per-stock 取
        # 最新一筆即可，不用跟 institutional 的 date 嚴格對齊）。獨立包一層 try：這是新資料源
        # （foreign_holdings 表可能還沒建立，例如尚未跑過任何一次 _update_chips_db），缺這張表
        # 不該讓整個籌碼排行連 institutional/margin 都一起壞掉。
        try:
            fh_df = con.execute("""
                SELECT stock_id, foreign_pct FROM foreign_holdings
                QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) = 1
            """).fetchdf()
        except Exception:
            fh_df = pd.DataFrame()
        con.close()
    except Exception:
        return {}

    universe = universe_df[["stock_id", "stock_name", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)

    if not price_df.empty:
        price_df["stock_id"] = price_df["stock_id"].astype(str)
        # 洗掉 NaN（daily_prices.close 可能是 NULL→NaN，例：停牌/全額交割）→ 換成 None，
        # 否則 chips_generator._price_cell 的 int(nan) 會 ValueError、讓整個 chips.html 停更。
        # 注意：float 欄位的 .where(notna, None) 不會真的換成 None（NaN 留著），要先轉 object。
        _pc = price_df.set_index("stock_id")[["close", "change_pct", "volume"]].astype(object)
        price_map: Dict[str, dict] = _pc.where(_pc.notna(), None).to_dict("index")
    else:
        price_map = {}

    if not fh_df.empty:
        fh_df["stock_id"] = fh_df["stock_id"].astype(str)
        foreign_pct_map: Dict[str, float] = fh_df.set_index("stock_id")["foreign_pct"].to_dict()
    else:
        foreign_pct_map = {}

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
                "data_date":   str(r["date"])[:10],  # Timestamp→純日期(YYYY-MM-DD)
                "foreign_pct": foreign_pct_map.get(r["stock_id"]),
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
        mm["prev_margin_balance"] = mm["margin_balance"] - mm["margin_change"]
        mm["volume"] = mm["stock_id"].map(lambda sid: price_map.get(sid, {}).get("volume"))
        mask = (
            (mm["prev_margin_balance"] >= _MARGIN_ALERT_MIN_PREV_BALANCE)
            & (mm["margin_change"] > 0)
            & (mm["volume"].fillna(0) >= _MARGIN_ALERT_MIN_VOLUME_LOTS)
            & (mm["margin_change"] / mm["prev_margin_balance"] > _MARGIN_ALERT_RATIO)
        )
        alerts = mm[mask].copy()
        alerts["alert_pct"] = (alerts["margin_change"] / alerts["prev_margin_balance"] * 100).round(2)
        for _, r in alerts.sort_values("alert_pct", ascending=False).iterrows():
            px = price_map.get(r["stock_id"], {})
            margin_alerts.append({
                "stock_id":       r["stock_id"],
                "stock_name":     r["stock_name"],
                "meta_sector":    r["meta_sector"],
                "margin_balance": int(r["margin_balance"]),
                "margin_change":  int(r["margin_change"]),
                "prev_margin_balance": int(r["prev_margin_balance"]),
                "alert_pct":      float(r["alert_pct"]),
                "close":          px.get("close"),
                "change_pct":     px.get("change_pct"),
                "data_date":      str(r["date"])[:10],  # Timestamp→純日期(YYYY-MM-DD)
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
    margin_covered_by_meta: Dict[str, set] = {}
    if not margin_df.empty:
        margin_df["stock_id"] = margin_df["stock_id"].astype(str)
        margin_merged = margin_df.merge(universe, on="stock_id", how="inner")
        # margin 用 margin 自己的最新日期，不要綁 institutional 的 today——兩表發布日可能不同步，
        # 用 institutional 的 today 過濾 margin 會在 margin 落後一天時把整批 margin 數字歸零。
        margin_today = margin_merged["date"].max() if not margin_merged.empty else None
        today_margin = margin_merged[margin_merged["date"] == margin_today]
        if not today_margin.empty:
            for meta_name, grp in today_margin.groupby("meta_sector"):
                mc = int(grp["margin_change"].sum())
                mb = int(grp["margin_balance"].sum())
                prev_mb = mb - mc
                margin_by_meta[meta_name] = {
                    "margin_change_today": mc,
                    "margin_balance_today": mb,
                    "margin_alert": (
                        prev_mb >= _MARGIN_ALERT_MIN_PREV_BALANCE
                        and mc > 0
                        and mc / prev_mb > _MARGIN_ALERT_RATIO
                    ),
                }
                margin_covered_by_meta[meta_name] = set(grp["exchange"].dropna().unique())

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
    # 族群實際橫跨的交易所（例如純上市族群本來就沒有 TPEx 成分股，不能算「涵蓋不足」）。
    # 用來跟「today 這天實際有資料的交易所」比較，才能分辨「單純資料源當天抓取失敗」
    # 跟「這個族群本來就沒有那個交易所的成分股」兩種情況。
    meta_all_exchanges: Dict[str, set] = {
        name: set(grp.dropna().unique())
        for name, grp in universe.groupby("meta_sector")["exchange"]
    }

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

        # 這個族群「應該」橫跨的交易所（該族群實際成分股所在的交易所）跟「today 這天
        # institutional/margin 實際有資料的交易所」比較，任一邊涵蓋不足就標記
        # partial_coverage=True。這不是指族群本來就只有單一交易所成分股的情況
        # （那種 meta_all_exchanges 本身就只有一個交易所，不會觸發），而是指族群明明有
        # 多交易所成分股、但當天某個交易所的資料源抓取失敗或跟另一所發布時間錯開，
        # 導致這裡算出來的 foreign_net_today/streak/margin 數字只反映部分成分股。
        expected_exchanges = meta_all_exchanges.get(meta_name, set())
        inst_partial = bool(expected_exchanges - set(covered_exchanges))
        margin_partial = bool(expected_exchanges - margin_covered_by_meta.get(meta_name, set()))
        partial_coverage = inst_partial or margin_partial

        m = margin_by_meta.get(meta_name, {})
        signals[meta_name] = {
            "foreign_net_today": foreign_net_today,
            "trust_net_today": trust_net_today,
            "foreign_buy_count": buy_count,
            "total_stocks": total_stocks,
            "foreign_buy_ratio": round(buy_count / total_stocks, 2) if total_stocks > 0 else 0,
            "foreign_streak": foreign_streak,
            "trust_streak": trust_streak,
            "partial_coverage": partial_coverage,
            "margin_change_today": m.get("margin_change_today", 0),
            "margin_balance_today": m.get("margin_balance_today", 0),
            "margin_alert": m.get("margin_alert", False),
        }

    return signals


# ═══════════════════════════════════════════════════════════════════
# 大盤分級儀表板（Market Regime Dashboard）— Phase 1
# 兩條獨立軸線：(1) 五級大盤方向 (2) 資金集中度診斷。
# 設計文件：docs/superpowers/specs/2026-07-09-market-regime-dashboard-design.md
# ═══════════════════════════════════════════════════════════════════

def calc_market_breadth(prices_df: pd.DataFrame) -> Dict[str, Any]:
    """個股上漲家數廣度。回傳 {up_count, down_count, flat_count, total, breadth_ratio}。

    對『個股』的 change_pct 計算（不是族群平均），breadth_ratio = up_count / total。
    total 只算有 change_pct（非 NaN）的個股；無資料時 total=0、breadth_ratio=0。
    """
    if prices_df is None or prices_df.empty or "change_pct" not in prices_df.columns:
        return {"up_count": 0, "down_count": 0, "flat_count": 0, "total": 0, "breadth_ratio": 0.0}

    pct = pd.to_numeric(prices_df["change_pct"], errors="coerce").dropna()
    total = int(len(pct))
    up = int((pct > 0).sum())
    down = int((pct < 0).sum())
    flat = total - up - down
    return {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "total": total,
        "breadth_ratio": round(up / total, 4) if total > 0 else 0.0,
    }


def calc_capital_concentration(
    prices_df: pd.DataFrame,
    heavyweight_ids: List[str],
) -> Dict[str, Any]:
    """權值股 vs 非權值股平均漲跌的落差（資金集中度）。

    回傳 {heavyweight_avg_pct, broad_avg_pct, divergence}，
    divergence = heavyweight_avg_pct - broad_avg_pct（可正可負：正=權值股相對強）。
    某一邊沒有資料時該邊的 avg 回 None，divergence 也回 None（無法比較）。
    """
    empty = {"heavyweight_avg_pct": None, "broad_avg_pct": None, "divergence": None}
    if prices_df is None or prices_df.empty or "change_pct" not in prices_df.columns:
        return empty

    df = prices_df.copy()
    df["stock_id"] = df["stock_id"].astype(str)
    df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
    df = df.dropna(subset=["change_pct"])
    if df.empty:
        return empty

    hw_set = set(str(s) for s in (heavyweight_ids or []))
    is_hw = df["stock_id"].isin(hw_set)
    hw_pct = df[is_hw]["change_pct"]
    broad_pct = df[~is_hw]["change_pct"]

    hw_avg = round(float(hw_pct.mean()), 2) if not hw_pct.empty else None
    broad_avg = round(float(broad_pct.mean()), 2) if not broad_pct.empty else None
    divergence = round(hw_avg - broad_avg, 2) if (hw_avg is not None and broad_avg is not None) else None
    return {
        "heavyweight_avg_pct": hw_avg,
        "broad_avg_pct": broad_avg,
        "divergence": divergence,
    }


def classify_market_regime(
    taiex_change_pct: float,
    breadth_ratio: float,
    divergence: Optional[float],
    concentration_threshold: float = 2.0,
) -> Dict[str, Any]:
    """綜合『指數漲跌幅 + 個股廣度』判斷五級大盤方向，並附資金集中度診斷。

    回傳 {tier, is_concentrated, concentration_direction}。
    tier ∈ {大漲, 小漲, 持平, 小跌, 大跌}。
    concentration_direction ∈ {None, 權值股撐盤, 中小型輪動}。

    分級規則（設計文件門檻，兩個條件都要符合；指數有方向但廣度不 confirm 時
    往下降級、最終落到「持平」，並由資金集中度診斷說明背離原因）：
      大漲: 指數 ≥ +1.5% 且 廣度 ≥ 65%
      小漲: 指數 ≥ +0.3% 且 廣度 ≥ 50%
      持平: -0.3% ~ +0.3%（或指數有方向但廣度不足）
      小跌: 指數 ≤ -0.3% 且 廣度 ≤ 50%
      大跌: 指數 ≤ -1.5% 且 廣度 ≤ 35%
    ⚠️ 門檻為設計階段草案、未回測，Task 6 端到端驗證時若明顯不合理應回頭校正。
    """
    pct = taiex_change_pct if taiex_change_pct is not None else 0.0
    b = breadth_ratio if breadth_ratio is not None else 0.0

    if pct >= 1.5 and b >= 0.65:
        tier = "大漲"
    elif pct >= 0.3 and b >= 0.50:
        tier = "小漲"
    elif pct <= -1.5 and b <= 0.35:
        tier = "大跌"
    elif pct <= -0.3 and b <= 0.50:
        tier = "小跌"
    else:
        # -0.3~+0.3，或指數有方向但廣度不 confirm（背離）→ 保守落「持平」
        tier = "持平"

    if divergence is not None and abs(divergence) >= concentration_threshold:
        is_concentrated = True
        concentration_direction = "權值股撐盤" if divergence > 0 else "中小型輪動"
    else:
        is_concentrated = False
        concentration_direction = None

    return {
        "tier": tier,
        "is_concentrated": is_concentrated,
        "concentration_direction": concentration_direction,
    }


def _streak_and_windows_as_of(daily_pcts: List[float], cutoff_index: int) -> Optional[Dict[str, Any]]:
    """
    回推「假裝 cutoff_index 是今天」時的 streak/上週/本週窗口，供族群總覽頁熱區格改版的轉折點
    回推算法使用（不用開新的歷史快照表，見
    docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md §2.3）。

    daily_pcts：某族群「每日平均漲跌%」序列，舊→新排列，長度需涵蓋到 cutoff_index。
    cutoff_index：0-based index，這個位置視為「今天」。

    窗口定義（以 cutoff_index=T0 為基準）：
        thisWeek = daily_pcts[T0-4 : T0+1]   （最近5天，含當天）
        lastWeek = daily_pcts[T0-9 : T0-4]   （再往前5天）
    streak：重用共用工具 streak_utils.calc_streak()，餵入截到 cutoff_index 為止的子序列。

    Returns
    -------
    {"streak": int, "last_week_pct": float, "this_week_pct": float} 或
    None（cutoff_index < 9，可用歷史不足10天，無法同時算出兩個5日窗口；或
    cutoff_index >= len(daily_pcts)，代表呼叫端傳入的cutoff_index跟daily_pcts長度對不上）
    """
    if cutoff_index < 9 or cutoff_index >= len(daily_pcts):
        return None

    this_week_window = daily_pcts[cutoff_index - 4: cutoff_index + 1]
    last_week_window = daily_pcts[cutoff_index - 9: cutoff_index - 4]

    def _compound(window: List[float]) -> float:
        factor = 1.0
        for pct in window:
            factor *= (1 + pct / 100)
        return round((factor - 1) * 100, 2)

    this_week_pct = _compound(this_week_window)
    last_week_pct = _compound(last_week_window)
    streak = _streak(daily_pcts[:cutoff_index + 1])

    return {"streak": streak, "last_week_pct": last_week_pct, "this_week_pct": this_week_pct}


_HEATGRID_LOOKBACK_DAYS = 20  # 涵蓋今天(cutoff=最新)+5天前(cutoff=最新-5)都需要的15天history，留5天餘裕


def calc_meta_heatgrid_windows(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Any]]:
    """
    對每個 meta_sector 算「今天」跟「5個交易日前」的 streak/上週/本週窗口原始數值，供族群總覽頁
    熱區格改版使用。**只回傳原始數值，不做五級分類**——分類邏輯（classify_tier）在
    export/index_generator.py，這支函式只負責查資料庫、算數字（跟 observation_scores.py 算原始
    rs_raw/breadth_raw 等因子、分類邏輯留給消費端的分工一致）。

    Returns
    -------
    {meta_name: {
        "streak_today": int, "last_week_pct_today": float, "this_week_pct_today": float,
        "streak_5d_ago": int | None, "last_week_pct_5d_ago": float | None,
    }}
    `this_week_pct_5d_ago` 不回傳：它等於 last_week_pct_today（見 Task 1 驗證過的窗口重疊
    關係），消費端直接重用 last_week_pct_today 即可，不用多存一份重複資料。
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        dates_df = con.execute(
            f"SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT {_HEATGRID_LOOKBACK_DAYS}"
        ).fetchdf()
        if dates_df.empty:
            return {}
        min_date = dates_df["date"].min()
        price_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices WHERE date >= ?",
            [min_date],
        ).fetchdf()
    except Exception:
        return {}
    finally:
        con.close()

    if price_df.empty:
        return {}

    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    price_df["stock_id"] = price_df["stock_id"].astype(str)

    merged = price_df.merge(universe, on="stock_id", how="inner")
    merged = merged.dropna(subset=["change_pct", "meta_sector"])
    if merged.empty:
        return {}

    all_dates = sorted(merged["date"].unique())
    pct_pivot = (
        merged.groupby(["meta_sector", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
    )

    today_index = len(all_dates) - 1
    five_days_ago_index = today_index - 5

    results: Dict[str, Dict[str, Any]] = {}
    for meta_name in pct_pivot.index:
        raw_series = pct_pivot.loc[meta_name]
        valid_flags = raw_series.notna().tolist()
        daily_pcts = [float(v) if pd.notna(v) else 0.0 for v in raw_series.tolist()]

        def _window_is_real(cutoff_index: int) -> bool:
            # _streak_and_windows_as_of() 用的10天視窗(this_week+last_week)必須全部是真實
            # 資料，不能有被fillna(0.0)頂替的假資料混進去——否則streak/window_pct會悄悄用
            # 「這個族群當時根本還沒交易/沒資料」的偽造平盤天數算出「看起來有效但其實是假
            # 資料」的結果，違反Global Constraints「資料不足時回None，不硬湊」（code review
            # 抓到：這個風險是Task 1 bounds-check防不到的，因為len(all_dates)是全市場聯集，
            # 不代表這個族群本身有那麼長的真實歷史）。
            if cutoff_index < 9:
                return False
            return all(valid_flags[cutoff_index - 9: cutoff_index + 1])

        today_calc = (
            _streak_and_windows_as_of(daily_pcts, today_index)
            if _window_is_real(today_index) else None
        )
        if today_calc is None:
            results[meta_name] = {
                "streak_today": None, "last_week_pct_today": None, "this_week_pct_today": None,
                "streak_5d_ago": None, "last_week_pct_5d_ago": None,
            }
            continue

        five_days_ago_calc = (
            _streak_and_windows_as_of(daily_pcts, five_days_ago_index)
            if five_days_ago_index >= 0 and _window_is_real(five_days_ago_index) else None
        )

        results[meta_name] = {
            "streak_today": today_calc["streak"],
            "last_week_pct_today": today_calc["last_week_pct"],
            "this_week_pct_today": today_calc["this_week_pct"],
            "streak_5d_ago": five_days_ago_calc["streak"] if five_days_ago_calc else None,
            "last_week_pct_5d_ago": five_days_ago_calc["last_week_pct"] if five_days_ago_calc else None,
        }

    return results
