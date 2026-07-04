import pandas as pd
from processors.changes import detect_changes

def _make_df(rows):
    return pd.DataFrame(rows, columns=["date", "sector_type", "sector_name",
                                        "sector_code", "stock_id", "stock_name"])

def test_detect_added_stock():
    yesterday = _make_df([
        ["2026-05-28", "concept", "AI", "", "2330", "台積電"],
    ])
    today = _make_df([
        ["2026-05-29", "concept", "AI", "", "2330", "台積電"],
        ["2026-05-29", "concept", "AI", "", "2317", "鴻海"],
    ])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    added = [c for c in changes if c["action"] == "added"]
    assert len(added) == 1
    assert added[0]["stock_id"] == "2317"

def test_detect_removed_stock():
    yesterday = _make_df([
        ["2026-05-28", "concept", "AI", "", "2330", "台積電"],
        ["2026-05-28", "concept", "AI", "", "2317", "鴻海"],
    ])
    today = _make_df([
        ["2026-05-29", "concept", "AI", "", "2330", "台積電"],
    ])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    removed = [c for c in changes if c["action"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["stock_id"] == "2317"

def test_no_changes_when_same():
    yesterday = _make_df([["2026-05-28", "concept", "AI", "", "2330", "台積電"]])
    today = _make_df([["2026-05-29", "concept", "AI", "", "2330", "台積電"]])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    assert changes == []

def test_empty_yesterday_returns_no_changes():
    yesterday = pd.DataFrame()
    today = _make_df([["2026-05-29", "concept", "AI", "", "2330", "台積電"]])
    changes = detect_changes(today, yesterday, sector_type="concept", today_date="2026-05-29")
    assert changes == []


from processors.performance import calc_sector_performance

def _make_sector_df(rows):
    return pd.DataFrame(rows, columns=["date","sector_type","sector_name",
                                        "sector_code","stock_id","stock_name"])

def _make_price_df(rows):
    return pd.DataFrame(rows, columns=["stock_id","stock_name","close",
                                        "change","change_pct","volume"])

def test_calc_performance_avg_change():
    sectors = _make_sector_df([
        ["2026-05-29","concept","AI","","2330","台積電"],
        ["2026-05-29","concept","AI","","2317","鴻海"],
    ])
    prices = _make_price_df([
        ["2330","台積電",905.0, 5.0, 0.56, 12345],
        ["2317","鴻海", 102.0,-1.0,-0.97,  8000],
    ])
    result = calc_sector_performance(sectors, prices)
    ai = next(r for r in result if r["sector_name"] == "AI")
    assert abs(ai["avg_change_pct"] - round((0.56 + (-0.97)) / 2, 2)) < 0.01

def test_calc_performance_up_down_counts():
    sectors = _make_sector_df([
        ["2026-05-29","concept","AI","","2330","台積電"],
        ["2026-05-29","concept","AI","","2317","鴻海"],
        ["2026-05-29","concept","AI","","2382","廣達"],
    ])
    prices = _make_price_df([
        ["2330","台積電",905.0, 5.0, 0.56, 12345],
        ["2317","鴻海", 102.0,-1.0,-0.97,  8000],
        ["2382","廣達", 250.0, 0.0, 0.00,  5000],
    ])
    result = calc_sector_performance(sectors, prices)
    ai = next(r for r in result if r["sector_name"] == "AI")
    assert ai["up_count"] == 1
    assert ai["down_count"] == 1
    assert ai["flat_count"] == 1

def test_calc_performance_skips_missing_price():
    sectors = _make_sector_df([
        ["2026-05-29","concept","AI","","2330","台積電"],
        ["2026-05-29","concept","AI","","9999","不存在"],
    ])
    prices = _make_price_df([
        ["2330","台積電",905.0, 5.0, 0.56, 12345],
    ])
    result = calc_sector_performance(sectors, prices)
    ai = next(r for r in result if r["sector_name"] == "AI")
    assert ai["up_count"] == 1
