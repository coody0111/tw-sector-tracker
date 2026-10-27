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


def test_ex_dividend_drop_is_not_a_stop_when_adjusted():
    """除息日原始價下跳 10%（100 → 90），還原價沒跌 → 不停損；報酬用還原價、顯示價用原始價（2026-10-27）。"""
    p = _path([0, 100, 0, 0], [100, 100, 90, 99])
    p["aopen"] = p["open"] * [0.9, 0.9, 1.0, 1.0]
    p["aclose"] = p["close"] * [0.9, 0.9, 1.0, 1.0]
    t = simulate_trade(p, signal_pos=0)
    assert t["exit_reason"] == "持有中" and t["entry_price"] == 100 and t["exit_price"] == 99
    assert t["ret"] == pytest.approx(_net(90, 99))                     # 還原後進場 90、現在 99 → 賺 10%
    raw = simulate_trade(_path([0, 100, 0, 0], [100, 100, 90, 99]), signal_pos=0)
    assert raw["exit_reason"] == "停損"                                 # 沒還原的話會被除息誤判停損
