import numpy as np
import pandas as pd

from recommend.features import add_chip_features, add_price_features


def _panel(closes, volumes=None, opens=None, changes=None, sid="2330"):
    n = len(closes)
    volumes = volumes or [1000] * n
    opens = opens or closes
    if changes is None:
        changes = [0.0] + [round(closes[i] - closes[i - 1], 2) for i in range(1, n)]
    return pd.DataFrame({
        "stock_id": sid, "date": pd.bdate_range("2026-01-01", periods=n),
        "open": opens, "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)], "close": closes,
        "volume": volumes, "change": changes,
    })


def test_limit_up_uses_reference_price_and_tick():
    closes = [100.0] * 25 + [110.0]
    f = add_price_features(_panel(closes))
    assert f["limit_up"].iloc[-1]
    assert not f["limit_up"].iloc[-2]


def test_limit_up_not_judged_in_first_five_rows():
    f = add_price_features(_panel([100.0, 110.0, 121.0, 133.0, 146.0, 160.5, 176.5]))
    assert not f["limit_up"].iloc[:5].any()
    assert f["limit_up"].iloc[5]


def test_one_word_requires_flat_ohlc():
    closes = [100.0] * 25 + [110.0]
    p = _panel(closes)
    assert add_price_features(p)["one_word"].iloc[-1]   # 開高低收都 110
    p.loc[p.index[-1], "low"] = 105.0
    assert not add_price_features(p)["one_word"].iloc[-1]


def test_volume_ratio_excludes_zero_volume_days_and_today():
    vols = [1000] * 10 + [0] * 5 + [1000] * 10 + [3000]
    f = add_price_features(_panel([100.0] * 26, volumes=vols))
    assert f["vr"].iloc[-1] == 3.0


def test_high_range_and_prior_return_exclude_today():
    closes = list(np.linspace(100, 120, 95)) + [130.0]
    f = add_price_features(_panel(closes))
    last = f.iloc[-1]
    assert last["hi90"] == closes[-2]
    assert last["rng20"] == closes[-2] / closes[-21] - 1
    assert last["ret20_prev"] == closes[-2] / closes[-22] - 1


def test_liquidity_threshold_turnover_100m():
    """前 20 日平均成交值 ≥ 1 億（不含當天）：100 元 × 1000 張 ＝ 1 億剛好過；同樣 1000 張、股價 10 元只有 1000 萬（13.14）。"""
    f = add_price_features(_panel([100.0] * 21, volumes=[999] * 20 + [50000]))
    assert not f["liq"].iloc[-1]
    f = add_price_features(_panel([100.0] * 21, volumes=[1000] * 20 + [1]))
    assert f["liq"].iloc[-1]
    f = add_price_features(_panel([10.0] * 21, volumes=[1000] * 21))
    assert not f["liq"].iloc[-1]


def _chip_panel():
    dates = pd.bdate_range("2026-01-01", periods=12)
    rows = []
    for sid, f_net, t_net, fpct0 in (("A", 1000, 100, 10.0), ("B", 0, -50, 20.0)):
        for k, d in enumerate(dates):
            rows.append({"stock_id": sid, "date": d, "foreign_net": f_net, "trust_net": t_net if k % 2 == 0 else 0,
                         "foreign_pct": fpct0 + k * (0.5 if sid == "A" else 0.0), "total_shares": 1_000_000,
                         "big_pct": 50.0 if k < 6 else (51.0 if sid == "A" else 49.0),
                         "big_date": dates[0] if k < 6 else dates[6]})
    return pd.DataFrame(rows)


def test_chip_windows_and_percentiles():
    f = add_chip_features(_chip_panel())
    a = f[f["stock_id"] == "A"].iloc[-1]
    b = f[f["stock_id"] == "B"].iloc[-1]
    assert a["inst5"] == (1000 * 5 + 100 * 2) / 1_000_000 * 100   # 最後 5 天投信有 2 天買（k=8、10）
    assert a["fpct5"] == 2.5
    assert a["trust_days10"] == 5
    assert a["inst5_pr"] == 1.0 and b["inst5_pr"] == 0.5
    assert a["big1w"] == 1.0 and b["big1w"] == -1.0
    assert a["big1w_pr"] == 1.0
    assert pd.isna(f[f["stock_id"] == "A"].iloc[0]["big1w"])      # 第一週沒有前一週


def test_price_features_use_adjusted_close_for_high_and_range():
    """除權息前的高價要還原：原始 hi90 會被除權前價格墊高、漏掉真突破（2026-10-27）。"""
    closes = [200.0] * 30 + [100.0] * 60 + [105.0]           # 第 31 天 1:2 除權（參考價 100）
    p = _panel(closes)
    p["adj"] = [0.5] * 30 + [1.0] * 61
    f = add_price_features(p)
    last = f.iloc[-1]
    assert last["hi90"] == 100.0 and last["aclose"] == 105.0   # 還原後前 90 日最高 100 → 105 是新高
    assert add_price_features(_panel(closes)).iloc[-1]["hi90"] == 200.0
