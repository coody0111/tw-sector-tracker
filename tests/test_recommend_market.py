import pandas as pd
import pytest

from recommend.market import market_header


def _feat():
    d = pd.bdate_range("2026-01-01", periods=25)
    rows = []
    for k, dt in enumerate(d):
        for sid, close in (("A", 100.0 + k), ("B", 100.0 - k), ("C", 50.0)):
            rows.append({"stock_id": sid, "date": dt, "open": close, "close": close,
                         "change": 1.0 if sid == "A" else -1.0, "limit_up": sid == "A" and k == 24, "liq": True})
    f = pd.DataFrame(rows)
    f.loc[(f["stock_id"] == "C") & (f["date"] == d[-1]), ["close", "change"]] = [45.0, -5.0]   # 50→45 跌停
    return f, d


def test_market_header_counts_breadth_and_limits():
    f, d = _feat()
    h = market_header(f, pd.DataFrame(columns=["stock_id", "date"]), d[-1])
    assert h["above_ma20_pct"] == pytest.approx(1 / 3)     # 只有 A 在 MA20 之上
    assert (h["limit_up"], h["limit_down"]) == (1, 1)
    assert h["fail_rate"] is None and h["fail_n"] == 0       # 沒有訊號 → 樣本不足


def test_fail_rate_uses_prior_ten_days_signals():
    f, d = _feat()
    sig = pd.DataFrame({"stock_id": ["A"] * 3 + ["B"] * 3, "date": list(d[15:18]) * 2})
    h = market_header(f, sig, d[-1])
    assert h["fail_n"] == 6 and h["fail_rate"] == pytest.approx(0.5)   # B 一路跌、A 一路漲
