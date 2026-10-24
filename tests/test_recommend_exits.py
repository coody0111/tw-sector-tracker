import pandas as pd
import pytest

from recommend.exits import FEE, TAX, simulate_trade


def _path(opens, closes, one_word=None):
    n = len(closes)
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n), "open": opens, "close": closes,
                         "one_word": one_word or [False] * n})


def _net(entry, exit_):
    return exit_ * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1


def test_stop_loss_on_close_six_percent():
    t = simulate_trade(_path([0, 100, 100, 100], [100, 98, 93.9, 120]), signal_pos=0)
    assert (t["exit_reason"], t["exit_price"]) == ("停損", 93.9)
    assert t["ret"] == pytest.approx(_net(100, 93.9))
    assert t["r_multiple"] == pytest.approx(t["ret"] / 0.06)


def test_trailing_twenty_percent_from_peak_close():
    t = simulate_trade(_path([0, 100] + [0] * 3, [100, 110, 150, 125, 119.9]), signal_pos=0)
    assert t["exit_reason"] == "回落" and t["exit_price"] == 119.9
    assert t["mfe"] == pytest.approx(0.5)


def test_max_hold_sixty_days_and_unfillable_one_word():
    t = simulate_trade(_path([0] + [100] * 70, [100] + [101] * 70), signal_pos=0)
    assert t["exit_reason"] == "到期" and t["hold_days"] == 60
    assert simulate_trade(_path([0, 110], [100, 110], one_word=[False, True]), signal_pos=0) is None


def test_open_position_when_path_ends():
    t = simulate_trade(_path([0, 100, 0], [100, 105, 108]), signal_pos=0)
    assert t["exit_reason"] == "持有中" and t["exit_price"] == 108
