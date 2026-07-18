"""
法人買進篩選器

支援多種過濾條件，可任意組合：
  foreign_streak   外資連買 ≥ N 日
  trust_streak     投信連買 ≥ N 日
  both_streak      外資+投信同時連買 ≥ N 日
  min_foreign_net  今日外資買超 ≥ N 股（負值為賣超；institutional 表單位是股，非元）
  min_trust_net    今日投信買超 ≥ N 股
  min_total_net    今日三大法人合計 ≥ N 股
  cum_foreign_net  lookback 天內外資累計 ≥ N 股
  cum_trust_net    lookback 天內投信累計 ≥ N 股
"""
import logging
from typing import Any, Dict, List

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# 「法人同步買超觀察」採用可解釋、可回測的固定門檻。volume 在 daily_prices 以張為單位，
# institutional 買賣超則以股為單位，因此計算占量時需乘 1,000。
JOINT_BUY_MIN_STREAK = 2
JOINT_BUY_MIN_PRICE_CUM_PCT = 0.0
JOINT_BUY_MIN_VOLUME_LOTS = 500
JOINT_BUY_MIN_FLOW_RATIO_PCT = 0.1


def is_joint_buy_signal(row: dict) -> bool:
    """法人同步買超觀察：連買、價格、流動性與買超占量四項都通過。"""
    return (
        (row.get("both_streak") or 0) >= JOINT_BUY_MIN_STREAK
        and row.get("price_cum_pct") is not None
        and row["price_cum_pct"] >= JOINT_BUY_MIN_PRICE_CUM_PCT
        and (row.get("volume") or 0) >= JOINT_BUY_MIN_VOLUME_LOTS
        and (row.get("institutional_flow_ratio_pct") or 0) >= JOINT_BUY_MIN_FLOW_RATIO_PCT
    )


def percentile_ranks(values: list[float]) -> list[float]:
    """0–1 百分位排名；同值使用平均排名，單一值回傳 1。"""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return [rank / (n - 1) for rank in ranks]


_CONTINUATION_WEIGHT_MODES = {"blended", "streak_only", "price_only"}


def rank_continuation_candidates(
    candidates: list[dict], streak_key: str, limit: int | None = None,
    weight_mode: str = "blended",
) -> list[dict]:
    """連買天數與 10 日漲幅的排行，供頁面與回測使用。

    weight_mode（預設 "blended"，維持既有頁面呼叫方式不變的行為）：
      blended     連買天數排名 + 價格漲幅排名各占一半（既有預設邏輯）
      streak_only 純依連買天數排名，價格漲幅不影響排序——回測用，隔離「法人連買」
                  本身的貢獻，不被「已經漲多少」污染
      price_only  純依價格漲幅排名，連買天數不影響排序——回測用，隔離「價格動能」
                  本身的貢獻，用來跟 streak_only／blended 對照，才回答得了「籌碼資訊
                  是否真的有額外貢獻」這個問題（見 2026-07-18 bug-reports.md 討論）
    """
    if weight_mode not in _CONTINUATION_WEIGHT_MODES:
        raise ValueError(f"weight_mode 必須是 {_CONTINUATION_WEIGHT_MODES} 之一，收到 {weight_mode!r}")
    if not candidates:
        return []
    streak_ranks = percentile_ranks([row.get(streak_key, 0) for row in candidates])
    price_ranks = percentile_ranks([row.get("price_cum_pct") or 0 for row in candidates])
    if weight_mode == "streak_only":
        combined = streak_ranks
    elif weight_mode == "price_only":
        combined = price_ranks
    else:
        combined = [s + p for s, p in zip(streak_ranks, price_ranks)]
    scored = list(zip(candidates, combined))
    scored.sort(key=lambda item: -item[1])
    ranked = [row for row, _ in scored]
    return ranked[:limit] if limit is not None else ranked


def rank_joint_buy_candidates(candidates: list[dict], limit: int = 30) -> list[dict]:
    """法人同步觀察共同排行，避免 UI 與回測各自維護不同排序。"""
    ranked = sorted(
        [row for row in candidates if is_joint_buy_signal(row)],
        key=lambda row: (
            -(row.get("both_streak") or 0),
            -(row.get("institutional_flow_ratio_pct") or 0),
            -(row.get("price_cum_pct") or 0),
        ),
    )
    return ranked[:limit]

_DB_PATH = "data/screener.db"
_UNIVERSE_PATH = "data/stock_universe.csv"
_ALL_NAMES_PATH = "data/stock_names.csv"


def _load_name_map() -> dict:
    result: dict = {}
    try:
        df = pd.read_csv(_ALL_NAMES_PATH, dtype=str, encoding="utf-8-sig")
        result.update(df.set_index("stock_id")["stock_name"].to_dict())
    except Exception:
        pass
    try:
        df2 = pd.read_csv(_UNIVERSE_PATH, usecols=["stock_id", "stock_name"], dtype=str)
        result.update(df2.set_index("stock_id")["stock_name"].to_dict())
    except Exception:
        pass
    return result


def _load_meta_map() -> dict:
    try:
        df = pd.read_csv(_UNIVERSE_PATH, usecols=["stock_id", "meta_sector"], dtype=str)
        return df.set_index("stock_id")["meta_sector"].to_dict()
    except Exception:
        return {}


def _load_exchange_map() -> dict:
    try:
        all_cols = pd.read_csv(_UNIVERSE_PATH, nrows=0).columns.tolist()
        if "exchange" not in all_cols:
            return {}
        df = pd.read_csv(_UNIVERSE_PATH, usecols=["stock_id", "exchange"], dtype=str)
        return df.set_index("stock_id")["exchange"].to_dict()
    except Exception:
        return {}


def _calc_streak(series: pd.Series) -> int:
    """回傳序列尾端連續正值天數（序列應按日期升序排列）。"""
    streak = 0
    for v in reversed(series.tolist()):
        if v is not None and v > 0:
            streak += 1
        else:
            break
    return streak


def _calc_cum_pct(change_pcts: list) -> float:
    """複利計算一段期間的累積漲跌幅（%）。用複利而非單純加總，避免長區間誤差。"""
    f = 1.0
    for pct in change_pcts:
        if pct is not None:
            f *= (1 + pct / 100)
    return round((f - 1) * 100, 2)


def scan_institutional(
    trade_date: str,
    lookback: int = 20,
    foreign_streak: int = 0,
    trust_streak: int = 0,
    both_streak: int = 0,
    min_foreign_net: int = 0,
    min_trust_net: int = 0,
    min_total_net: int = 0,
    cum_foreign_net: int = 0,
    cum_trust_net: int = 0,
    min_price_cum_pct: float = 0.0,
    price_window: int = 10,
    sort_by: str = "total_net",
    db_path: str = _DB_PATH,
) -> List[Dict[str, Any]]:
    """
    法人買進篩選，回傳符合條件的股票清單。

    Parameters
    ----------
    trade_date        : 目標日期 'YYYY-MM-DD'
    lookback          : 往回抓幾個交易日的法人資料（用於計算連買天數與累計）
    foreign_streak    : 外資連買 ≥ N 日（0 = 不限）
    trust_streak      : 投信連買 ≥ N 日（0 = 不限）
    both_streak       : 外資+投信同時連買 ≥ N 日（0 = 不限）
    min_foreign_net   : 今日外資買超門檻（股，0 = 不限）
    min_trust_net     : 今日投信買超門檻（股，0 = 不限）
    min_total_net     : 今日三大合計門檻（股，0 = 不限）
    cum_foreign_net   : lookback 天累計外資門檻（股，0 = 不限）
    cum_trust_net     : lookback 天累計投信門檻（股，0 = 不限）
    min_price_cum_pct : price_window 天股價累積漲幅門檻（%，0 = 不限）——用複利累積漲幅，
                        不是連續上漲天數，這樣像「兩週漲快一倍但中間偶有拉回」的個股不會被
                        嚴格的連漲天數篩掉。純外資連買、股價卻沒有實際反應的雜訊會被濾掉
                        （例如被動式資金流入但個股股本大、買超不影響股價的大型股）。
    price_window      : 股價累積漲幅要看幾天（預設 10，約兩週）
    sort_by           : 排序欄位，可選 total_net / foreign_net / trust_net /
                        foreign_streak / trust_streak / both_streak /
                        cum_foreign / cum_trust / price_cum_pct

    Returns
    -------
    list of dict，每筆含：
        stock_id, date,
        foreign_net, trust_net, dealer_net, total_net,  ← 今日
        foreign_streak, trust_streak, both_streak,
        cum_foreign, cum_trust,                          ← lookback 天累計
        close, change_pct,                                ← 今日行情（若有）
        price_cum_pct                                     ← price_window 天股價累積漲幅（若有行情資料）
    """
    con = duckdb.connect(db_path, read_only=True)

    # 若目標日無法人資料，自動 fallback 到最新有資料的日期
    latest_row = con.execute(f"""
        SELECT MAX(date) FROM institutional WHERE date <= '{trade_date}'
    """).fetchone()
    latest_inst_date = str(latest_row[0])[:10] if latest_row and latest_row[0] else None
    if not latest_inst_date:
        logger.warning("scan_institutional: 無任何法人資料")
        con.close()
        return []
    if latest_inst_date != trade_date:
        logger.info("法人資料尚未發布，使用最新日期 %s（請求 %s）", latest_inst_date, trade_date)

    # 取每支股票最近 lookback 筆法人資料。
    # 用 per-stock QUALIFY ROW_NUMBER，不要用全域 LIMIT——全域 LIMIT + ORDER BY stock_id
    # 會讓低號股吃滿配額、把高號股（大量 TPEx）整批截掉，隨歷史累積漸進式漏股。
    inst_df = con.execute(f"""
        SELECT stock_id, date, foreign_net, trust_net, dealer_net, total_net
        FROM institutional
        WHERE date <= '{latest_inst_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) <= {lookback}
    """).df()

    # 行情：優先用目標日，fallback 到最新法人日
    try:
        price_df = con.execute(f"""
            SELECT stock_id, close, change_pct, volume
            FROM daily_prices
            WHERE date = '{trade_date}'
        """).df()
    except Exception:
        # 舊測試資料庫可能尚未有 volume 欄；保留向後相容，但不會誤判成有效強訊號。
        price_df = con.execute(f"""
            SELECT stock_id, close, change_pct, NULL::BIGINT AS volume
            FROM daily_prices
            WHERE date = '{trade_date}'
        """).df()
    if price_df.empty:
        try:
            price_df = con.execute(f"""
                SELECT stock_id, close, change_pct, volume
                FROM daily_prices
                WHERE date = '{latest_inst_date}'
            """).df()
        except Exception:
            price_df = con.execute(f"""
                SELECT stock_id, close, change_pct, NULL::BIGINT AS volume
                FROM daily_prices
                WHERE date = '{latest_inst_date}'
            """).df()

    # 股價 price_window 天累積漲幅：每支股票各自最近 N 個交易日的 change_pct，
    # 用來算複利累積漲幅（不是連續上漲天數，見函式 docstring）。
    price_window_df = con.execute(f"""
        SELECT stock_id, date, change_pct
        FROM daily_prices
        WHERE date <= '{latest_inst_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) <= {price_window}
    """).df()

    con.close()
    trade_date = latest_inst_date  # 掃描基準改為有資料的最新日

    if inst_df.empty:
        logger.warning("scan_institutional: 無法人資料 (%s)", trade_date)
        return []

    inst_df["date"] = pd.to_datetime(inst_df["date"])

    # 各交易所發布日可能不同步（例：TPEx 已出今天、TWSE 還停在昨天，或反之）。
    # 用「表裡最近兩個交易日」當可接受的錨點集合：每支股票取自己最新一筆，
    # 只要它的最新日落在這兩天內就算「今日」——讓 TWSE/TPEx 不同步時兩邊都不漏，
    # 又不會把停牌/下市（最新資料是好幾天前）的股票用陳舊資料拉進來。
    anchor_dates = set(sorted(inst_df["date"].unique())[-2:])

    price_map: dict = {}
    if not price_df.empty:
        price_map = price_df.set_index("stock_id")[["close", "change_pct", "volume"]].to_dict("index")

    price_cum_map: dict = {}
    if not price_window_df.empty:
        for psid, pgrp in price_window_df.groupby("stock_id"):
            pgrp = pgrp.sort_values("date")
            price_cum_map[str(psid)] = _calc_cum_pct(pgrp["change_pct"].tolist())

    name_map = _load_name_map()
    meta_map = _load_meta_map()
    exchange_map = _load_exchange_map()
    results = []

    for sid, grp in inst_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        # 每支股票取自己最新一筆當「今日」；最新日必須落在錨點集合內
        # （否則是停牌/下市的陳舊資料，跳過）
        today = grp.iloc[-1]
        stock_date = today["date"]
        if stock_date not in anchor_dates:
            continue

        f_net = today["foreign_net"]
        t_net = today["trust_net"]
        d_net = today["dealer_net"]
        tot   = today["total_net"]

        # ── 今日單日門檻 ─────────────────────────────────────────
        if min_foreign_net and (f_net is None or f_net < min_foreign_net):
            continue
        if min_trust_net and (t_net is None or t_net < min_trust_net):
            continue
        if min_total_net and (tot is None or tot < min_total_net):
            continue

        # ── 連買天數（只用 lookback 窗口內的資料，到該股自己的最新日為止）──
        window = grp.tail(lookback)

        f_streak = _calc_streak(window["foreign_net"])
        t_streak = _calc_streak(window["trust_net"])

        # both_streak：外資+投信同日皆買超的連續天數
        b_streak = 0
        for _, row in window.iloc[::-1].iterrows():
            if row["foreign_net"] is not None and row["foreign_net"] > 0 \
               and row["trust_net"] is not None and row["trust_net"] > 0:
                b_streak += 1
            else:
                break

        if foreign_streak and f_streak < foreign_streak:
            continue
        if trust_streak and t_streak < trust_streak:
            continue
        if both_streak and b_streak < both_streak:
            continue

        # ── 累計金額 ─────────────────────────────────────────────
        cum_f = int(window["foreign_net"].fillna(0).sum())
        cum_t = int(window["trust_net"].fillna(0).sum())

        if cum_foreign_net and cum_f < cum_foreign_net:
            continue
        if cum_trust_net and cum_t < cum_trust_net:
            continue

        # ── 股價累積漲幅 ─────────────────────────────────────────
        price_cum_pct = price_cum_map.get(str(sid))

        if min_price_cum_pct and (price_cum_pct is None or price_cum_pct < min_price_cum_pct):
            continue

        # ── 整合行情 ─────────────────────────────────────────────
        px = price_map.get(str(sid), {})
        volume = px.get("volume")
        volume = None if volume is None or pd.isna(volume) else int(volume)
        joint_net = max(0, int(f_net or 0) + int(t_net or 0))
        flow_ratio_pct = (
            round(joint_net / (volume * 1000) * 100, 4)
            if volume and volume > 0 else None
        )

        results.append({
            "stock_id":       str(sid),
            "stock_name":     name_map.get(str(sid), ""),
            "meta_sector":    meta_map.get(str(sid), ""),
            "exchange":       exchange_map.get(str(sid), ""),
            "date":           str(stock_date)[:10],
            "foreign_net":    int(f_net) if f_net is not None else None,
            "trust_net":      int(t_net) if t_net is not None else None,
            "dealer_net":     int(d_net) if d_net is not None else None,
            "total_net":      int(tot)   if tot   is not None else None,
            "foreign_streak": f_streak,
            "trust_streak":   t_streak,
            "both_streak":    b_streak,
            "cum_foreign":    cum_f,
            "cum_trust":      cum_t,
            "close":          px.get("close"),
            "change_pct":     px.get("change_pct"),
            "volume":         volume,
            "institutional_flow_ratio_pct": flow_ratio_pct,
            "price_cum_pct":  price_cum_pct,
        })

    # 排序
    _sort_key = {
        "total_net":      lambda x: -(x["total_net"]   or 0),
        "foreign_net":    lambda x: -(x["foreign_net"] or 0),
        "trust_net":      lambda x: -(x["trust_net"]   or 0),
        "foreign_streak": lambda x: -x["foreign_streak"],
        "trust_streak":   lambda x: -x["trust_streak"],
        "both_streak":    lambda x: -x["both_streak"],
        "cum_foreign":    lambda x: -x["cum_foreign"],
        "cum_trust":      lambda x: -x["cum_trust"],
        "price_cum_pct":  lambda x: -(x["price_cum_pct"] or 0),
    }
    key_fn = _sort_key.get(sort_by, _sort_key["total_net"])
    results.sort(key=key_fn)

    logger.info(
        "法人篩選 %s：%d 檔符合條件（lookback=%d）",
        trade_date, len(results), lookback,
    )
    return results
