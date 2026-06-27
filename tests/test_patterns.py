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
        [95.0, 92.0, 90.0, 92.0, 94.0] +   # first bottom ~idx 14
        [96.0, 97.0, 97.0, 96.0, 97.0] * 4 +  # bounce / neckline ~97
        [95.0, 92.0, 90.5, 92.0, 94.0] +   # second bottom ~idx 38
        [95.0, 96.0, 98.0]                  # today breaks neckline
    )
    # Volume spike on breakout day
    vols = [1_000_000] * (len(closes) - 1) + [1_300_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_bottom(df) is True


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
    vols = [1_000_000] * (len(closes) - 1) + [1_300_000]
    df = _make_ohlcv(closes, vols)
    assert detect_double_top(df) is True


def test_double_top_not_detected_when_price_holds():
    closes = [90.0] * 10 + [100.0, 98.0, 100.5] + [92.0] * 10 + [99.5, 98.0, 95.0]
    df = _make_ohlcv(closes)
    assert detect_double_top(df) is False
