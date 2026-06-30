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
_DBL_PRICE_DIFF  = 0.05   # 雙底/頂兩端差距 < 5%（原3%太嚴）
_DBL_BOUNCE      = 0.08   # 中間反彈/拉回 >= 8%（原5%太小）
_DBL_VOL_CONFIRM = 1.5    # 突破頸線量確認（原1.2）
_TRI_VOL_CONFIRM = 1.8    # 三角突破量確認（原1.3）
_BRK_VOL_CONFIRM = 1.5    # 60日突破量確認
_BOX_RANGE       = 0.08   # 箱型整理最大振幅 8%
_IHS_PRICE_DIFF  = 0.15   # 頭肩底左右肩差距 < 15%
_IHS_VOL_CONFIRM = 1.5    # 頭肩底突破頸線量確認


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
    雙底：近60日兩個局部低點（差<5%，間距≥8根），中間反彈≥8%（頸線），
    第一低點前有下跌趨勢（前高≥低點×1.10），今日突破頸線 + 量>20MA×1.5。
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

            # 兩低點至少相距 8 根（避免同一個底被計兩次）
            if i2 - i1 < 8:
                continue

            # 兩低點差距 < 5%
            if abs(low1 - low2) / min(low1, low2) >= _DBL_PRICE_DIFF:
                continue

            # 第一個底之前要有過較高的價格（確認先有下跌趨勢，需高 10% 以上）
            if i1 > 0 and seg[:i1].max() < seg[i1] * 1.10:
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

            anchor = float(neckline)
            stop   = round(anchor * 0.97, 2)
            target = round(anchor + (anchor - float(min(low1, low2))), 2)
            rr     = round((target - anchor) / (anchor - stop), 2)
            return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}

    return None


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

            anchor = float(neckline)
            top_avg = float((high1 + high2) / 2)
            stop   = round(anchor * 1.03, 2)
            target = round(anchor - (top_avg - anchor), 2)
            rr     = round((anchor - target) / (stop - anchor), 2) if stop > anchor else 0.0
            return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}

    return None


def detect_triangle_up(df: pd.DataFrame) -> bool:
    """
    三角向上突破：近20日壓力局部高點連線斜率<0 + 支撐局部低點連線斜率>0（對稱三角），
    整理期量縮（後10日均量 ≤ 前10日×1.1），今日必須上漲且收盤突破壓力外推值 + 量>20MA×1.8。
    加上 MA50 上升趨勢過濾：收盤需在 MA50 之上才算有效突破。
    """
    if len(df) < 21:
        return False

    # MA50 上升趨勢過濾：確保不在空頭整理中
    if len(df) >= 51:
        ma50 = df['close'].iloc[-51:-1].mean()
        if df['close'].iloc[-1] < ma50 * 0.98:
            return None

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

    # 突破日必須是上漲日（排除下跌日假突破）
    if today['close'] <= df['close'].iloc[-2]:
        return False

    # 整理期量能應收縮（後10日均量不超過前10日均量 × 1.1）
    vol_early = volume[-21:-11].mean()
    vol_late  = volume[-11:-1].mean()
    if vol_early > 0 and vol_late > vol_early * 1.1:
        return False

    vol_ma20 = volume[-21:-1].mean()
    if vol_ma20 > 0 and volume[-1] < vol_ma20 * _TRI_VOL_CONFIRM:
        return None

    anchor    = float(today['close'])
    tri_range = float(highs.max() - lows.min())
    stop      = round(anchor * 0.97, 2)
    target    = round(anchor + tri_range, 2)
    rr        = round((target - anchor) / (anchor - stop), 2) if anchor > stop else 0.0
    return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}


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
        return None

    anchor    = float(today['close'])
    tri_range = float(highs.max() - lows.min())
    stop      = round(anchor * 1.03, 2)
    target    = round(anchor - tri_range, 2)
    rr        = round((anchor - target) / (stop - anchor), 2) if stop > anchor else 0.0
    return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}


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
            anchor      = float(breakout_close)
            sixty_d_low = float(close[hist_start:day_idx].min())
            stop        = round(anchor * 0.97, 2)
            target      = round(anchor + (anchor - sixty_d_low) * 0.5, 2)
            rr          = round((target - anchor) / (anchor - stop), 2) if anchor > stop else 0.0
            return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}

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

    # 建立 peak→trough 波段（按時序），記錄波谷收盤作為停損依據
    swings: list[tuple[float, float, float, float]] = []  # (pullback_pct, vol_avg, peak_close, trough_close)
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
        swings.append((pullback, vol_avg, pk_close, tr_close))

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
        return None

    last_pullback_pct = recent[-1][0]
    anchor = float(today['close'])
    # 停損設在最後一個波谷下方 1%，避免 3% 固定停損過緊（VCP 回檔通常 10-20%）
    last_trough_close = recent[-1][3]
    stop = round(max(last_trough_close * 0.99, anchor * 0.85), 2)  # cap: 不超過 15% 下方
    target = round(anchor * (1.0 + last_pullback_pct), 2)
    rr_denom = anchor - stop
    rr = round((target - anchor) / rr_denom, 2) if rr_denom > 0 else 0.0
    return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}


def detect_inverse_hs(df: pd.DataFrame) -> dict | None:
    """
    頭肩底：近70日找3個局部低點（頭最低，左右肩高度相近），
    兩肩之間各有一個峰值形成頸線，今日收盤突破頸線投影值 + 量確認 + 上漲日。

    條件：
    - 左右肩差距 < 15%
    - 頭比兩肩都低
    - 左肩之前有更高價格（確認先有下跌趨勢）
    - 右肩距今不超過 20 根
    - 今日突破頸線延伸值，且當日上漲
    - 量 > 20MA × 1.5
    """
    if len(df) < 35:
        return None

    close  = df['close'].values
    volume = df['volume'].values
    window = min(70, len(close))
    seg    = close[-window:]
    seg_n  = len(seg)

    minima   = _local_minima(seg, radius=3)
    if len(minima) < 3:
        return None

    maxima_all = _local_maxima(seg, radius=2)
    vol_ma20   = volume[-21:-1].mean() if len(volume) >= 21 else volume[:-1].mean()

    # 只取最近 6 個低點組合，避免 O(n³) 爆炸
    cands = minima[-6:] if len(minima) > 6 else minima

    for a in range(len(cands) - 2):
        for b in range(a + 1, len(cands) - 1):
            for c in range(b + 1, len(cands)):
                ls_idx, hd_idx, rs_idx = cands[a], cands[b], cands[c]
                ls, hd, rs = seg[ls_idx], seg[hd_idx], seg[rs_idx]

                if min(ls, hd, rs) <= 0:
                    continue

                # 頭必須比兩肩都低
                if not (hd < ls and hd < rs):
                    continue

                # 左右肩高度相近（差距 < 15%）
                if abs(ls - rs) / max(ls, rs) > _IHS_PRICE_DIFF:
                    continue

                # 各特徵間最少相距 5 根
                if hd_idx - ls_idx < 5 or rs_idx - hd_idx < 5:
                    continue

                # 右肩要夠新（距今 ≤ 20 根）
                if rs_idx < seg_n - 20:
                    continue

                # 左肩前需有更高價格確認下跌趨勢
                if ls_idx > 0 and seg[:ls_idx].max() < ls * 1.08:
                    continue

                # 找頸線兩峰
                peaks_left  = [i for i in maxima_all if ls_idx < i < hd_idx]
                peaks_right = [i for i in maxima_all if hd_idx < i < rs_idx]
                if not peaks_left or not peaks_right:
                    continue

                pk1_idx, pk2_idx = peaks_left[-1], peaks_right[0]
                pk1, pk2         = seg[pk1_idx], seg[pk2_idx]

                if pk2_idx == pk1_idx:
                    continue

                # 頸線斜率延伸至今日（第 seg_n 根）
                neckline_slope = (pk2 - pk1) / (pk2_idx - pk1_idx)
                neckline_today = pk1 + neckline_slope * (seg_n - pk1_idx)

                # 今日必須突破頸線且為上漲日
                if close[-1] <= neckline_today:
                    continue
                if close[-1] <= close[-2]:
                    continue

                # 量確認
                if vol_ma20 > 0 and volume[-1] < vol_ma20 * _IHS_VOL_CONFIRM:
                    continue

                head_depth = max(pk1, pk2) - hd
                anchor     = float(neckline_today)
                stop       = round(float(rs) * 0.98, 2)
                target     = round(anchor + head_depth, 2)
                rr_denom   = anchor - stop
                rr         = round((target - anchor) / rr_denom, 2) if rr_denom > 0 else 0.0
                return {"anchor": anchor, "stop": stop, "target": target, "rr": rr}

    return None


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
        if detect_inverse_hs(grp):
            patterns.append("頭肩底")
            pattern_score += 3
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


def scan_and_track(date_str: str, db_path: str = _DB_PATH) -> list[dict]:
    """
    新訊號掃描 + 歷史訊號追蹤。

    今日觸發的新訊號寫入 pattern_signals；
    歷史 active 訊號依停損/目標/時間更新狀態；
    回傳所有 active 訊號（同 scan_patterns 格式，加上 anchor/stop/target/rr/signal_date/days_held）。
    """
    con = duckdb.connect(db_path)

    con.execute("""
        CREATE TABLE IF NOT EXISTS pattern_signals (
            stock_id     VARCHAR NOT NULL,
            pattern      VARCHAR NOT NULL,
            signal_date  DATE    NOT NULL,
            anchor       DOUBLE,
            stop         DOUBLE,
            target       DOUBLE,
            rr           DOUBLE,
            status       VARCHAR DEFAULT 'active',
            last_check   DATE,
            days_held    INTEGER DEFAULT 0,
            consec_below INTEGER DEFAULT 0,
            PRIMARY KEY (stock_id, pattern, signal_date)
        )
    """)

    # ── 載入資料（同 scan_patterns）──────────────────────────────────────
    price_df = con.execute("""
        SELECT stock_id, date, open, high, low, close, volume, change_pct
        FROM daily_prices
        WHERE date <= ?
          AND date >= CAST(? AS DATE) - INTERVAL '90 days'
        ORDER BY stock_id, date
    """, [date_str, date_str]).df()

    inst_df = con.execute("""
        SELECT stock_id, date, foreign_net, trust_net
        FROM institutional
        WHERE date <= ?
          AND date >= CAST(? AS DATE) - INTERVAL '20 days'
        ORDER BY stock_id, date
    """, [date_str, date_str]).df()

    sh_df = con.execute("""
        WITH latest AS (SELECT MAX(date) AS d FROM shareholder)
        SELECT s.stock_id, s.lv12_15_pct, s.streak
        FROM shareholder s, latest l WHERE s.date = l.d
    """).df() if con.execute("SELECT COUNT(*) FROM shareholder").fetchone()[0] > 0 else pd.DataFrame()

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

    if price_df.empty:
        con.close()
        logger.warning("scan_and_track: 無行情資料 (%s)", date_str)
        return []

    try:
        univ_cols = ["stock_id", "stock_name", "meta_sector"]
        all_cols = pd.read_csv(_UNIVERSE_PATH, nrows=0).columns.tolist()
        if "exchange" in all_cols:
            univ_cols.append("exchange")
        universe = pd.read_csv(_UNIVERSE_PATH, dtype=str, usecols=univ_cols)
        name_map = universe.set_index("stock_id")[univ_cols[1:]].to_dict("index")
    except Exception:
        name_map = {}

    price_df = price_df.groupby("stock_id").tail(65).reset_index(drop=True)
    price_df["date"] = pd.to_datetime(price_df["date"])
    target_date = pd.to_datetime(date_str)

    inst_df = inst_df.groupby("stock_id").tail(10).reset_index(drop=True)

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

    inst_by_stock = {sid: grp.reset_index(drop=True)
                     for sid, grp in inst_df.groupby("stock_id")}

    # ── 偵測今日新訊號並寫入 DB ───────────────────────────────────────────
    _ALL_DETECTORS = [
        ("雙底",    detect_double_bottom),
        ("頭肩底",  detect_inverse_hs),
        ("三角突破", detect_triangle_up),
        ("60日突破", detect_breakout_confirm),
        ("VCP突破",  detect_vcp),
        ("雙頂",    detect_double_top),
        ("三角跌破", detect_triangle_down),
    ]
    _BEARISH_PATTERNS = {"雙頂", "三角跌破"}

    today_close_map: dict[str, tuple] = {}  # sid -> (close, volume)

    for sid, grp in price_df.groupby("stock_id"):
        grp = grp.sort_values("date").reset_index(drop=True)
        today_rows = grp[grp["date"] == target_date]
        if today_rows.empty or len(grp) < 20:
            continue

        today_row = today_rows.iloc[0]
        today_close_map[str(sid)] = (float(today_row["close"]), float(today_row["volume"]))

        for pattern_name, detector in _ALL_DETECTORS:
            info = detector(grp)
            if info:
                con.execute("""
                    INSERT INTO pattern_signals
                        (stock_id, pattern, signal_date, anchor, stop, target, rr,
                         status, last_check, days_held, consec_below)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, 0, 0)
                    ON CONFLICT (stock_id, pattern, signal_date) DO NOTHING
                """, [str(sid), pattern_name, date_str,
                      info["anchor"], info["stop"], info["target"], info["rr"], date_str])

    # ── 更新所有 active 訊號狀態 ──────────────────────────────────────────
    active_df = con.execute("""
        SELECT stock_id, pattern, signal_date, anchor, stop, target, days_held, consec_below
        FROM pattern_signals WHERE status = 'active'
    """).df()

    for _, sig in active_df.iterrows():
        sid = str(sig["stock_id"])
        if sid not in today_close_map:
            continue

        today_close, _ = today_close_map[sid]
        signal_date = pd.to_datetime(sig["signal_date"])
        days_held = int((target_date - signal_date).days)
        is_bearish = sig["pattern"] in _BEARISH_PATTERNS

        anchor = float(sig["anchor"])
        is_adverse = today_close > anchor if is_bearish else today_close < anchor
        consec_below = int(sig["consec_below"]) + 1 if is_adverse else 0

        stop   = float(sig["stop"])
        target = float(sig["target"])

        if is_bearish:
            hard_fail  = today_close > stop
            hit_target = today_close <= target
        else:
            hard_fail  = today_close < stop
            hit_target = today_close >= target

        if hard_fail or consec_below >= 2:
            new_status = "failed"
        elif hit_target:
            new_status = "hit_target"
        elif days_held > 20:
            new_status = "expired"
        else:
            new_status = "active"

        con.execute("""
            UPDATE pattern_signals
            SET status = ?, last_check = ?, days_held = ?, consec_below = ?
            WHERE stock_id = ? AND pattern = ? AND signal_date = ?
        """, [new_status, date_str, days_held, consec_below,
              sid, sig["pattern"], str(sig["signal_date"])])

    # ── 取得所有仍 active 的訊號 ──────────────────────────────────────────
    active_final = con.execute("""
        SELECT stock_id, pattern, signal_date, anchor, stop, target, rr, days_held
        FROM pattern_signals
        WHERE status = 'active'
        ORDER BY signal_date DESC, rr DESC
    """).df()
    con.close()

    if active_final.empty:
        return []

    # 每支股票的 active 訊號列表（最近 + 最高 rr 優先）
    stock_to_signals: dict[str, list] = {}
    for _, sig in active_final.iterrows():
        sid = str(sig["stock_id"])
        if sid not in stock_to_signals:
            stock_to_signals[sid] = []
        stock_to_signals[sid].append(dict(sig))

    # ── 建立顯示資料 ──────────────────────────────────────────────────────
    results = []

    for sid_grp, grp in price_df.groupby("stock_id"):
        sid = str(sid_grp)
        if sid not in stock_to_signals:
            continue

        grp = grp.sort_values("date").reset_index(drop=True)
        today_rows = grp[grp["date"] == target_date]
        if today_rows.empty:
            continue

        today = today_rows.iloc[0]
        change_pct = float(today.get("change_pct", 0) or 0)

        vol_ma20  = grp["volume"].iloc[-21:-1].mean() if len(grp) >= 21 else grp["volume"].iloc[:-1].mean()
        vol_ratio = round(float(today["volume"]) / vol_ma20, 2) if vol_ma20 > 0 else 1.0

        stock_inst  = inst_by_stock.get(sid_grp, pd.DataFrame())
        vp_score    = _calc_vol_price_score(grp["close"], grp["volume"])
        chips_score = _calc_chips_score(stock_inst)

        sigs        = stock_to_signals[sid]
        all_patterns = [s["pattern"] for s in sigs]
        primary     = sigs[0]

        pattern_score = 0
        for p in all_patterns:
            if p in ("雙底", "三角突破", "60日突破"):
                pattern_score += 2
            elif p in ("VCP突破", "頭肩底"):
                pattern_score += 3
            elif p in ("雙頂", "三角跌破"):
                pattern_score -= 2

        total_score = vp_score + chips_score + pattern_score

        f_streak  = _calc_streak(stock_inst["foreign_net"]) if not stock_inst.empty and "foreign_net" in stock_inst else 0
        t_streak  = _calc_streak(stock_inst["trust_net"])   if not stock_inst.empty and "trust_net"   in stock_inst else 0

        sh_info   = sh_map.get(sid, {})
        lv_pct    = sh_info.get("lv12_15_pct")
        sh_streak = sh_info.get("streak", 0)
        m5d_pct   = margin_map.get(sid, 0.0)

        comp = calc_composite_score(
            foreign_streak=f_streak,
            trust_streak=t_streak,
            patterns=all_patterns,
            vol_ratio=vol_ratio,
            lv12_15_pct=lv_pct,
            sh_streak=sh_streak,
            margin_alert_pct=m5d_pct,
            margin_divergence=False,
        )

        info = name_map.get(sid, {})

        results.append({
            "stock_id":            sid,
            "stock_name":          info.get("stock_name", ""),
            "meta_sector":         info.get("meta_sector", ""),
            "exchange":            info.get("exchange", ""),
            "close_price":         round(float(grp["close"].iloc[-1]), 2),
            "change_pct":          round(change_pct, 2),
            "vol_ratio":           vol_ratio,
            "score":               total_score,
            "composite_score":     comp,
            "patterns":            all_patterns,
            "inst_streak_foreign": f_streak,
            "inst_streak_trust":   t_streak,
            "lv12_15_pct":         lv_pct,
            "sh_streak":           sh_streak,
            "closes":              grp["close"].iloc[-30:].tolist(),
            "signal_date":         str(primary["signal_date"])[:10],
            "days_held":           int(primary["days_held"]),
            "anchor":              float(primary["anchor"]),
            "stop":                float(primary["stop"]),
            "target":              float(primary["target"]),
            "rr":                  float(primary["rr"]),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("scan_and_track %s: %d 檔 active 訊號", date_str, len(results))
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
        elif p == "頭肩底":      pattern_pts += 28
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


def backtest_patterns_rr(
    days: int = 100,
    hold_days: int = 20,
    mfe_qual: float = 30.0,
    max_dd: float | None = None,
    start_date: str | None = None,
    db_path: str = _DB_PATH,
) -> None:
    """
    形態回測：停損 + 時間出場，追蹤實際後續漲幅與最大回撤。

    進場：訊號日實際收盤（entry_close）
    出場條件：
      1. 收盤回撤超過 max_dd%（若指定）或偵測函數的 stop 價 → 停損
      2. 持倉滿 hold_days → 時間出場
    追蹤指標：
      MFE = 持倉期間最大有利幅度（最多能賺多少）
      MDD = 持倉期間最大不利幅度（最多要扛多少）
      exit_pnl = 出場時實際損益%
    去重：同一股票同一形態，距上次訊號 < hold_days 天則跳過。
    """
    _BEARISH = {"雙頂", "三角跌破"}
    _DETECTORS = [
        ("雙底",    detect_double_bottom),
        ("頭肩底",  detect_inverse_hs),
        ("三角突破", detect_triangle_up),
        ("60日突破", detect_breakout_confirm),
        ("VCP突破",  detect_vcp),
        ("雙頂",    detect_double_top),
        ("三角跌破", detect_triangle_down),
    ]
    _PATTERN_ORDER = ["60日突破", "VCP突破", "頭肩底", "雙底", "三角突破", "雙頂", "三角跌破"]

    print("正在載入價格資料庫...")
    con = duckdb.connect(db_path, read_only=True)
    dates_df = con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date"
    ).df()
    all_prices_df = con.execute(
        "SELECT stock_id, date, close, volume, high, low FROM daily_prices ORDER BY stock_id, date"
    ).df()
    con.close()

    all_prices_df["date"]   = pd.to_datetime(all_prices_df["date"])
    all_prices_df["close"]  = pd.to_numeric(all_prices_df["close"],  errors="coerce")
    all_prices_df["volume"] = pd.to_numeric(all_prices_df["volume"], errors="coerce").fillna(0)

    trading_dates = sorted(pd.to_datetime(dates_df["date"]).tolist())
    if len(trading_dates) <= hold_days:
        print("資料不足，無法回測")
        return

    scan_dates = trading_dates[:-hold_days]
    if days > 0:
        scan_dates = scan_dates[-days:]
    if start_date is not None:
        cutoff = pd.to_datetime(start_date)
        scan_dates = [d for d in scan_dates if d >= cutoff]

    stop_label = f"回撤>{max_dd:.0f}%" if max_dd is not None else "偵測函數stop"
    print(f"掃描期間: {str(scan_dates[0])[:10]} ~ {str(scan_dates[-1])[:10]}  ({len(scan_dates)} 個交易日)")
    print(f"持倉上限: {hold_days} 日  停損條件: {stop_label}  無固定目標")
    print("開始回測...\n")

    price_map: dict[str, pd.DataFrame] = {}
    for sid, grp in all_prices_df.groupby("stock_id"):
        price_map[str(sid)] = grp.sort_values("date").reset_index(drop=True)

    all_trades: list[dict] = []
    n_stocks = len(price_map)

    for tick, (sid, full_grp) in enumerate(price_map.items(), 1):
        if tick % 200 == 0:
            pct = tick / n_stocks * 100
            print(f"  進度: {tick}/{n_stocks} 支 ({pct:.0f}%)  已找到 {len(all_trades)} 筆訊號")

        stock_dates = set(full_grp["date"].tolist())
        common = [d for d in scan_dates if d in stock_dates]
        if not common:
            continue

        # 去重：同 pattern 距上一次訊號 < hold_days → 跳過
        last_signal_dt: dict[str, pd.Timestamp] = {}

        for scan_dt in common:
            mask = full_grp["date"] <= scan_dt
            hist = full_grp[mask].tail(75).reset_index(drop=True)
            if len(hist) < 20:
                continue
            if hist.iloc[-1]["date"] != scan_dt:
                continue

            future = full_grp[full_grp["date"] > scan_dt].head(hold_days)
            if future.empty:
                continue

            entry_close = float(hist.iloc[-1]["close"])

            for pattern_name, detector in _DETECTORS:
                # 去重檢查
                last_dt = last_signal_dt.get(pattern_name)
                if last_dt is not None:
                    gap = (scan_dt - last_dt).days
                    if gap < hold_days:
                        continue

                try:
                    info = detector(hist)
                except Exception:
                    continue

                if not info:
                    continue

                det_stop = float(info["stop"])
                target   = float(info["target"])
                rr_ref   = float(info["rr"])

                is_bearish = pattern_name in _BEARISH

                # 有效停損價：max_dd 指定時用回撤比例，否則用偵測函數值
                if max_dd is not None:
                    if is_bearish:
                        eff_stop = entry_close * (1 + max_dd / 100)
                    else:
                        eff_stop = entry_close * (1 - max_dd / 100)
                else:
                    eff_stop = det_stop

                # 模擬持倉：停損出場或時間到期
                exit_type   = "expired"
                exit_pnl    = 0.0
                mfe         = 0.0   # max favorable excursion
                mdd         = 0.0   # max drawdown（最大不利幅度）
                actual_days = 0

                closes_fwd = future["close"].tolist()
                for j, c in enumerate(closes_fwd, 1):
                    c = float(c)
                    actual_days = j
                    if is_bearish:
                        fav = (entry_close - c) / entry_close * 100
                        adv = (c - entry_close) / entry_close * 100
                    else:
                        fav = (c - entry_close) / entry_close * 100
                        adv = (entry_close - c) / entry_close * 100
                    mfe = max(mfe, fav)
                    mdd = max(mdd, adv)

                    if is_bearish:
                        if c >= eff_stop:
                            exit_type = "stop"
                            exit_pnl  = (entry_close - c) / entry_close * 100
                            break
                    else:
                        if c <= eff_stop:
                            exit_type = "stop"
                            exit_pnl  = (c - entry_close) / entry_close * 100
                            break

                if exit_type == "expired":
                    last_c = float(closes_fwd[-1])
                    exit_pnl = (entry_close - last_c if is_bearish else last_c - entry_close) / entry_close * 100

                last_signal_dt[pattern_name] = scan_dt
                all_trades.append({
                    "signal_date":  str(scan_dt)[:10],
                    "stock_id":     sid,
                    "pattern":      pattern_name,
                    "entry":        entry_close,
                    "stop":         det_stop,
                    "eff_stop":     eff_stop,
                    "target":       target,
                    "rr_ref":       rr_ref,
                    "exit_type":    exit_type,
                    "exit_pnl":     exit_pnl,
                    "mfe":          mfe,
                    "mdd":          mdd,
                    "days_held":    actual_days,
                })

    if not all_trades:
        print("回測期間無訊號")
        return

    df = pd.DataFrame(all_trades)
    out_path = "data/backtest_rr.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    stop_desc = f"回撤>{max_dd:.0f}%停損" if max_dd is not None else "偵測函數stop"
    W  = 116
    hd = "=" * W
    print(f"\n{hd}")
    print(f"  形態回測（{stop_desc}+時間出場）  掃描 {len(scan_dates)} 日  持倉 {hold_days} 日  MFE合格線 ≥{mfe_qual:.0f}%")
    print(f"  總訊號: {len(df)}   明細: {out_path}")
    print(hd)

    fmt = "{:<12} {:>6} {:>8} {:>8} {:>9} {:>9} {:>10} {:>10} {:>9} {:>9}"
    print(fmt.format("形態", "筆數", "停損率", "時間出場", "期望值%", "均獲利%", "均虧損%", f"MFE≥{mfe_qual:.0f}%率", "avgMFE%", "avgMDD%"))
    print("-" * W)

    overall_ev_n = 0.0
    for pat in _PATTERN_ORDER:
        sub = df[df["pattern"] == pat]
        if sub.empty:
            continue
        n       = len(sub)
        wins    = sub[sub["exit_pnl"] > 0]
        losses  = sub[sub["exit_pnl"] <= 0]
        stops   = sub[sub["exit_type"] == "stop"]
        expired = sub[sub["exit_type"] == "expired"]
        qual    = sub[sub["mfe"] >= mfe_qual]
        wr      = len(wins) / n
        sr      = len(stops) / n
        er      = len(expired) / n
        qr      = len(qual) / n
        avg_w   = wins["exit_pnl"].mean()   if not wins.empty   else 0.0
        avg_l   = losses["exit_pnl"].mean() if not losses.empty else 0.0
        ev      = wr * avg_w + (1 - wr) * avg_l
        avg_mfe = sub["mfe"].mean()
        avg_mdd = sub["mdd"].mean()
        overall_ev_n += ev * n
        print(fmt.format(
            pat, n,
            f"{sr*100:.0f}%", f"{er*100:.0f}%",
            f"{ev:+.2f}", f"{avg_w:+.1f}", f"{avg_l:+.1f}",
            f"{qr*100:.0f}%", f"{avg_mfe:+.1f}", f"-{avg_mdd:.1f}",
        ))

    overall_ev = overall_ev_n / len(df)
    print(hd)
    print(f"  綜合期望值: {overall_ev:+.2f}%")
    print(f"  停損率=觸發stop出場  時間出場=到期強制平倉  MFE合格率=持倉期間最大漲幅≥{mfe_qual:.0f}%")
    print(f"  avgMFE=平均最大有利幅度（理論最多賺多少）  avgMDD=平均最大回撤（持倉期間最多要扛多少）")
    print(f"  期望值 = 勝率×均獲利% + 敗率×均虧損%  (>0 表示正期望值系統)")
    print(hd + "\n")

    # 如果有指定 start_date，額外輸出每筆交易明細
    if start_date is not None:
        bullish = df[~df["pattern"].isin(_BEARISH)].copy()
        if not bullish.empty:
            bullish_sorted = bullish.sort_values("signal_date")
            cum = 0.0
            print(f"{'='*100}")
            print(f"  逐筆交易明細（多方型態，{start_date} 起）")
            print(f"{'='*100}")
            fmt2 = "{:<12} {:<6} {:<10} {:>8} {:>9} {:>8} {:>8} {:>8}"
            print(fmt2.format("型態", "代號", "訊號日", "進場價", "損益%", "出場", "MFE%", "累積損益%"))
            print("-" * 100)
            for _, t in bullish_sorted.iterrows():
                cum += t["exit_pnl"]
                exit_icon = "✅" if t["exit_type"] == "stop" and t["exit_pnl"] > 0 else (
                    "❌" if t["exit_type"] == "stop" else (
                    "🎯" if t["exit_pnl"] > 5 else "⏱"))
                print(fmt2.format(
                    t["pattern"], t["stock_id"], t["signal_date"][:10],
                    f"{t['entry']:.1f}",
                    f"{t['exit_pnl']:+.1f}%",
                    exit_icon,
                    f"{t['mfe']:+.1f}%",
                    f"{cum:+.1f}%",
                ))
            print("-" * 100)
            n_win = (bullish["exit_pnl"] > 0).sum()
            print(f"  總筆數: {len(bullish)}  獲利: {n_win}  虧損: {len(bullish)-n_win}  "
                  f"勝率: {n_win/len(bullish)*100:.0f}%  累積損益: {bullish['exit_pnl'].sum():+.1f}%（等權重）")
            print(f"{'='*100}\n")
