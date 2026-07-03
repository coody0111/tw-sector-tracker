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


import duckdb
from processors.performance import calc_weekly_rank

def _seed_daily_prices(db_path, rows):
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE,
            close DOUBLE, volume BIGINT, change DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices (stock_id, date, change_pct) VALUES (?, ?, ?)",
        rows,
    )
    con.close()

def test_calc_weekly_rank_compares_rolling_5day_windows(tmp_path):
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame(
        [["2330", "A"], ["2317", "B"]],
        columns=["stock_id", "meta_sector"],
    )
    dates = [
        "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    ]
    rows = []
    for i, d in enumerate(dates):
        pct_a = 0.1 if i < 5 else 2.0   # A：上週平淡，這週強
        pct_b = 1.0 if i < 5 else 0.1   # B：上週強，這週平淡
        rows.append(("2330", d, pct_a))
        rows.append(("2317", d, pct_b))
    _seed_daily_prices(db_path, rows)

    result = calc_weekly_rank(universe, db_path=str(db_path))

    assert result["A"]["last_week_rank"] == 2
    assert result["A"]["this_week_rank"] == 1
    assert result["B"]["last_week_rank"] == 1
    assert result["B"]["this_week_rank"] == 2

def test_calc_weekly_rank_returns_empty_when_insufficient_history(tmp_path):
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([["2330", "A"]], columns=["stock_id", "meta_sector"])
    _seed_daily_prices(db_path, [("2330", "2026-06-26", 1.0)])
    result = calc_weekly_rank(universe, db_path=str(db_path))
    assert result == {}
