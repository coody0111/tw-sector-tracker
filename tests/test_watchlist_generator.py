from datetime import date

import pandas as pd

from export.watchlist_generator import build_watchlist_rows, generate


def test_build_watchlist_rows_keeps_selected_ids_and_attaches_latest_market_data():
    universe = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
        {"stock_id": "2454", "stock_name": "聯發科", "meta_sector": "IC設計"},
    ])
    prices = pd.DataFrame([
        {"stock_id": "2330", "close": 100.0, "change_pct": 1.2, "date": "2026-09-04"},
        {"stock_id": "2454", "close": 80.0, "change_pct": -0.5, "date": "2026-09-04"},
    ])
    rows = build_watchlist_rows(
        universe,
        prices,
        selected_ids=["2454"],
        rolling_returns={"2454": {5: -2.0, 7: -1.0, 10: 3.0, 14: None}},
        oliver_analysis={"2454": {"weekly_structure": {"state": "bullish"}, "action_state": "watch"}},
    )

    assert [row["stock_id"] for row in rows] == ["2454"]
    assert rows[0]["close"] == 80.0
    assert rows[0]["roll5"] == -2.0
    assert rows[0]["roll14"] is None
    assert rows[0]["oliver"]["weekly_structure"]["state"] == "bullish"


def test_build_watchlist_rows_keeps_unknown_or_stale_selection():
    universe = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
    ])
    rows = build_watchlist_rows(
        universe,
        pd.DataFrame(),
        selected_ids=["2330", "9999"],
    )

    assert [row["stock_id"] for row in rows] == ["2330", "9999"]
    assert rows[0]["data_status"] == "no-data"
    assert rows[1]["data_status"] == "unknown-stock"


def test_generate_escapes_stock_names_and_includes_watchlist_contract(tmp_path):
    universe = pd.DataFrame([
        {"stock_id": "2330", "stock_name": '<img src=x onerror="alert(1)">', "meta_sector": "測試"},
    ])
    output = tmp_path / "watchlist.html"
    generate(
        date(2026, 9, 4),
        universe,
        pd.DataFrame(),
        oliver_analysis={
            "2330": {
                "weekly_structure": {"state": "bullish", "summary": "週線位於上升 10-week EMA 上方", "close_vs_10w_ema_pct": 3.2},
                "daily_cycle": {"state": "base", "summary": "近 20 日價格區間收斂"},
                "extension_state": "normal",
                "reversal_state": "none",
                "pivotal_point": {"status": "none", "trigger": None, "invalidation": None, "risk_pct": None},
                "risk_state": "normal",
                "action_state": "watch",
                "evidence": ["週線位於上升 10-week EMA 上方"],
                "uncertainty": ["門檻待回測"],
                "parameter_status": "unverified-project-parameters",
            }
        },
        market_context={
            "weekly_structure": {
                "state": "bullish",
                "summary": "TAIEX 週線位於上升 10-week EMA 上方",
                "close_vs_10w_ema_pct": 3.2,
            },
            "market_phase": "leading",
            "market_action": "normal-research",
            "as_of": "2026-09-04",
        },
        output_path=str(output),
    )
    html = output.read_text(encoding="utf-8")

    assert "tw-sector-watchlist-v1" in html
    assert "watchlist.html" in html
    assert "textContent=String(s ?? '')" in html
    assert "extension_state" in html
    assert "reversal_state" in html
    assert "Pivotal Point" in html
    assert "action_state" in html
    assert 'id="market-context"' in html
    assert "MARKET_CONTEXT" in html
    assert "normal-research" in html
    assert "EMA Crossback 向上" in html
    assert "EMA Crossback 向下警訊" in html
    assert "</script>" not in html.replace("</script></body></html>", "")
