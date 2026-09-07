from __future__ import annotations

import pandas as pd
import duckdb

from processors.oliver_structure import analyze_price_history, calc_oliver_market_structure


def _history(closes: list[float], *, volumes: list[int] | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=len(closes))
    opens = [value * 0.998 for value in closes]
    highs = [max(open_, close) * 1.01 for open_, close in zip(opens, closes)]
    lows = [min(open_, close) * 0.99 for open_, close in zip(opens, closes)]
    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes or [1_000] * len(closes),
    })


def test_analyze_price_history_reports_bullish_weekly_structure():
    history = _history([100 + index * 0.12 for index in range(70)])

    result = analyze_price_history(history)

    assert result["weekly_structure"]["state"] == "bullish"
    assert result["weekly_structure"]["close_vs_10w_ema_pct"] > 0
    assert result["action_state"] in {"research", "watch"}
    assert result["parameter_status"] == "unverified-project-parameters"


def test_analyze_price_history_reports_flat_weekly_base_separately():
    result = analyze_price_history(_history([100.0] * 70))

    assert result["weekly_structure"]["state"] == "base"
    assert result["action_state"] == "watch"


def test_analyze_price_history_reports_flat_weekly_base_separately():
    result = analyze_price_history(_history([100.0] * 70))

    assert result["weekly_structure"]["state"] == "base"
    assert result["action_state"] == "watch"


def test_analyze_price_history_keeps_insufficient_history_unknown():
    result = analyze_price_history(_history([100, 101, 102, 103, 104]))

    assert result["weekly_structure"]["state"] == "unknown"
    assert result["daily_cycle"]["state"] == "unknown"
    assert result["action_state"] == "unknown"
    assert result["uncertainty"]


def test_analyze_price_history_separates_downside_extension_and_confirmed_reversal():
    history = _history([100.0] * 54 + [98.0, 95.0, 92.0, 89.0, 86.0, 92.0])
    last = history.index[-1]
    history.loc[last, ["open", "high", "low", "close", "volume"]] = [86.0, 93.0, 84.0, 92.0, 3_000]

    result = analyze_price_history(history)

    assert result["daily_cycle"]["state"] == "reversal-extension-confirmed"
    assert result["reversal_state"] == "confirmed"
    assert result["pivotal_point"] == {
        "status": "defined",
        "trigger": 93.0,
        "invalidation": 84.0,
        "risk_pct": 9.68,
    }
    assert result["weekly_structure"]["state"] == "bearish"
    assert result["action_state"] == "reduce-risk"


def test_analyze_price_history_ignores_bars_after_as_of():
    visible = _history([100 + index * 0.1 for index in range(70)])
    future = _history([100 + index * 0.1 for index in range(70)] + [180.0, 190.0])
    as_of = visible["date"].iloc[-1]

    assert analyze_price_history(future, as_of=as_of) == analyze_price_history(visible)


def test_analyze_price_history_marks_extreme_upside_extension_as_avoid_chasing():
    history = _history([100.0] * 55 + [104.0, 110.0, 118.0, 128.0, 142.0])

    result = analyze_price_history(history)

    assert result["daily_cycle"]["state"] == "exhaustion-extension"
    assert result["extension_state"] == "extreme"
    assert result["risk_state"] == "avoid-chasing"
    assert result["action_state"] == "reduce-risk"


def test_analyze_price_history_marks_failed_reversal_separately():
    history = _history([100.0] * 53 + [98.0, 95.0, 92.0, 89.0, 86.0, 92.0, 82.0])
    reversal = history.index[-2]
    history.loc[reversal, ["open", "high", "low", "close", "volume"]] = [86.0, 93.0, 84.0, 92.0, 3_000]
    last = history.index[-1]
    history.loc[last, ["open", "high", "low", "close", "volume"]] = [88.0, 89.0, 81.0, 82.0, 2_500]

    result = analyze_price_history(history)

    assert result["daily_cycle"]["state"] == "reversal-extension-failed"
    assert result["reversal_state"] == "failed"
    assert result["risk_state"] == "deterioration-warning"
    assert result["action_state"] == "reduce-risk"


def test_analyze_price_history_defines_pivotal_point_for_confirmed_base_break():
    history = _history([100.0] * 69 + [103.0], volumes=[1_000] * 69 + [2_000])
    last = history.index[-1]
    history.loc[last, ["open", "high", "low", "close"]] = [100.5, 104.0, 100.0, 103.0]

    result = analyze_price_history(history)

    assert result["daily_cycle"]["state"] == "base-n-break-bullish"
    assert result["pivotal_point"]["status"] == "defined"
    assert result["pivotal_point"]["trigger"] == 101.0
    assert result["risk_state"] == "defined-risk"
    assert result["action_state"] == "research"


def test_calc_oliver_market_structure_returns_analysis_for_entire_universe(tmp_path):
    db_path = tmp_path / "prices.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)")
    history = _history([100 + index * 0.12 for index in range(70)])
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("1000", *row) for row in history[["date", "open", "high", "low", "close", "volume"]].itertuples(index=False, name=None)],
    )
    con.close()
    universe = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "有資料"},
        {"stock_id": "2000", "stock_name": "沒資料"},
    ])

    result = calc_oliver_market_structure(universe, db_path=str(db_path), as_of=history["date"].iloc[-1])

    assert set(result) == {"1000", "2000"}
    assert result["1000"]["weekly_structure"]["state"] == "bullish"
    assert result["2000"]["weekly_structure"]["state"] == "unknown"
