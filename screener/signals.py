"""
選股訊號掃描器

巨量換手訊號（三條件同時成立）：
  ① 爆量：今日量 == 過去 N 交易日最大值
  ② 收跌不鎖跌停：close < prev_close 且 change_pct > -9.5%
  ③ 前日漲停：prev_change_pct >= 9.5%

附帶資訊（非過濾條件，供人工判斷）：
  ✦ 量倍數（今日量 / lookback 均量）
  ✦ 外資/投信/三大法人當日買賣超
  ✦ inst_confirmed：外資 + 投信同日皆買超
"""
import logging
from typing import List, Dict, Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"
_UNIVERSE_PATH = "data/stock_universe.csv"

# lookback 視窗至少要有這麼多筆真實資料，量倍數才有統計意義。
# 少於這個門檻代表該股歷史回補不足（例如只有錨點日 + 今天兩筆），
# 拿去算「今日量 / 均量」會是無意義的雜訊，不能當正常訊號用。
_MIN_WINDOW_DAYS = 20

# 動能派均線健檢常數（見 docs/superpowers/specs/2026-07-14-momentum-strategy-page-design.md）
_MIN_MA_HISTORY_DAYS = 65   # MA60 + 斜率比較所需最少交易日（60 + 緩衝）
_EXIT_BIG_BLACK_PCT = -4.0  # 「重挫長黑」門檻，主觀預設值，可依實測調整
_RS_WINDOW_DAYS = 5         # 相對強弱計算窗口，對齊現有累積漲跌 badge

_LIMIT_UP_PCT = 9.5   # 漲停判定門檻，沿用 scan_volume_turnover 既有慣例（見設計文件資料正確性風險）

# 通用多頭排列＋創新高掃描常數（動能派筆記十一/四十五；mapping spec B3）
_DEFAULT_LOOKBACK_DAYS = 60  # 「創新高」比較窗口，約一季（波段新高，非歷史新高，理由見統整 spec）
_B3_VOLUME_MULTIPLE = 1.5     # 量能確認門檻（v2 spec §3.4），沿用 scan_volume_turnover 既有慣例
_B3_VOLUME_LOOKBACK_DAYS = 20  # 量能確認的均量比較窗口


def _load_universe_map(universe_path: str = _UNIVERSE_PATH) -> dict:
    try:
        df = pd.read_csv(universe_path, usecols=["stock_id", "stock_name", "meta_sector"], dtype=str)
        return df.set_index("stock_id")[["stock_name", "meta_sector"]].to_dict("index")
    except Exception:
        return {}


def _load_universe_df(universe_path: str = _UNIVERSE_PATH) -> pd.DataFrame:
    return pd.read_csv(universe_path, dtype=str)


def scan_volume_turnover(
    trade_date: str,
    lookback: int = 126,
    db_path: str = _DB_PATH,
) -> List[Dict[str, Any]]:
    """
    掃描巨量換手訊號，並附上三大法人確認評級。

    Parameters
    ----------
    trade_date : str   e.g. "2026-06-24"
    lookback   : int   成交量比較窗口（交易日數，預設 126）

    Returns
    -------
    list of dict，依量倍數降序排列，每筆含：
        stock_id, close, change_pct, volume,
        prev_close, prev_change_pct,
        vol_multiple (今日量 / 均量),
        vol_window_days (實際窗口天數),
        foreign_net, trust_net, total_net,   ← 當日三大法人（無資料為 None）
        inst_confirmed                        ← 外資 + 投信同日皆買超
    """
    con = duckdb.connect(db_path, read_only=True)

    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()

    # 三大法人：只取訊號當日
    inst_df = con.execute(f"""
        SELECT stock_id, foreign_net, trust_net, total_net
        FROM institutional
        WHERE date = '{trade_date}'
    """).df()

    con.close()

    if price_df.empty:
        logger.warning("scan_volume_turnover: DuckDB 無行情資料")
        return []

    # 建立三大法人查詢字典
    inst_map: dict = {}
    if not inst_df.empty:
        inst_map = inst_df.set_index("stock_id")[["foreign_net", "trust_net", "total_net"]].to_dict("index")

    universe_map = _load_universe_map()
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]
        if today_idx < 1:
            continue

        today = grp.iloc[today_idx]
        prev  = grp.iloc[today_idx - 1]

        # ── 硬性三條件 ──────────────────────────────────────────
        # ② 收跌不鎖跌停
        if not (today["close"] < prev["close"] and today["change_pct"] > -9.5):
            continue

        # ③ 前日漲停
        if prev["change_pct"] < 9.5:
            continue

        # ① 爆量：今日量 = 過去 lookback 日最大值
        window_start = max(0, today_idx - lookback + 1)
        window = grp.iloc[window_start: today_idx + 1]
        if len(window) < _MIN_WINDOW_DAYS:
            # 歷史資料不足（例如 TWSE 回補被封鎖，只剩錨點日+今天兩筆），
            # 均量/量倍數統計上沒有意義，直接跳過該股票，不要產生誤導性訊號。
            continue
        vol_max = window["volume"].max()
        if int(today["volume"]) < int(vol_max):
            continue

        # ── 附帶資訊 ────────────────────────────────────────────
        vol_avg = window["volume"].mean()
        vol_multiple = round(today["volume"] / vol_avg, 1) if vol_avg > 0 else 0

        # 量倍數過低 → 雜訊，不納入
        if vol_multiple < 1.5:
            continue

        inst = inst_map.get(sid, {})
        foreign_net = inst.get("foreign_net")
        trust_net   = inst.get("trust_net")
        total_net   = inst.get("total_net")

        inst_confirmed = (
            foreign_net is not None and foreign_net > 0 and
            trust_net   is not None and trust_net   > 0
        )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":        sid,
            "stock_name":      uinfo.get("stock_name", ""),
            "meta_sector":     uinfo.get("meta_sector", ""),
            "close":           today["close"],
            "change_pct":      today["change_pct"],
            "volume":          int(today["volume"]),
            "prev_close":      prev["close"],
            "prev_change_pct": prev["change_pct"],
            "vol_multiple":    vol_multiple,
            "vol_window_days": len(window),
            "foreign_net":     foreign_net,
            "trust_net":       trust_net,
            "total_net":       total_net,
            "inst_confirmed":  inst_confirmed,
        })

    # 量倍數越大排越前面
    results.sort(key=lambda x: -x["vol_multiple"])

    has_inst = len(inst_map) > 0
    logger.info(
        "巨量換手掃描 %s：命中 %d 檔（三大法人資料%s）",
        trade_date, len(results), "已取得" if has_inst else "尚未發布"
    )
    return results


def scan_momentum_health(
    trade_date: str,
    db_path: str = _DB_PATH,
    universe_path: str = _UNIVERSE_PATH,
) -> List[Dict[str, Any]]:
    """
    動能派個股健檢：均線排列、出場三原則、相對強弱評分（族群內+vs大盤）、五級強弱分類。

    均線排列口徑只看 close>MA5>MA10>MA60（三線，策略原始口徑）——ma20 仍會算、仍回傳，
    純資訊性欄位，不參與 ma_alignment 的判斷（見
    docs/superpowers/specs/2026-07-14-momentum-strategy-page-design.md §1.1，早期草案曾誤把
    MA20 也塞進判斷式，比策略定義更嚴格會漏抓，這裡已修正）。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-14"

    Returns
    -------
    list of dict，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma20, ma60,
        ma_alignment ("多頭排列"/"空頭排列"/"糾結"),
        ma5_slope_down (bool)，          ← 出場子條件：五日線下彎
        below_ma5 (bool)，               ← 出場子條件：跌破五日線（v2新增）
        big_black_proxy (bool)，         ← 出場子條件：重挫proxy，非完整K棒長黑判斷（v2新增）
        ma5_rising (bool)，              ← 動能子條件：MA5上揚（v2新增）
        ma10_rising (bool)，             ← 動能子條件：MA10上揚（v2新增）
        exit_3_rule_triggered (bool)，   ← (1)below_ma5 (2)ma5_slope_down (3)big_black_proxy 三者同時成立
        entry_confirmed (bool)，         ← 多頭排列 + ma5_rising + ma10_rising
        rs_score (float|None)，          ← 個股5日報酬 - 族群5日平均報酬
        rs_rank_pct (float|None)，       ← 族群內百分位排名，1.0=最強
        rs_market_score (float|None)，   ← 個股5日報酬 - universe 等權平均5日報酬（vs 大盤，5日週期）
        daily_excess_pct (float|None)，  ← 個股今日漲跌% - universe 今日等權平均漲跌%（單日週期，v2新增，
                                            不可與 rs_market_score 混用，見設計 spec §3.1）
        rs_sample_count (int)，          ← 同族群當日有效算出 rs_score 的股票數（v2新增，RS樣本信心分母）
        strength_tier                    ← 超強/強/整理/弱/超弱
    """
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()

    if price_df.empty:
        logger.warning("scan_momentum_health: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map(universe_path)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]

        if today_idx + 1 < _MIN_MA_HISTORY_DAYS:
            # 歷史資料不足以穩定算出 MA60 + 斜率比較，跳過避免雜訊訊號
            continue

        window = grp.iloc[: today_idx + 1]
        close = window["close"]

        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        if pd.isna(ma60.iloc[-1]) or pd.isna(ma5.iloc[-2]) or pd.isna(ma10.iloc[-2]):
            continue

        ma5_today, ma5_yday = float(ma5.iloc[-1]), float(ma5.iloc[-2])
        ma10_today, ma10_yday = float(ma10.iloc[-1]), float(ma10.iloc[-2])
        ma20_today = float(ma20.iloc[-1])
        ma60_today = float(ma60.iloc[-1])
        today_close = float(close.iloc[-1])

        # 只看三線 close>MA5>MA10>MA60（策略原始口徑），MA20 純資訊性欄位、不參與判斷
        if today_close > ma5_today > ma10_today > ma60_today:
            ma_alignment = "多頭排列"
        elif today_close < ma5_today < ma10_today < ma60_today:
            ma_alignment = "空頭排列"
        else:
            ma_alignment = "糾結"

        ma5_slope_down = ma5_today < ma5_yday
        ma5_rising = ma5_today > ma5_yday
        ma10_rising = ma10_today > ma10_yday

        today = window.iloc[-1]
        below_ma5 = bool(today["close"] < ma5_today)
        big_black_proxy = bool(today["change_pct"] <= _EXIT_BIG_BLACK_PCT)
        exit_3_rule_triggered = bool(below_ma5 and ma5_slope_down and big_black_proxy)
        entry_confirmed = bool(
            ma_alignment == "多頭排列" and ma5_rising and ma10_rising
        )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":              sid,
            "stock_name":            uinfo.get("stock_name", ""),
            "meta_sector":           uinfo.get("meta_sector", ""),
            "close":                 float(today["close"]),
            "change_pct":            float(today["change_pct"]),
            "ma5":                   round(ma5_today, 2),
            "ma10":                  round(ma10_today, 2),
            "ma20":                  round(ma20_today, 2),
            "ma60":                  round(ma60_today, 2),
            "ma_alignment":          ma_alignment,
            "ma5_slope_down":        ma5_slope_down,
            "below_ma5":             below_ma5,
            "big_black_proxy":       big_black_proxy,
            "ma5_rising":            ma5_rising,
            "ma10_rising":           ma10_rising,
            "exit_3_rule_triggered": exit_3_rule_triggered,
            "entry_confirmed":       entry_confirmed,
            "rs_score":              None,
            "rs_rank_pct":           None,
            "rs_market_score":       None,
            "rs_sample_count":       0,
            "daily_excess_pct":      None,
            "strength_tier":         None,
        })

    if not results:
        logger.info("動能健檢掃描 %s：共 0 檔（歷史資料足夠）", trade_date)
        return results

    # ── B4：相對強弱（族群內 + vs 大盤） ──────────────────────────
    universe_df = _load_universe_df(universe_path)

    # 族群基準 = 族群內成分股近5日等權平均累積報酬。刻意不呼叫 calc_cumulative_meta()——
    # 那支函式不吃 trade_date，永遠抓 DB 裡最新日期算，回測餵歷史 trade_date 時會洩漏
    # trade_date 之後才發生的未來資料（look-ahead bias，見 bug-reports.md 2026-07-16 重現紀錄）。
    # 改成用已經用 SQL WHERE date<=trade_date 裁切過的 price_df 現算，跟下面 market_cum5
    # 同一套手法（那半原本就正確，因為本來就沒借用 calc_cumulative_meta）。
    sector_map = universe_df.set_index(universe_df["stock_id"].astype(str))["meta_sector"].to_dict()
    sector_price_df = price_df[price_df["stock_id"].astype(str).isin(sector_map.keys())].copy()
    sector_price_df["meta_sector"] = sector_price_df["stock_id"].astype(str).map(sector_map)

    sector_cum5_map = {}
    for meta_name, sgrp in sector_price_df.groupby("meta_sector"):
        sector_dates = sorted(sgrp["date"].unique())
        if len(sector_dates) < _RS_WINDOW_DAYS:
            continue
        last_n = sector_dates[-_RS_WINDOW_DAYS:]
        daily_avg = sgrp[sgrp["date"].isin(last_n)].groupby("date")["change_pct"].mean()
        factor = 1.0
        for d in last_n:
            pct = daily_avg.get(d)
            if pct is not None and pd.notna(pct):
                factor *= (1 + float(pct) / 100)
        sector_cum5_map[meta_name] = round((factor - 1) * 100, 2)

    # 「大盤」基準 = universe 等權平均近5日累積報酬（不用 TAIEX 加權指數——universe 只有
    # 追蹤的電子科技股，跟涵蓋全市場的 TAIEX 不是同一個母體，混用會有 apples-to-oranges 問題）。
    # 只用有在 universe 裡的股票，跟族群基準同一套母體。
    universe_ids = set(universe_df["stock_id"].astype(str))
    market_df = price_df[price_df["stock_id"].astype(str).isin(universe_ids) & (price_df["date"] <= target)]
    market_cum5 = None
    market_dates = sorted(market_df["date"].unique())
    if len(market_dates) >= _RS_WINDOW_DAYS:
        last_n = market_dates[-_RS_WINDOW_DAYS:]
        daily_avg = market_df[market_df["date"].isin(last_n)].groupby("date")["change_pct"].mean()
        factor = 1.0
        for d in last_n:
            pct = daily_avg.get(d)
            if pct is not None and pd.notna(pct):
                factor *= (1 + float(pct) / 100)
        market_cum5 = round((factor - 1) * 100, 2)

    # 「今日」大盤基準（v2 spec §3.1 daily_excess_pct，跟上面的5日 market_cum5 是不同週期，
    # 不能混用——這裡只取 target 當天 universe 等權平均，不做5日累積）。
    today_market_df = market_df[market_df["date"] == target]
    market_today_avg_pct = None
    if not today_market_df.empty:
        avg_val = today_market_df["change_pct"].mean()
        if pd.notna(avg_val):
            market_today_avg_pct = float(avg_val)

    for row in results:
        sid = row["stock_id"]
        if market_today_avg_pct is not None and pd.notna(row["change_pct"]):
            row["daily_excess_pct"] = round(row["change_pct"] - market_today_avg_pct, 2)

        grp = price_df[(price_df["stock_id"] == sid) & (price_df["date"] <= target)]
        cum5_window = grp.sort_values("date").tail(_RS_WINDOW_DAYS)
        if len(cum5_window) < _RS_WINDOW_DAYS:
            continue  # rs_score/rs_market_score 保持 None

        factor = 1.0
        for pct in cum5_window["change_pct"]:
            factor *= (1 + float(pct) / 100)
        stock_cum5 = round((factor - 1) * 100, 2)

        sector_cum5 = sector_cum5_map.get(row["meta_sector"])
        if sector_cum5 is not None:
            row["rs_score"] = round(stock_cum5 - sector_cum5, 2)
        if market_cum5 is not None:
            row["rs_market_score"] = round(stock_cum5 - market_cum5, 2)

    rs_df = pd.DataFrame(results)
    valid = rs_df["rs_score"].notna()
    if valid.any():
        rs_df.loc[valid, "rs_rank_pct"] = (
            rs_df.loc[valid].groupby("meta_sector")["rs_score"].rank(pct=True, ascending=True)
        )
        sample_counts = rs_df.loc[valid].groupby("meta_sector")["rs_score"].transform("count")
        rs_df.loc[valid, "rs_sample_count"] = sample_counts
    for i, row in enumerate(results):
        val = rs_df.loc[i, "rs_rank_pct"]
        row["rs_rank_pct"] = None if pd.isna(val) else round(float(val), 3)
        count_val = rs_df.loc[i, "rs_sample_count"]
        row["rs_sample_count"] = int(count_val) if pd.notna(count_val) else 0

    # ── 五級強弱分類 ──────────────────────────────────────────────
    for row in results:
        rank = row["rs_rank_pct"]
        if row["ma_alignment"] == "空頭排列" and row["exit_3_rule_triggered"]:
            row["strength_tier"] = "超弱"
        elif row["ma_alignment"] == "多頭排列" and rank is not None and rank >= 0.8:
            row["strength_tier"] = "超強"
        elif row["ma_alignment"] == "多頭排列" and (rank is None or rank >= 0.5):
            row["strength_tier"] = "強"
        elif row["ma_alignment"] == "空頭排列":
            row["strength_tier"] = "弱"
        elif row["ma_alignment"] == "糾結":
            row["strength_tier"] = "整理"
        else:
            row["strength_tier"] = "弱"

    logger.info("動能健檢掃描 %s：共 %d 檔（歷史資料足夠）", trade_date, len(results))
    return results


def scan_consecutive_limit_up(
    trade_date: str,
    db_path: str = _DB_PATH,
    universe_path: str = _UNIVERSE_PATH,
) -> List[Dict[str, Any]]:
    """
    連續漲停鎖死偵測：逐股計算連續鎖漲停天數，供「最強型態」排序/標記使用。

    跟 scan_volume_turnover() 是獨立函式：那個抓「漲停打開反轉」，這個抓「還在
    連續鎖死」，語意相反，資料來源相同但用途不同，刻意不合併。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-14"

    Returns
    -------
    list of dict，依 limit_up_streak 降冪排列，每筆含：
        stock_id, stock_name, meta_sector, close, change_pct, volume,
        limit_up_streak (連續鎖漲停天數，今天算第1天),
        volume_declining_streak (bool|None，連板期間量是否逐日遞減/持平；
                                  streak<2 時為 None)
    """
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()

    if price_df.empty:
        logger.warning("scan_consecutive_limit_up: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map(universe_path)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]
        today = grp.iloc[today_idx]

        if today["change_pct"] < _LIMIT_UP_PCT:
            continue

        # 從今天往前數連續漲停天數
        streak = 0
        i = today_idx
        while i >= 0 and grp.iloc[i]["change_pct"] >= _LIMIT_UP_PCT:
            streak += 1
            i -= 1

        # 量縮鎖死判斷（筆記：惜售最強）：連板期間成交量逐日遞減或持平（舊→新）。
        # streak 天數對應的列是 [i+1, today_idx]（含頭尾，已按日期升冪排序）。
        volume_declining_streak = None
        if streak >= 2:
            streak_vols = grp.iloc[i + 1: today_idx + 1]["volume"].tolist()
            volume_declining_streak = all(
                streak_vols[k] <= streak_vols[k - 1] for k in range(1, len(streak_vols))
            )

        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                sid,
            "stock_name":              uinfo.get("stock_name", ""),
            "meta_sector":             uinfo.get("meta_sector", ""),
            "close":                   float(today["close"]),
            "change_pct":              float(today["change_pct"]),
            "volume":                  int(today["volume"]),
            "limit_up_streak":         streak,
            "volume_declining_streak": volume_declining_streak,
        })

    results.sort(key=lambda x: -x["limit_up_streak"])

    logger.info("連續漲停鎖死掃描 %s：命中 %d 檔", trade_date, len(results))
    return results


def scan_bullish_alignment_new_high(
    trade_date: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    db_path: str = _DB_PATH,
    universe_path: str = _UNIVERSE_PATH,
) -> List[Dict[str, Any]]:
    """
    通用多頭排列＋創新高掃描（動能派筆記十一、四十五；mapping spec B3）。

    跟 patterns.py::detect_breakout_confirm（「多頭拐點」）不同：那支限定 MA60
    要先走平才轉折，抓的是「長期盤整後啟動」；這支不要求 MA60 走平，抓「已經在
    乾淨多頭排列、還在創新高」的續強訊號，兩者並存、互補（一個抓啟動、一個抓續強），
    這支不修改也不呼叫 detect_breakout_confirm。

    均線用 5/10/60（不是既有 detect_breakout_confirm 的 5/20/60——動能派策略用
    MA10 不是 MA20，見 mapping spec B1/B3）。

    ⚠️ 已知限制（未修復，記錄於此避免誤用）：「創新高」用的是原始收盤價
    （daily_prices.close，TWSE/TPEx 官方每日資料本來就是原始價；yfinance 回補
    是否為還原價則依安裝版本的 auto_adjust 預設值而定，本專案未明確鎖定，見
    scrapers/backfill.py::_fetch_yfinance_one_stock）。除權息當天原始價會跳空
    下修，可能讓除權息後短期內的個股被誤判「沒創新高」（假陰性，不是假陽性——
    不會多顯示錯誤訊號，只會少顯示，相對安全但仍不精確）。專案目前沒有任何還原
    股價資料源可用，這是資料面的既有缺口，不在這次範圍內修。

    lookback_days 預設 60（約一季，「波段新高」，不是「歷史新高」）：全市場個股
    的歷史回補深度不穩定，用全歷史「歷史新高」在資料不齊時會產生系統性偏誤
    （回補淺的股票更容易被誤判創新高）；60 個交易日是務實的預設值，呼叫端可調整。

    Parameters
    ----------
    trade_date : str   e.g. "2026-07-14"
    lookback_days : int   「創新高」比較窗口（交易日，含今日，預設 60）

    Returns
    -------
    list of dict，只回傳「多頭排列 且 創新高」都成立的股票，依 change_pct 降序：
        stock_id, stock_name, meta_sector, close, change_pct,
        ma5, ma10, ma60, lookback_days,
        volume_ratio_20d (float|None)，  ← 今日量/前20日均量，v2新增（不足20日回None）
        volume_confirmed (bool|None)     ← volume_ratio_20d >= 1.5，v2新增，純標記不過濾清單
    """
    con = duckdb.connect(db_path, read_only=True)
    price_df = con.execute(f"""
        SELECT stock_id, date, close, change_pct, volume
        FROM daily_prices
        WHERE date <= '{trade_date}'
        ORDER BY stock_id, date
    """).df()
    con.close()

    if price_df.empty:
        logger.warning("scan_bullish_alignment_new_high: DuckDB 無行情資料")
        return []

    universe_map = _load_universe_map(universe_path)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target = pd.to_datetime(trade_date)

    min_history = max(60, lookback_days)
    results = []

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        today_rows = grp[grp["date"] == target]
        if today_rows.empty:
            continue
        today_idx = today_rows.index[0]

        if today_idx + 1 < min_history:
            # 歷史資料不足以穩定算出 MA60 或跑滿 lookback_days 窗口，跳過避免雜訊訊號
            continue

        window = grp.iloc[: today_idx + 1]
        close = window["close"]

        ma5  = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        if pd.isna(ma60):
            continue

        today_close = float(close.iloc[-1])
        if not (today_close > ma5 > ma10 > ma60):
            continue

        prior_window = close.iloc[-lookback_days:-1]
        if prior_window.empty or today_close <= prior_window.max():
            continue

        volume = window["volume"]
        # 注意：daily_prices.volume 是 BIGINT，DuckDB→pandas 若欄位有 NULL 會轉成
        # nullable Int64 的 pd.NA（不是 float NaN），float(pd.NA) 會直接 raise
        # TypeError，所以「先用 pd.isna 判斷、再轉 float」的順序不能反過來。
        raw_today_volume = volume.iloc[-1]
        prior_vol_window = volume.iloc[-(_B3_VOLUME_LOOKBACK_DAYS + 1):-1]
        if len(prior_vol_window) < _B3_VOLUME_LOOKBACK_DAYS or pd.isna(raw_today_volume):
            volume_ratio_20d = None
            volume_confirmed = None
        else:
            today_volume = float(raw_today_volume)
            avg_vol = prior_vol_window.mean()
            if pd.notna(avg_vol) and avg_vol > 0:
                volume_ratio_20d = round(today_volume / avg_vol, 2)
                volume_confirmed = bool(volume_ratio_20d >= _B3_VOLUME_MULTIPLE)
            else:
                volume_ratio_20d = None
                volume_confirmed = None

        today_row = window.iloc[-1]
        change_pct = today_row.get("change_pct")
        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":         sid,
            "stock_name":       uinfo.get("stock_name", ""),
            "meta_sector":      uinfo.get("meta_sector", ""),
            "close":            today_close,
            "change_pct":       float(change_pct) if pd.notna(change_pct) else None,
            "ma5":              round(float(ma5), 2),
            "ma10":             round(float(ma10), 2),
            "ma60":             round(float(ma60), 2),
            "lookback_days":    lookback_days,
            "volume_ratio_20d": volume_ratio_20d,
            "volume_confirmed": volume_confirmed,
        })

    results.sort(key=lambda x: -(x["change_pct"] or 0))
    logger.info("多頭排列+創新高掃描 %s：命中 %d 檔（lookback=%d）", trade_date, len(results), lookback_days)
    return results
