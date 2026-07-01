import duckdb
from screener.signals import scan_volume_turnover


def _seed_db(db_path, price_rows, inst_rows=None):
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, close DOUBLE,
            change_pct DOUBLE, volume BIGINT
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?)",
        price_rows,
    )
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT,
            trust_net BIGINT, total_net BIGINT
        )
    """)
    if inst_rows:
        con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?, ?)", inst_rows)
    con.close()


def test_skips_stock_with_insufficient_history(tmp_path):
    """只有錨點日 + 今天兩筆資料時，量倍數統計上沒有意義，不該產生訊號。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("1101", "2025-06-02", 100.0, 0.0, 1000),   # 錨點日，跟今天差很多天
        ("1101", "2026-07-01", 110.0, 5.0, 50000),  # 前日漲停（change_pct 用不到，看今天跟昨天關係）
    ]
    _seed_db(db_path, rows)

    results = scan_volume_turnover("2026-07-01", db_path=str(db_path))

    assert results == []


def test_detects_signal_with_sufficient_history(tmp_path):
    """有足夠歷史資料（>=20 筆）時，符合三條件應該正常產生訊號。"""
    db_path = tmp_path / "test.db"
    rows = []
    # 25 個交易日的平緩歷史，量都在 1000 左右
    dates = [f"2026-05-{d:02d}" for d in range(1, 26)]
    for d in dates:
        rows.append(("2330", d, 100.0, 0.5, 1000))
    # 前一天漲停
    rows.append(("2330", "2026-06-30", 110.0, 9.9, 1200))
    # 今天：收跌、不鎖跌停、爆量
    rows.append(("2330", "2026-07-01", 108.0, -1.8, 50000))
    _seed_db(db_path, rows)

    results = scan_volume_turnover("2026-07-01", db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["vol_window_days"] >= 20
