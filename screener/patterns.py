"""
量價形態掃描器。
"""
import logging
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
    change_pct = (close.iloc[-1] / close.iloc[-2] - 1) * 100

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
    三角向上突破：近20日高點斜率<0 + 低點斜率>0，
    今日收盤突破高點趨勢線 + 量>20MA×1.3。
    """
    if len(df) < 21:
        return False

    hist   = df.iloc[-21:-1]   # 20 days before today
    today  = df.iloc[-1]
    volume = df['volume'].values
    highs  = hist['high'].values  if 'high' in hist.columns else hist['close'].values
    lows   = hist['low'].values   if 'low'  in hist.columns else hist['close'].values
    x      = np.arange(len(highs))

    high_slope, high_intercept = np.polyfit(x, highs, 1)
    low_slope,  _              = np.polyfit(x, lows,  1)

    if not (high_slope < 0 and low_slope > 0):
        return False

    # Predicted high trendline at position 20 (today)
    predicted_high = high_slope * 20 + high_intercept
    if today['close'] <= predicted_high:
        return False

    vol_ma20 = volume[-21:-1].mean()
    if vol_ma20 > 0 and volume[-1] < vol_ma20 * _TRI_VOL_CONFIRM:
        return False

    return True


def detect_triangle_down(df: pd.DataFrame) -> bool:
    """
    三角向下跌破：近20日高點斜率<0 + 低點斜率<0，
    今日收盤跌破低點趨勢線 + 量>20MA×1.3。
    """
    if len(df) < 21:
        return False

    hist   = df.iloc[-21:-1]
    today  = df.iloc[-1]
    volume = df['volume'].values
    highs  = hist['high'].values  if 'high' in hist.columns else hist['close'].values
    lows   = hist['low'].values   if 'low'  in hist.columns else hist['close'].values
    x      = np.arange(len(highs))

    high_slope, _              = np.polyfit(x, highs, 1)
    low_slope,  low_intercept  = np.polyfit(x, lows,  1)

    if not (high_slope < 0 and low_slope < 0):
        return False

    predicted_low = low_slope * 20 + low_intercept
    if today['close'] >= predicted_low:
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
