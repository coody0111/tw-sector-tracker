"""因子研究檯的測試。第一風險 = 前視偏誤，所以那組測試最重要。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research import evaluate as ev
from research import factor_data as fd
from research import factors as fx


def _panel(n_days: int = 80, n_stocks: int = 12, seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n_days)
    cols = [f"S{i:02d}" for i in range(n_stocks)]
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_days, n_stocks)), axis=0)),
        index=idx, columns=cols,
    )
    high = close * (1 + rng.uniform(0, 0.03, close.shape))
    low = close * (1 - rng.uniform(0, 0.03, close.shape))
    volume = pd.DataFrame(rng.integers(1e3, 1e6, close.shape), index=idx, columns=cols).astype(float)
    return {"close": close, "high": high, "low": low, "volume": volume}


# --- RankIC 正確性（合成資料驗算對）------------------------------------------


def test_rank_ic_perfectly_aligned_is_plus_one():
    p = _panel()
    f = pd.DataFrame(
        np.tile(np.arange(p["close"].shape[1], dtype=float), (p["close"].shape[0], 1)),
        index=p["close"].index, columns=p["close"].columns,
    )
    assert ev.rank_ic(f, f).dropna().mean() == pytest.approx(1.0)


def test_rank_ic_reversed_is_minus_one():
    p = _panel()
    f = pd.DataFrame(
        np.tile(np.arange(p["close"].shape[1], dtype=float), (p["close"].shape[0], 1)),
        index=p["close"].index, columns=p["close"].columns,
    )
    assert ev.rank_ic(f, -f).dropna().mean() == pytest.approx(-1.0)


def test_rank_ic_random_is_near_zero():
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2025-01-01", periods=400)
    cols = [f"S{i:02d}" for i in range(60)]
    a = pd.DataFrame(rng.normal(size=(400, 60)), index=idx, columns=cols)
    b = pd.DataFrame(rng.normal(size=(400, 60)), index=idx, columns=cols)
    assert abs(ev.rank_ic(a, b).dropna().mean()) < 0.02


def test_rank_ic_skips_thin_cross_sections():
    idx = pd.bdate_range("2025-01-01", periods=3)
    cols = ["A", "B", "C"]  # 只有 3 檔 < MIN_XS
    f = pd.DataFrame(1.0, index=idx, columns=cols)
    assert ev.rank_ic(f, f).dropna().empty


# --- 未來報酬正確性 -----------------------------------------------------------


def test_forward_returns_match_manual_calculation():
    p = _panel(n_days=10, n_stocks=3)
    fwd = fd.forward_returns(p, horizons=(1, 3))
    close = p["close"]
    for h in (1, 3):
        expect = close.iloc[h] / close.iloc[0] - 1
        pd.testing.assert_series_equal(fwd[h].iloc[0], expect, check_names=False)


def test_forward_returns_tail_is_nan():
    p = _panel(n_days=10, n_stocks=3)
    fwd = fd.forward_returns(p, horizons=(3,))
    assert fwd[3].iloc[-3:].isna().all().all()


# --- 前視偏誤（鐵律）----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(fx.FACTORS))
def test_factor_does_not_peek_into_the_future(name):
    """把 t 之後的資料改成 NaN，第 t 天的因子值必須不變。"""
    p = _panel(n_days=90, n_stocks=15, seed=3)
    t = 75

    full = fx.FACTORS[name](p)
    truncated = {k: v.iloc[: t + 1].copy() for k, v in p.items()}
    partial = fx.FACTORS[name](truncated)

    a, b = full.iloc[t], partial.iloc[t]
    assert a.isna().equals(b.isna()), f"{name}: 第 t 天的 NaN 樣態依賴未來"
    pd.testing.assert_series_equal(a.dropna(), b.dropna(), check_names=False)


def test_forward_returns_is_the_only_future_looking_helper():
    """反向驗證：fwd_ret 確實會因為截斷而改變（證明測試本身有效）。"""
    p = _panel(n_days=90, n_stocks=15, seed=3)
    t = 75
    full = fd.forward_returns(p, (5,))[5].iloc[t]
    trunc = fd.forward_returns({k: v.iloc[: t + 1] for k, v in p.items()}, (5,))[5].iloc[t]
    assert full.notna().any() and trunc.isna().all()


# --- 族群聚合 -----------------------------------------------------------------


def test_to_sector_uses_median_for_factor_and_mean_for_return():
    idx = pd.bdate_range("2025-01-01", periods=1)
    cols = ["A", "B", "C", "D"]
    f = pd.DataFrame([[1.0, 2.0, 6.0, 10.0]], index=idx, columns=cols)
    r = pd.DataFrame([[0.1, 0.3, 0.5, 0.9]], index=idx, columns=cols)
    smap = pd.Series({"A": "X", "B": "X", "C": "Y", "D": "Y"})

    sf, sr = ev.to_sector(f, r, smap)
    assert sf.loc[idx[0], "X"] == pytest.approx(1.5)   # median(1,2)
    assert sf.loc[idx[0], "Y"] == pytest.approx(8.0)   # median(6,10)
    assert sr.loc[idx[0], "X"] == pytest.approx(0.2)   # mean(0.1,0.3)
    assert sr.loc[idx[0], "Y"] == pytest.approx(0.7)   # mean(0.5,0.9)


def test_to_sector_ignores_stocks_missing_from_map():
    idx = pd.bdate_range("2025-01-01", periods=1)
    f = pd.DataFrame([[1.0, 2.0]], index=idx, columns=["A", "Z"])
    smap = pd.Series({"A": "X"})
    sf, _ = ev.to_sector(f, f, smap)
    assert list(sf.columns) == ["X"]


# --- 樣本外切分 ---------------------------------------------------------------


def test_split_is_chronological_and_non_overlapping():
    p = _panel(n_days=90)
    split = fd.split_date(p, in_sample_frac=2 / 3)
    days = p["close"].index
    ins, oos = days[days < split], days[days >= split]

    assert len(ins) + len(oos) == len(days)
    assert ins.max() < oos.min()
    assert len(ins) == pytest.approx(len(days) * 2 / 3, abs=1)


# --- 組合方式 -----------------------------------------------------------------


def test_blend_filter_keeps_main_ordering_and_drops_low_condition():
    idx = pd.bdate_range("2025-01-01", periods=1)
    cols = list("ABCD")
    main = pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=idx, columns=cols)
    cond = pd.DataFrame([[4.0, 3.0, 2.0, 1.0]], index=idx, columns=cols)

    out = fx.blend_filter(main, cond, keep_top=0.5).iloc[0]
    assert out[["C", "D"]].isna().all()          # cond 排名低 -> 剔除
    assert out["A"] < out["B"]                    # 留下來的順序仍由 main 決定


def test_blend_average_moves_toward_the_second_signal():
    idx = pd.bdate_range("2025-01-01", periods=1)
    cols = list("ABCD")
    main = pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=idx, columns=cols)
    cond = pd.DataFrame([[4.0, 3.0, 2.0, 1.0]], index=idx, columns=cols)

    out = fx.blend_average(main, cond, w=0.5).iloc[0]
    assert out.nunique() == 1                     # 完全反向、各半 -> 全部打平
