"""scripts/drop_no_trade_rows.py：只刪「量 0 且開高低都空」的列，CSV 與 DuckDB 兩邊；不加 --apply 不動資料。"""
import duckdb
import pandas as pd

import scripts.drop_no_trade_rows as d


def _setup(tmp_path):
    rows = pd.DataFrame([
        {"stock_id": "3064", "close": 13.2, "volume": 0, "open": None, "high": None, "low": None},      # 假列
        {"stock_id": "2330", "close": 1000.0, "volume": 30000, "open": 990.0, "high": 1001.0, "low": 985.0},
        {"stock_id": "9999", "close": 50.0, "volume": 0, "open": 50.0, "high": 50.0, "low": 50.0},      # 量 0 但有開高低：不刪
    ])
    csv_dir = tmp_path / "prices"
    csv_dir.mkdir()
    rows.to_csv(csv_dir / "2026-11-02.csv", index=False, encoding="utf-8-sig")
    db = str(tmp_path / "s.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices AS SELECT stock_id, DATE '2026-11-02' AS date, close, volume, open, high, low FROM rows")
    con.close()
    return csv_dir, db


def test_dry_run_changes_nothing(tmp_path):
    csv_dir, db = _setup(tmp_path)
    assert d.clean_csvs(False, csv_dir) == 1 and d.clean_db(False, db) == 1
    assert len(pd.read_csv(csv_dir / "2026-11-02.csv")) == 3
    assert duckdb.connect(db).execute("SELECT count(*) FROM daily_prices").fetchone()[0] == 3


def test_apply_removes_only_no_trade_rows(tmp_path):
    csv_dir, db = _setup(tmp_path)
    assert d.clean_csvs(True, csv_dir) == 1 and d.clean_db(True, db) == 1
    left = pd.read_csv(csv_dir / "2026-11-02.csv", dtype={"stock_id": str})
    assert sorted(left["stock_id"]) == ["2330", "9999"]
    con = duckdb.connect(db)
    assert sorted(r[0] for r in con.execute("SELECT stock_id FROM daily_prices").fetchall()) == ["2330", "9999"]
    con.close()
