import duckdb
import pandas as pd
from screener.backtest import run_backtest, _build_price_index, _forward_return


def _make_prices(tmp_path, rows):
    """rows: list of (stock_id, 'YYYY-MM-DD', open, close)"""
    db = str(tmp_path / "bt.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, close DOUBLE, change_pct DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, NULL)",
        [(s, pd.to_datetime(d).date(), o, c) for (s, d, o, c) in rows],
    )
    con.close()
    return db


def test_forward_return_enters_next_day_open(tmp_path):
    # 訊號日 05-01；D+1(05-02) 開盤 100 進，D+1+5(05-07) 收 110 → +10%
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 8)]
    rows[-1] = ("2330", "2026-05-07", 108.0, 110.0)  # 出場日收盤 110
    rows[1] = ("2330", "2026-05-02", 100.0, 101.0)   # 進場日開盤 100
    db = _make_prices(tmp_path, rows)
    close_map, open_map, stock_dates = _build_price_index(db)
    entry, ret = _forward_return(close_map, open_map, stock_dates, "2330",
                                 pd.Timestamp("2026-05-01"), 5)
    assert entry == 100.0            # 用 D+1 開盤，不是 D 收盤
    assert ret == 10.0              # (110-100)/100


def test_run_backtest_accepts_any_scanner(tmp_path):
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0 + d) for d in range(1, 10)]
    db = _make_prices(tmp_path, rows)

    def fake_scanner(date_str, db_path):
        return [{"stock_id": "2330", "close": 100.0}] if date_str == "2026-05-01" else []

    df = run_backtest(fake_scanner, db_path=db, horizons=(5,))
    assert len(df) == 1
    assert df.iloc[0]["signal_date"] == "2026-05-01"
    assert df.iloc[0]["stock_id"] == "2330"
    assert "ret_5" in df.columns
