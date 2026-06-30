import numpy as np
import pandas as pd
import pytest
from screener.patterns import _calc_streak, _calc_vol_price_score, _calc_chips_score


def test_streak_consecutive_buy():
    s = pd.Series([100, -50, 200, 300, 400])
    assert _calc_streak(s) == 3   # 最後3日連續正


def test_streak_consecutive_sell():
    s = pd.Series([100, 200, -100, -200, -300])
    assert _calc_streak(s) == -3


def test_streak_zero():
    s = pd.Series([100, 200, 0])
    assert _calc_streak(s) == 0


def _make_price_series(closes, volumes):
    return pd.Series(closes, dtype=float), pd.Series(volumes, dtype=float)


def test_vol_price_score_up():
    # 量增價漲 → +2
    closes = [10.0] * 20 + [10.5]   # 今日漲 5%
    volumes = [1_000_000] * 20 + [2_000_000]  # 今日量 2x 均量
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == 2


def test_vol_price_score_down():
    # 量增價跌 → -2
    closes = [10.0] * 20 + [9.5]
    volumes = [1_000_000] * 20 + [2_000_000]
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == -2


def test_vol_price_score_diverge():
    # 量減價漲（背離）→ -1
    closes = [10.0] * 20 + [10.5]
    volumes = [1_000_000] * 20 + [500_000]   # 量減
    c, v = _make_price_series(closes, volumes)
    assert _calc_vol_price_score(c, v) == -1


def test_chips_score_foreign_streak():
    inst = pd.DataFrame({
        'foreign_net': [100_000, 200_000, 150_000],
        'trust_net': [0, 0, 0],
    })
    # 外資連買 3 日 → +3
    assert _calc_chips_score(inst) == 3


def test_chips_score_both_streaks():
    inst = pd.DataFrame({
        'foreign_net': [100_000, 200_000],
        'trust_net': [50_000, 80_000],
    })
    # 外資連買 2 + 投信連買 2 → +4
    assert _calc_chips_score(inst) == 4


from screener.patterns import detect_double_bottom, detect_double_top


def _make_ohlcv(closes, volumes=None):
    """Build minimal DataFrame for pattern detection."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    return pd.DataFrame({
        'close':  closes,
        'high':   [c * 1.005 for c in closes],
        'low':    [c * 0.995 for c in closes],
        'volume': volumes,
    })


def test_double_bottom_detected():
    # Baseline 100, first low 90 at idx 15, bounce to 97, second low 90.5 at idx 40, today 98 (above neckline)
    closes = (
        [100.0] * 12 +
        [95.0, 92.0, 90.0, 92.0, 94.0] +      # first bottom ~idx 14
        [96.0, 98.0, 98.0, 97.0, 98.0] * 4 +  # bounce / neckline ~98 (9%+ bounce from 90)
        [95.0, 92.0, 90.5, 92.0, 94.0] +      # second bottom ~idx 38
        [95.0, 96.0, 99.0]                     # today breaks neckline
    )
    # Volume spike on breakout day (1.5x+ required with new threshold)
    vols = [1_000_000] * (len(closes) - 1) + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_bottom(df)


def test_double_bottom_not_detected_no_bounce():
    # Two lows but bounce only 2% (< 5%)
    closes = [100.0] * 10 + [90.0, 91.0, 90.5] + [92.0] * 10 + [90.2, 91.0, 92.5]
    df = _make_ohlcv(closes)
    assert detect_double_bottom(df) is False


def test_double_top_detected():
    closes = (
        [90.0] * 12 +
        [95.0, 98.0, 100.0, 98.0, 95.0] +   # first top ~100
        [92.0, 91.0, 91.0, 92.0, 91.0] * 4 +  # pullback / neckline ~91
        [94.0, 97.0, 99.8, 97.0, 94.0] +   # second top ~99.8
        [92.0, 91.0, 90.0]                  # today breaks neckline downward
    )
    vols = [1_000_000] * (len(closes) - 1) + [2_000_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_top(df)


def test_double_top_not_detected_when_price_holds():
    closes = [90.0] * 10 + [100.0, 98.0, 100.5] + [92.0] * 10 + [99.5, 98.0, 95.0]
    df = _make_ohlcv(closes)
    assert detect_double_top(df) is False


from screener.patterns import (
    detect_triangle_up, detect_triangle_down,
    detect_breakout_confirm, detect_box_consolidation,
    detect_vcp,
)


def test_triangle_up_detected():
    # 對稱三角收斂：壓力局部高點下降（105→103→101），支撐局部低點上升（95→97），今日突破
    # highs: 局部高點在 idx 2(105), 7(103), 11(103), 17(101) → last-two slope = -0.333/day
    # lows:  局部低點在 idx 4(95.0), 14(97.0) → slope = +0.2/day
    # 壓力外推至 position 20 ≈ 100.0；today close = 101.5 > 100.0 ✓
    highs_h = [103.0, 104.0, 105.0, 103.0, 102.0,
               101.0, 102.0, 103.0, 102.0, 101.0,
               100.0, 103.0, 101.5, 101.0, 100.0,
                99.0, 100.0, 101.0, 100.0,  99.0]
    lows_h  = [ 97.5,  96.5,  97.0,  97.5,  95.0,
                95.5,  96.5,  97.0,  97.5,  98.0,
                98.5,  99.0,  98.5,  98.5,  97.0,
                97.5,  98.0,  98.5,  98.0,  99.0]
    closes_h = [(h + l) / 2 for h, l in zip(highs_h, lows_h)]
    highs  = highs_h  + [103.0]
    lows   = lows_h   + [99.5]
    closes = closes_h + [101.5]
    vols   = [1_000_000] * 20 + [2_000_000]
    df = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': vols})
    assert detect_triangle_up(df)


def test_triangle_down_detected():
    # 下降三角：壓力高點下降（105→103→101），支撐低點水平（95.0 / 95.2），今日跌破
    # highs: 局部高點在 idx 2(105), 7(103), 11(102), 17(100) → declining ✓
    # lows:  局部低點在 idx 4(95.0), 14(95.2) → slope = 0.02/day → |slope|/mean < 0.5% ✓
    # 支撐外推至 position 20 ≈ 95.32；today close = 93.5 < 95.32 ✓
    highs_h = [103.0, 104.0, 105.0, 103.0, 102.0,
               101.0, 102.0, 103.0, 102.0, 101.0,
               100.0, 102.0, 100.5, 100.0,  99.0,
                98.0,  99.0, 100.0,  99.0,  98.0]
    lows_h  = [ 96.5,  96.0,  96.5,  97.0,  95.0,
                95.5,  96.0,  96.5,  97.0,  97.0,
                97.5,  97.0,  97.5,  97.5,  95.2,
                95.8,  96.0,  96.5,  96.0,  96.5]
    closes_h = [(h + l) / 2 for h, l in zip(highs_h, lows_h)]
    highs  = highs_h  + [97.0]
    lows   = lows_h   + [92.5]
    closes = closes_h + [93.5]
    vols   = [1_000_000] * 20 + [2_000_000]
    df = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': vols})
    assert detect_triangle_down(df)


def test_breakout_confirm_detected():
    # 60-day high = 100; yesterday (day 63) close = 101 with big volume; today = 102
    closes = [98.0] * 60 + [100.0, 101.0, 102.0]   # 63 days total
    vols   = [1_000_000] * 61 + [1_600_000, 1_000_000]  # big vol on day 62 (yesterday)
    df = _make_ohlcv(closes, vols)
    assert detect_breakout_confirm(df)


def test_breakout_confirm_not_detected_when_below():
    # Breakout happened but today fell back below
    closes = [98.0] * 60 + [100.0, 101.0, 99.5]
    vols   = [1_000_000] * 61 + [1_600_000, 1_000_000]
    df = _make_ohlcv(closes, vols)
    assert not detect_breakout_confirm(df)


def test_box_consolidation_detected():
    # 20 days tight range: 99-101 (2%), today still inside
    closes = [99.0, 100.0, 101.0, 100.5] * 5 + [100.2]
    df = _make_ohlcv(closes)
    assert detect_box_consolidation(df) is True


def test_box_consolidation_broken():
    # Range tight but today broke out above
    closes = [99.0, 100.0, 101.0, 100.5] * 5 + [108.0]
    df = _make_ohlcv(closes)
    assert detect_box_consolidation(df) is False


def _make_vcp_df(
    prior_close_override: float | None = None,
    second_pullback_pct: float = 0.031,
) -> pd.DataFrame:
    """
    建立 70 列 VCP 測試資料（手工設計，確保嚴格局部高/低點）。

    結構：
      rows  0-24:  前置上升趨勢  80→104
      rows 25-26:  急漲 108→111（peak1 at row 26）
      rows 27-35:  第一波回檔 110→97（trough at row 33）
      rows 36-43:  反彈 101.5→107（peak2 at row 41）
      rows 44-49:  第二波回檔 105→pb2_low（trough at row 49）
      rows 50-68:  收縮整理（明確高於 pb2_low）
      row  69:     突破日 109
    """
    n = 70
    closes  = np.zeros(n, dtype=float)
    volumes = np.full(n, 1_200_000.0)

    # 前置上升
    for i in range(25):
        closes[i] = 80.0 + i

    # 急漲至峰值1
    closes[25] = 108.0
    closes[26] = 111.0   # ← PEAK 1

    # 第一波回檔（讓 97.0 嚴格低於周圍5根）
    pb1 = [110.0, 107.0, 105.0, 102.0, 100.0, 98.0, 97.0, 98.5, 100.0]
    for i, c in enumerate(pb1):
        closes[27 + i] = c
        volumes[27 + i] = 1_800_000   # 量大
    # closes[33] = 97.0 ← TROUGH 1 (strictly lower than [30..36])

    # 反彈至峰值2（明確高低，不與相鄰重複）
    rec2 = [101.5, 103.0, 104.5, 105.8, 106.5, 107.0, 106.2, 105.0]
    for i, c in enumerate(rec2):
        closes[36 + i] = c
    # closes[41] = 107.0 ← PEAK 2

    # 第二波回檔（從 105.0 起始，不等於 peak2=107.0）
    pk2 = 107.0
    pb2_low = pk2 * (1 - second_pullback_pct)
    pb2_vals = np.linspace(105.0, pb2_low, 6)
    for i, c in enumerate(pb2_vals):
        closes[44 + i] = c
        volumes[44 + i] = 900_000     # 量縮
    # closes[49] = pb2_low ← TROUGH 2

    # 收縮整理（從 pb2_low+0.3 開始，嚴格高於 trough2）
    for i in range(19):
        closes[50 + i] = pb2_low + 0.3 + i * 0.05
        volumes[50 + i] = 700_000

    # 突破日（突破 peak2=107.0）
    closes[69] = 109.0
    volumes[69] = 3_000_000

    if prior_close_override is not None:
        closes[5] = prior_close_override

    return pd.DataFrame({
        'close':  closes,
        'high':   closes * 1.005,
        'low':    closes * 0.995,
        'volume': volumes,
    })


def test_vcp_detected():
    """標準兩波量縮突破 → 應偵測為 VCP。"""
    df = _make_vcp_df()
    assert detect_vcp(df)


def test_vcp_not_detected_downtrend():
    """前置收盤價偏高（股票已在高位或下跌中）→ 非 VCP。"""
    # prior_close (row 5) = 112, first peak ≈ 111 → prior_close >= first_peak * 0.95 → 拒絕
    df = _make_vcp_df(prior_close_override=112.0)
    assert detect_vcp(df) is False


def test_vcp_not_detected_pullback_not_contracting():
    """第二波回檔 > 第一波 × 80% → 不符合量縮收斂條件。"""
    # second_pullback_pct=0.12: 第二波回檔 12% > 第一波 11.7% * 80% = 9.4%
    df = _make_vcp_df(second_pullback_pct=0.12)
    assert detect_vcp(df) is False


def test_scan_patterns_returns_list():
    """Integration smoke test: scan_patterns 回傳 list，每筆有必要欄位。"""
    from screener.patterns import scan_patterns
    results = scan_patterns("2026-06-26")   # 用已知有資料的日期
    assert isinstance(results, list)
    if results:
        r = results[0]
        for key in ("stock_id", "stock_name", "score", "patterns", "vol_ratio"):
            assert key in r, f"Missing key: {key}"
        assert isinstance(r["patterns"], list)
        # Score range sanity check
        assert -20 <= r["score"] <= 20
