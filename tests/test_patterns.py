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
