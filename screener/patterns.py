"""
量價形態掃描器。
"""
import logging
import duckdb
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"
_UNIVERSE_PATH = "data/stock_universe.csv"

# Score 門檻常數
_VOL_UP   = 1.5
_VOL_DOWN = 0.7
_PRICE_UP   =  0.5   # %
_PRICE_DOWN = -0.5   # %

# 形態偵測常數
_DBL_PRICE_DIFF  = 0.03   # 雙底/頂兩端差距 < 3%
_DBL_BOUNCE      = 0.05   # 中間反彈/拉回 >= 5%
_DBL_VOL_CONFIRM = 1.2    # 突破頸線量確認
_TRI_VOL_CONFIRM = 1.3    # 三角突破量確認
_BRK_VOL_CONFIRM = 1.5    # 60日突破量確認
_BOX_RANGE       = 0.08   # 箱型整理最大振幅 8%


def _calc_streak(series: pd.Series) -> int:
    """計算末端連買(正)或連賣(負)天數。"""
    if series.empty:
        return 0
    values = series.tolist()
    if values[-1] > 0:
        streak = 0
        for v in reversed(values):
            if v > 0:
                streak += 1
            else:
                break
        return streak
    elif values[-1] < 0:
        streak = 0
        for v in reversed(values):
            if v < 0:
                streak += 1
            else:
                break
        return -streak
    return 0


def _calc_vol_price_score(close: pd.Series, volume: pd.Series) -> int:
    """量價得分：量增價漲+2、量增/減價跌-2、量減價漲-1。"""
    if len(close) < 21:
        return 0
    vol_ma20 = volume.iloc[-21:-1].mean()
    if vol_ma20 == 0:
        return 0
    vol_ratio = volume.iloc[-1] / vol_ma20
    prev_close = close.iloc[-2]
    if prev_close == 0:
        return 0
    change_pct = (close.iloc[-1] / prev_close - 1) * 100

    vol_up   = vol_ratio > _VOL_UP
    vol_down = vol_ratio < _VOL_DOWN
    price_up   = change_pct > _PRICE_UP
    price_down = change_pct < _PRICE_DOWN

    if vol_up and price_up:
        return 2
    if (vol_up or vol_down) and price_down:
        return -2
    if vol_down and price_up:
        return -1   # 背離
    return 0


def _calc_chips_score(inst_df: pd.DataFrame) -> int:
    """法人連買/連賣得分（外資上限±5，投信上限±3）。"""
    if inst_df.empty:
        return 0
    score = 0
    if 'foreign_net' in inst_df.columns:
        streak = _calc_streak(inst_df['foreign_net'])
        score += max(-5, min(5, streak))
    if 'trust_net' in inst_df.columns:
        streak = _calc_streak(inst_df['trust_net'])
        score += max(-3, min(3, streak))
    return score


def _local_minima(arr: np.ndarray, radius: int = 3) -> list[int]:
    """找局部最低點：前後 radius 根都比它高。"""
    minima = []
    for i in range(radius, len(arr) - radius):
        if all(arr[i] < arr[i - j] for j in range(1, radius + 1)) and \
           all(arr[i] < arr[i + j] for j in range(1, radius + 1)):
            minima.append(i)
    return minima


def _local_maxima(arr: np.ndarray, radius: int = 3) -> list[int]:
    """找局部最高點：前後 radius 根都比它低。"""
    maxima = []
    for i in range(radius, len(arr) - radius):
        if all(arr[i] > arr[i - j] for j in range(1, radius + 1)) and \
           all(arr[i] > arr[i + j] for j in range(1, radius + 1)):
            maxima.append(i)
    return maxima


def _pivot_trendline(
    arr: np.ndarray, find_peaks: bool, radius: int = 2
) -> tuple[float | None, float | None]:
    """
    連接局部高點（find_peaks=True）或低點（False）的趨勢線。
    用最後兩個 pivot 連線，回傳 (slope, intercept)。
    若 pivot 不足，fallback 到前後兩半的極值連線。
    """
    pivots = _local_maxima(arr, radius) if find_peaks else _local_minima(arr, radius)

    if len(pivots) >= 2:
        x1, x2 = pivots[-2], pivots[-1]
    else:
        half = len(arr) // 2
        if find_peaks:
            x1 = int(np.argmax(arr[:half]))
            x2 = half + int(np.argmax(arr[half:]))
        else:
            x1 = int(np.argmin(arr[:half]))
            x2 = half + int(np.argmin(arr[half:]))

    if x2 == x1:
        return None, None
    slope = (arr[x2] - arr[x1]) / (x2 - x1)
    intercept = arr[x1] - slope * x1
    return slope, intercept


def detect_double_bottom(df: pd.DataFrame) -> bool:
    """
    雙底：近60日兩個局部低點（差<3%），中間反彈≥5%（頸線），
    今日收盤突破頸線 + 量>20MA×1.2。
    """
    if len(df) < 30:
        return False

    close  = df['close'].values
    volume = df['volume'].values
    window = min(60, len(close))
    seg    = close[-window:]
    seg_n  = len(seg)

    minima = _local_minima(seg)
    if len(minima) < 2:
        return False

    vol_ma20 = volume[-21:-1].mean() if len(volume) >= 21 else volume[:-1].mean()

    for a in range(len(minima) - 1):
        for b in range(a + 1, len(minima)):
            i1, i2 = minima[a], minima[b]
            low1, low2 = seg[i1], seg[i2]

            if min(low1, low2) <= 0:
                continue

            # 兩低點差距 < 3%
            if abs(low1 - low2) / min(low1, low2) >= _DBL_PRICE_DIFF:
                continue

            # 中間最高點為頸線
            neckline = seg[i1:i2 + 1].max()
            bounce   = (neckline - min(low1, low2)) / min(low1, low2)
            if bounce < _DBL_BOUNCE:
                continue

            # 第二個底要夠新（離今日不超過 15 根）
            if i2 < seg_n - 15:
                continue

            # 今日收盤突破頸線
            if close[-1] <= neckline:
                continue

            # 量確認
            if vol_ma20 > 0 and volume[-1] < vol_ma20 * _DBL_VOL_CONFIRM:
                continue

            return True

    return False


def detect_double_top(df: pd.DataFrame) -> bool:
    """
    雙頂：近60日兩個局部高點（差<3%），中間拉回≥5%（頸線），
    今日收盤跌破頸線 + 量>20MA×1.2。
    """
    if len(df) < 30:
        return False

    close  = df['close'].values
    volume = df['volume'].values
    window = min(60, len(close))
    seg    = close[-window:]
    seg_n  = len(seg)

    maxima = _local_maxima(seg)
    if len(maxima) < 2:
        return False

    vol_ma20 = volume[-21:-1].mean() if len(volume) >= 21 else volume[:-1].mean()

    for a in range(len(maxima) - 1):
        for b in range(a + 1, len(maxima)):
            i1, i2 = maxima[a], maxima[b]
            high1, high2 = seg[i1], seg[i2]

            if max(high1, high2) <= 0:
                continue

            if abs(high1 - high2) / max(high1, high2) >= _DBL_PRICE_DIFF:
                continue

            neckline = seg[i1:i2 + 1].min()
            pullback = (max(high1, high2) - neckline) / max(high1, high2)
            if pullback < _DBL_BOUNCE:
                continue

            if i2 < seg_n - 15:
                continue

            if close[-1] >= neckline:
                continue

            if vol_ma20 > 0 and volume[-1] < vol_ma20 * _DBL_VOL_CONFIRM:
                continue

            return True

    return False


def detect_triangle_up(df: pd.DataFrame) -> bool:
    """
    三角向上突破：近20日壓力局部高點連線斜率<0 + 支撐局部低點連線斜率>0（對稱三角），
    今日收盤突破壓力趨勢線外推值 + 量>20MA×1.3。
    """
    if len(df) < 21:
        return False

    hist   = df.iloc[-21:-1]   # 20 days before today
    today  = df.iloc[-1]
    volume = df['volume'].values
    close_arr = hist['close'].values
    highs_raw = hist['high'].values if 'high' in hist.columns else close_arr
    lows_raw  = hist['low'].values  if 'low'  in hist.columns else close_arr
    # 若 high/low 全為 NaN（TWSE 日 CSV 無高低欄），以 close 補替
    highs = np.where(np.isnan(highs_raw), close_arr, highs_raw)
    lows  = np.where(np.isnan(lows_raw),  close_arr, lows_raw)

    high_slope, high_intercept = _pivot_trendline(highs, find_peaks=True)
    low_slope, _               = _pivot_trendline(lows,  find_peaks=False)

    if high_slope is None or low_slope is None:
        return False
    if not (high_slope < 0 and low_slope > 0):
        return False

    # 壓力線外推至今日位置（第20根，hist 佔0-19）
    predicted_resistance = high_slope * 20 + high_intercept
    if today['close'] <= predicted_resistance:
        return False

    vol_ma20 = volume[-21:-1].mean()
    if vol_ma20 > 0 and volume[-1] < vol_ma20 * _TRI_VOL_CONFIRM:
        return False

    return True


def detect_triangle_down(df: pd.DataFrame) -> bool:
    """
    下降三角跌破：近20日壓力局部高點連線斜率<0（壓力下降）+ 支撐局部低點連線近乎水平，
    今日收盤跌破支撐趨勢線外推值 + 量>20MA×1.3。
    """
    if len(df) < 21:
        return False

    hist   = df.iloc[-21:-1]
    today  = df.iloc[-1]
    volume = df['volume'].values
    close_arr = hist['close'].values
    highs_raw = hist['high'].values if 'high' in hist.columns else close_arr
    lows_raw  = hist['low'].values  if 'low'  in hist.columns else close_arr
    highs = np.where(np.isnan(highs_raw), close_arr, highs_raw)
    lows  = np.where(np.isnan(lows_raw),  close_arr, lows_raw)

    high_slope, _                     = _pivot_trendline(highs, find_peaks=True)
    low_slope,  low_intercept         = _pivot_trendline(lows,  find_peaks=False)

    if high_slope is None or low_slope is None:
        return False

    # 下降三角：壓力斜率<0，支撐近水平（|low_slope|相對低點均值 < 0.5%/日）
    low_mean = lows.mean()
    if low_mean == 0:
        return False
    low_slope_pct = abs(low_slope) / low_mean * 100
    if not (high_slope < 0 and low_slope_pct < 0.5):
        return False

    predicted_support = low_slope * 20 + low_intercept
    if today['close'] >= predicted_support:
        return False

    vol_ma20 = volume[-21:-1].mean()
    if vol_ma20 > 0 and volume[-1] < vol_ma20 * _TRI_VOL_CONFIRM:
        return False

    return True


def detect_breakout_confirm(df: pd.DataFrame) -> bool:
    """
    60日新高突破確認：過去3個交易日內有一天創60日新高+量>20MA×1.5，
    今日收盤仍守在突破日收盤上方。
    """
    if len(df) < 63:
        return False

    close  = df['close'].values
    volume = df['volume'].values
    n      = len(close)
    vol_ma20 = volume[-21:-1].mean()

    # Check days at indices -4, -3, -2 (past 3 days, not including today)
    for offset in range(-4, -1):
        day_idx = n + offset   # e.g. n-4, n-3, n-2
        breakout_close = close[day_idx]
        breakout_vol   = volume[day_idx]

        # 60-day high strictly before this day
        hist_start = max(0, day_idx - 60)
        sixty_d_high = close[hist_start:day_idx].max()

        if breakout_close <= sixty_d_high:
            continue
        if vol_ma20 > 0 and breakout_vol < vol_ma20 * _BRK_VOL_CONFIRM:
            continue
        # Today holds above breakout close
        if close[-1] >= breakout_close:
            return True

    return False


def detect_box_consolidation(df: pd.DataFrame) -> bool:
    """
    箱型整理：近20日（最高-最低）/最低 < 8%，今日仍在區間內。
    """
    if len(df) < 21:
        return False

    last20      = df['close'].iloc[-21:-1]
    today_close = df['close'].iloc[-1]
    box_high    = last20.max()
    box_low     = last20.min()

    if box_low == 0:
        return False
    if (box_high - box_low) / box_low >= _BOX_RANGE:
        return False

    # Today still inside box (allow 1% tolerance)
    return bool(box_low * 0.99 <= today_close <= box_high * 1.01)


_VCP_WINDOW      = 50    # 觀察視窗（交易日）
_VCP_MIN_WAVES   = 2     # 至少 2 波回檔
_VCP_MAX_RETRACE = 0.80  # 後一波回檔幅度 < 前一波 × 80%
_VCP_VOL_CONFIRM = 2.0   # 突破日量 ≥ 整理均量 × 2.0


def detect_vcp(df: pd.DataFrame) -> bool:
    """
    VCP (Mark Minervini) 三波量縮突破：

    1. 在近50日視窗內找至少2個 peak→trough 回檔波段
    2. 每波回檔幅度 < 前一波 × 80%（逐波收縮）
    3. 每波平均量能 ≤ 前一波（量隨波縮）
    4. 前置上升趨勢確認：整理期首個高點 > 65日前收盤（非下跌途中整理）
    5. 今日收盤突破最後一波峰值
    6. 今日量 ≥ 整理均量 × 2.0
    """
    needed = _VCP_WINDOW + 20
    if len(df) < needed:
        return False

    window = df.iloc[-(needed):-1]    # 整理視窗（不含今日）
    today  = df.iloc[-1]
    closes  = window['close'].values[-_VCP_WINDOW:]
    volumes = window['volume'].values[-_VCP_WINDOW:]

    # 找局部高點 / 低點
    peaks   = _local_maxima(closes, radius=3)
    troughs = _local_minima(closes, radius=3)

    if len(peaks) < _VCP_MIN_WAVES or len(troughs) < 1:
        return False

    # 建立 peak→trough 波段（按時序）
    swings: list[tuple[float, float, float]] = []  # (pullback_pct, vol_avg, peak_close)
    for pk in peaks:
        subsequent_troughs = [t for t in troughs if t > pk]
        if not subsequent_troughs:
            continue
        tr       = subsequent_troughs[0]
        pk_close = closes[pk]
        tr_close = closes[tr]
        pullback = (pk_close - tr_close) / pk_close if pk_close > 0 else 0
        if pullback < 0.02:    # 回檔 < 2% 視為雜訊
            continue
        vol_avg = float(volumes[pk : tr + 1].mean())
        swings.append((pullback, vol_avg, pk_close))

    if len(swings) < _VCP_MIN_WAVES:
        return False

    recent = swings[-_VCP_MIN_WAVES:]

    # 回檔幅度逐波收縮
    pullbacks = [s[0] for s in recent]
    if not all(pullbacks[i] < pullbacks[i - 1] * _VCP_MAX_RETRACE
               for i in range(1, len(pullbacks))):
        return False

    # 量能逐波收縮（寬容 5%）
    vols = [s[1] for s in recent]
    if not all(vols[i] <= vols[i - 1] * 1.05 for i in range(1, len(vols))):
        return False

    # 前置上升趨勢：65日前收盤 < 整理期首個高點（確認非下跌途中）
    prior_close    = df['close'].iloc[-(needed - 5)]   # ~65日前
    first_peak_cls = recent[0][2]
    if prior_close >= first_peak_cls * 0.95:
        return False

    # 突破最後一波峰值
    last_peak_close = recent[-1][2]
    if today['close'] <= last_peak_close:
        return False

    # 突破日量確認
    avg_vol = float(volumes.mean())
    if avg_vol > 0 and today['volume'] < avg_vol * _VCP_VOL_CONFIRM:
        return False

    return True


def scan_patterns(date_str: str, db_path: str = _DB_PATH) -> list[dict]:
    """
    掃描 date_str 當日全市場量價形態。
    回傳有命中任一形態的股票清單，依 score 降序。
    """
    con = duckdb.connect(db_path, read_only=True)

    # Load up to 65 days of price data for all stocks
    price_df = con.execute("""
        SELECT stock_id, date, open, high, low, close, volume, change_pct
        FROM daily_prices
        WHERE date <= ?
          AND date >= CAST(? AS DATE) - INTERVAL '90 days'
        ORDER BY stock_id, date
    """, [date_str, date_str]).df()

    # Load up to 10 days of institutional data
    inst_df = con.execute("""
        SELECT stock_id, date, foreign_net, trust_net
        FROM institutional
        WHERE date <= ?
          AND date >= CAST(? AS DATE) - INTERVAL '20 days'
        ORDER BY stock_id, date
    """, [date_str, date_str]).df()

    # Load latest shareholder data (most recent week)
    sh_df = con.execute("""
        WITH latest AS (SELECT MAX(date) AS d FROM shareholder)
        SELECT s.stock_id, s.lv12_15_pct, s.streak
        FROM shareholder s, latest l WHERE s.date = l.d
    """).df() if con.execute("SELECT COUNT(*) FROM shareholder").fetchone()[0] > 0 else pd.DataFrame()

    # Load margin 5-day change % (latest date vs 5 rows ago per stock)
    margin_df = con.execute("""
        WITH ranked AS (
            SELECT stock_id, margin_balance,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM margin WHERE date <= ?
        )
        SELECT a.stock_id,
               CASE WHEN b.margin_balance > 0
                    THEN (a.margin_balance - b.margin_balance) * 100.0 / b.margin_balance
                    ELSE 0 END AS margin_5d_pct
        FROM ranked a JOIN ranked b ON a.stock_id = b.stock_id
        WHERE a.rn = 1 AND b.rn = 5
    """, [date_str]).df() if con.execute("SELECT COUNT(*) FROM margin").fetchone()[0] > 0 else pd.DataFrame()

    con.close()

    if price_df.empty:
        logger.warning("scan_patterns: 無行情資料 (%s)", date_str)
        return []

    # Load name/sector map
    try:
        univ_cols = ["stock_id", "stock_name", "meta_sector"]
        all_cols = pd.read_csv(_UNIVERSE_PATH, nrows=0).columns.tolist()
        if "exchange" in all_cols:
            univ_cols.append("exchange")
        universe = pd.read_csv(_UNIVERSE_PATH, dtype=str, usecols=univ_cols)
        name_map = universe.set_index("stock_id")[univ_cols[1:]].to_dict("index")
    except Exception:
        name_map = {}

    # Keep only last 65 rows per stock
    price_df = price_df.groupby("stock_id").tail(65).reset_index(drop=True)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target_date = pd.to_datetime(date_str)

    # Keep only last 10 rows of institutional per stock
    inst_df = inst_df.groupby("stock_id").tail(10).reset_index(drop=True)

    # Build lookup maps for shareholder and margin
    sh_map: dict[str, dict] = {}
    if not sh_df.empty:
        for _, r in sh_df.iterrows():
            sh_map[str(r["stock_id"])] = {
                "lv12_15_pct": float(r["lv12_15_pct"]) if r["lv12_15_pct"] is not None else None,
                "streak":      int(r["streak"]) if r["streak"] is not None else 0,
            }

    margin_map: dict[str, float] = {}
    if not margin_df.empty:
        for _, r in margin_df.iterrows():
            margin_map[str(r["stock_id"])] = float(r["margin_5d_pct"]) if r["margin_5d_pct"] is not None else 0.0

    results = []
    inst_by_stock = {sid: grp.reset_index(drop=True)
                     for sid, grp in inst_df.groupby("stock_id")}

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)

        # Must have today's row
        today_rows = grp[grp["date"] == target_date]
        if today_rows.empty or len(grp) < 20:
            continue

        today = today_rows.iloc[0]
        change_pct = float(today.get("change_pct", 0) or 0)

        # Vol ratio
        vol_ma20 = grp["volume"].iloc[-21:-1].mean() if len(grp) >= 21 else grp["volume"].iloc[:-1].mean()
        vol_ratio = round(float(today["volume"]) / vol_ma20, 2) if vol_ma20 > 0 else 1.0

        # Chips data
        stock_inst = inst_by_stock.get(str(sid), pd.DataFrame())

        # Scores
        vp_score    = _calc_vol_price_score(grp["close"], grp["volume"])
        chips_score = _calc_chips_score(stock_inst)

        # Pattern detection
        patterns      = []
        pattern_score = 0

        if detect_double_bottom(grp):
            patterns.append("雙底")
            pattern_score += 2
        if detect_triangle_up(grp):
            patterns.append("三角突破")
            pattern_score += 2
        if detect_breakout_confirm(grp):
            patterns.append("60日突破")
            pattern_score += 2
        if detect_double_top(grp):
            patterns.append("雙頂")
            pattern_score -= 2
        if detect_triangle_down(grp):
            patterns.append("三角跌破")
            pattern_score -= 2
        if detect_vcp(grp):
            patterns.append("VCP突破")
            pattern_score += 3
        if detect_box_consolidation(grp):
            patterns.append("箱型整理")

        if not patterns:
            continue

        total_score = vp_score + chips_score + pattern_score

        info = name_map.get(str(sid), {})

        # Streak info for display
        f_streak = _calc_streak(stock_inst["foreign_net"]) if not stock_inst.empty and "foreign_net" in stock_inst else 0
        t_streak = _calc_streak(stock_inst["trust_net"])   if not stock_inst.empty and "trust_net"   in stock_inst else 0

        # Shareholder & margin data for composite score
        sh_info = sh_map.get(str(sid), {})
        lv_pct   = sh_info.get("lv12_15_pct")
        sh_streak = sh_info.get("streak", 0)
        m5d_pct  = margin_map.get(str(sid), 0.0)

        comp = calc_composite_score(
            foreign_streak=f_streak,
            trust_streak=t_streak,
            patterns=patterns,
            vol_ratio=vol_ratio,
            lv12_15_pct=lv_pct,
            sh_streak=sh_streak,
            margin_alert_pct=m5d_pct,
            margin_divergence=False,
        )

        results.append({
            "stock_id":            str(sid),
            "stock_name":          info.get("stock_name", ""),
            "meta_sector":         info.get("meta_sector", ""),
            "exchange":            info.get("exchange", ""),
            "close_price":         round(float(grp["close"].iloc[-1]), 2),
            "change_pct":          round(change_pct, 2),
            "vol_ratio":           vol_ratio,
            "score":               total_score,
            "composite_score":     comp,
            "patterns":            patterns,
            "inst_streak_foreign": f_streak,
            "inst_streak_trust":   t_streak,
            "lv12_15_pct":         lv_pct,
            "sh_streak":           sh_streak,
            "closes":              grp["close"].iloc[-30:].tolist(),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("scan_patterns %s: 命中 %d 檔", date_str, len(results))
    return results


def calc_composite_score(
    foreign_streak: int,
    trust_streak: int,
    patterns: list[str],
    vol_ratio: float,
    lv12_15_pct: float | None,
    sh_streak: int,
    margin_alert_pct: float,
    margin_divergence: bool,
) -> int:
    """
    綜合評分系統 0-100：
      外資籌碼 25 + 投信籌碼 20 + 形態 25 + 量能 15 + 大戶持倉 15 = 100
      融資警示最多扣 15 分
    """
    # 外資：每連買1日+2，上限25；連賣扣分同規
    f_pts = max(-25, min(25, foreign_streak * 2))

    # 投信：每連買1日+2，上限20
    t_pts = max(-20, min(20, trust_streak * 2))

    # 形態
    pattern_pts = 0
    for p in patterns:
        if p == "雙底":          pattern_pts += 25
        elif p == "三角突破":    pattern_pts += 20
        elif p == "VCP突破":     pattern_pts += 22
        elif p == "60日突破":    pattern_pts += 15
        elif p == "雙頂":        pattern_pts -= 25
        elif p == "三角跌破":    pattern_pts -= 20

    # 量能：vol_ratio > 2.0 → 15, > 1.5 → 10, > 1.2 → 5, < 0.7 → -5
    if vol_ratio >= 2.0:    vol_pts = 15
    elif vol_ratio >= 1.5:  vol_pts = 10
    elif vol_ratio >= 1.2:  vol_pts = 5
    elif vol_ratio < 0.7:   vol_pts = -5
    else:                   vol_pts = 0

    # 大戶持倉：streak × 3 (cap 12) + lv12_15_pct > 60% 加3
    sh_pts = 0
    if sh_streak is not None:
        sh_pts += max(-12, min(12, sh_streak * 3))
    if lv12_15_pct is not None and lv12_15_pct >= 60:
        sh_pts += 3

    # 融資扣分
    margin_pts = 0
    if margin_divergence:
        margin_pts -= 15
    elif margin_alert_pct >= 10:
        margin_pts -= 10
    elif margin_alert_pct >= 5:
        margin_pts -= 5

    raw = f_pts + t_pts + pattern_pts + vol_pts + sh_pts + margin_pts
    # 對應 0-100：基準 50 分，raw 為偏離量
    score = 50 + raw
    return max(0, min(100, score))


def backtest_patterns(days: int = 120, db_path: str = _DB_PATH) -> None:
    """
    跑過去 N 個交易日的形態掃描，輸出各形態 3/5/10 日勝率 + 平均報酬。
    """
    con = duckdb.connect(db_path, read_only=True)
    dates_df = con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT ?",
        [days + 10],
    ).df()
    all_prices_df = con.execute(
        "SELECT stock_id, date, close FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    all_prices_df["date"] = pd.to_datetime(all_prices_df["date"])
    price_map = {
        sid: grp.sort_values("date").reset_index(drop=True)
        for sid, grp in all_prices_df.groupby("stock_id")
    }

    trading_dates = sorted(dates_df["date"].tolist())
    # Leave last 10 trading days for forward return calculation
    scan_dates = trading_dates[:-10][-days:]

    all_signals = []
    for td in scan_dates:
        date_str = str(td)[:10]
        try:
            results = scan_patterns(date_str, db_path=db_path)
            for r in results:
                for p in r["patterns"]:
                    if p == "箱型整理":
                        continue
                    all_signals.append({
                        "signal_date": date_str,
                        "stock_id":    r["stock_id"],
                        "pattern":     p,
                        "r3d": None, "r5d": None, "r10d": None,
                    })
        except Exception as exc:
            logger.debug("backtest skip %s: %s", date_str, exc)

    if not all_signals:
        print("回測期間無形態訊號")
        return

    # Calculate forward returns
    for sig in all_signals:
        sid   = sig["stock_id"]
        sdate = pd.to_datetime(sig["signal_date"])
        grp   = price_map.get(sid)
        if grp is None:
            continue
        today_mask = grp["date"] == sdate
        if not today_mask.any():
            continue
        idx = grp[today_mask].index[0]
        sig_close = float(grp.loc[idx, "close"])
        for n, key in [(3, "r3d"), (5, "r5d"), (10, "r10d")]:
            fut_idx = idx + n
            if fut_idx < len(grp):
                fut_close = float(grp.loc[fut_idx, "close"])
                sig[key] = (fut_close - sig_close) / sig_close * 100

    # Print summary table
    signals_df = pd.DataFrame(all_signals)
    print(f"\n{'='*80}")
    print(f"  形態回測結果（過去 {days} 個交易日）")
    print(f"{'='*80}")
    fmt = "{:<14} {:>5} {:>8} {:>8} {:>8} {:>8} {:>9} {:>9} {:>9}"
    print(fmt.format("形態", "次數", "勝率3d", "均報3d", "勝率5d", "均報5d", "勝率10d", "均報10d", "最大虧損"))
    print("-" * 80)

    for pattern in ["60日突破", "雙底", "三角突破", "雙頂", "三角跌破"]:
        sub = signals_df[signals_df["pattern"] == pattern]
        if sub.empty:
            continue
        row_parts = [pattern, str(len(sub))]
        max_loss = None
        for key in ["r3d", "r5d", "r10d"]:
            vals = sub[key].dropna()
            if vals.empty:
                row_parts += ["─", "─"]
                continue
            win_rate = (vals > 0).mean() * 100
            avg_ret  = vals.mean()
            row_parts += [f"{win_rate:.0f}%", f"{avg_ret:+.1f}%"]
            min_val = vals.min()
            if max_loss is None or min_val < max_loss:
                max_loss = min_val
        row_parts.append(f"{max_loss:+.1f}%" if max_loss is not None else "─")
        print(fmt.format(*row_parts))

    print(f"{'='*80}\n")
