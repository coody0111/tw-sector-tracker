import pandas as pd
import pytest

from recommend.backtest import CASES, blowup_rate, case_hits, catch_rate, report, run_trades, winner_episodes


def _feat():
    d = pd.bdate_range("2026-01-01", periods=8)
    rows = []
    for sid, closes in (("A", [100, 110, 112, 120, 130, 140, 150, 160]), ("B", [50, 55, 54, 51, 50, 49, 48, 47])):
        for dt, c in zip(d, closes):
            rows.append({"stock_id": sid, "date": dt, "open": c, "close": c, "one_word": False})
    return pd.DataFrame(rows)


def test_run_trades_links_signals_to_exits_and_excludes_dates():
    f = _feat()
    d1 = f["date"][1]
    sig = pd.DataFrame({"stock_id": ["A", "B"], "date": [d1, d1], "strategy": "突破策略",
                        "type": ["整理", "續攻"], "routes": "法人", "n_routes": 1})
    t = run_trades(f, sig)
    assert list(t["stock_id"]) == ["A", "B"]
    assert t.loc[t["stock_id"] == "A", "exit_reason"].iloc[0] == "持有中"
    assert t.loc[t["stock_id"] == "B", "exit_reason"].iloc[0] == "停損"   # 進場 54，50 ≤ 54×0.94
    assert run_trades(f, sig, exclude_dates=[d1]).empty


def _trades(rets, types=None):
    n = len(rets)
    return pd.DataFrame({"date": list(pd.bdate_range("2026-01-01", periods=n)), "ret": rets,
                         "r_multiple": [r / 0.06 for r in rets], "exit_reason": "停損",
                         "type": types or ["整理"] * n})


def test_report_core_metrics():
    r = report(_trades([0.30, -0.06, -0.06, 0.12]), split_date="2026-01-03")
    assert r["n"] == 4
    assert r["win_rate"] == 0.5
    assert r["pf"] == pytest.approx(0.42 / 0.12)
    assert r["payoff"] == pytest.approx(0.21 / 0.06)
    assert r["max_consec_losses"] == 2
    assert r["in_sample"]["n"] == 2 and r["out_sample"]["n"] == 2
    assert r["top5_share"] == pytest.approx(0.30 / 0.42)


def test_report_skips_open_positions():
    t = _trades([0.1, 0.2])
    t.loc[1, "exit_reason"] = "持有中"
    assert report(t, split_date="2026-01-02")["n"] == 1


def _price(sid, closes):
    d = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"stock_id": sid, "date": d, "open": closes, "close": closes, "one_word": False})


def test_winner_episodes_and_catch_rate():
    closes = [10.0] * 10 + [10.0 + k for k in range(1, 15)] + [24.0] * 50   # 漲到 24（+140%）
    f = pd.concat([_price("A", closes), _price("B", [10.0] * 74)], ignore_index=True)
    eps = winner_episodes(f, start="2026-01-01", end="2026-12-31")
    assert list(eps["stock_id"]) == ["A"]
    start = eps["start_date"].iloc[0]
    hit = pd.DataFrame({"stock_id": ["A"], "date": [start + pd.offsets.BDay(3)]})
    miss = pd.DataFrame({"stock_id": ["A"], "date": [start + pd.offsets.BDay(20)]})
    assert catch_rate(eps, hit, f) == 1.0
    assert catch_rate(eps, miss, f) == 0.0


def test_blowup_rate_twenty_day_minus_fifteen():
    f = pd.concat([_price("A", [100.0] * 2 + [80.0] * 25), _price("B", [100.0] * 27)], ignore_index=True)
    d1 = f["date"].iloc[0]
    sig = pd.DataFrame({"stock_id": ["A", "B"], "date": [d1, d1]})
    assert blowup_rate(sig, f) == 0.5    # A：隔天開 100、第 20 日收 80 → −20%


def test_case_hits():
    sig = pd.DataFrame({"stock_id": ["6672"], "date": [pd.Timestamp("2026-09-24")]})
    assert case_hits(sig) == {("6672", "2026-09-24"): True, ("6213", "2026-09-24"): False}
    assert CASES == [("6672", "2026-09-24"), ("6213", "2026-09-24")]
