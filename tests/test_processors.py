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
from processors.performance import calc_meta_chips_signals


def _seed_chips_db(db_path, inst_rows, margin_rows=None):
    """inst_rows: list of (stock_id, date, foreign_net, trust_net)
    margin_rows: list of (stock_id, date, margin_balance, margin_change)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT
        )
    """)
    con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?)", inst_rows)
    con.execute("""
        CREATE TABLE margin (
            stock_id VARCHAR, date DATE, margin_balance BIGINT, margin_change BIGINT
        )
    """)
    if margin_rows:
        con.executemany("INSERT INTO margin VALUES (?, ?, ?, ?)", margin_rows)
    con.close()


def _make_universe(rows):
    """rows: list of (stock_id, meta_sector, exchange)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector", "exchange"])


def test_calc_meta_chips_signals_no_partial_coverage_when_all_exchanges_present(tmp_path):
    """族群橫跨 TWSE+TPEx，今天兩邊都有資料 → 不該標記 partial_coverage。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-03", 1000, 100),
        ("6488", "2026-07-03", 500, 50),
    ], margin_rows=[
        ("1101", "2026-07-03", 10000, 500),
        ("6488", "2026-07-03", 5000, 200),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=1)

    assert result["測試族群"]["partial_coverage"] is False


def test_calc_meta_chips_signals_flags_partial_coverage_when_tpex_missing(tmp_path):
    """族群橫跨 TWSE+TPEx，但今天 institutional 只有 TWSE 資料（模擬 TPEx 抓取失敗）
    → 應該標記 partial_coverage=True，讓 chips.html 可以顯示警示，不要讓使用者誤以為
    foreign_net_today/streak 是完整族群的數字。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-03", 1000, 100),
        # 6488 (TPEx) 當天完全沒有 institutional 資料 —— 模擬 TPEx API 抓取失敗
    ], margin_rows=[
        ("1101", "2026-07-03", 10000, 500),
        ("6488", "2026-07-03", 5000, 200),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=1)

    assert result["測試族群"]["partial_coverage"] is True
    # 既有行為（分母動態排除缺資料交易所）應該維持不變：只算 TWSE 那 1 檔
    assert result["測試族群"]["total_stocks"] == 1


def test_calc_meta_chips_signals_flags_partial_coverage_when_margin_missing(tmp_path):
    """institutional 兩所都有資料，但 margin 當天只有 TWSE（模擬融資 TPEx 抓取失敗）
    → margin_balance_today/margin_change_today 只反映 TWSE，也該標記 partial_coverage。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-03", 1000, 100),
        ("6488", "2026-07-03", 500, 50),
    ], margin_rows=[
        ("1101", "2026-07-03", 10000, 500),
        # 6488 (TPEx) 融資資料當天缺失
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=1)

    assert result["測試族群"]["partial_coverage"] is True


def test_calc_meta_chips_signals_single_exchange_group_is_never_partial(tmp_path):
    """族群本來就只有 TWSE 成分股（沒有任何 TPEx 個股），今天只有 TWSE 資料是正常狀態，
    不該被誤判成「涵蓋不足」。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "純上市族群", "TWSE"),
        ("1102", "純上市族群", "TWSE"),
    ])
    _seed_chips_db(db_path, [
        ("1101", "2026-07-03", 1000, 100),
        ("1102", "2026-07-03", 500, 50),
    ], margin_rows=[
        ("1101", "2026-07-03", 10000, 500),
        ("1102", "2026-07-03", 5000, 200),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=1)

    assert result["純上市族群"]["partial_coverage"] is False
