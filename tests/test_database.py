# tests/test_database.py
import duckdb
import pandas as pd

from screener.database import get_shareholder_top


def _seed_shareholder(con):
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        INSERT INTO shareholder VALUES
        ('2330', '2026-06-26', 20.0, 100, 5000000, 25000000, NULL, 0),
        ('2330', '2026-07-03', 21.0, 105, 5250000, 25000000, 1.0, 1)
    """)


def test_get_shareholder_top_returns_prev_date_and_share_chg(tmp_path, monkeypatch):
    """get_shareholder_top() 要回傳上週日期跟張數變化（股數差），
    才能算出『大戶張數變化』跟『對齊集保週期的週股價變化』。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder(con)
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    row = df.iloc[0]
    # date/prev_date 是 DuckDB DATE → pandas datetime64（Timestamp），跟 daily_prices 一致
    # （Task 4 的股價對齊靠這個一致性），故只比日期部分、不比型別
    assert str(row["date"])[:10] == "2026-07-03"
    assert str(row["prev_date"])[:10] == "2026-06-26"
    assert row["lv12_15_shares"] == 5250000
    assert row["share_chg"] == 250000   # 5,250,000 - 5,000,000


def test_get_shareholder_top_prev_date_null_for_single_week(tmp_path, monkeypatch):
    """只有一週資料時，prev_date/share_chg 應該是 NULL，不能報錯。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("INSERT INTO shareholder VALUES ('9999', '2026-07-03', 15.0, 10, 100000, 1000000, NULL, 0)")
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["prev_date"])
    assert pd.isna(df.iloc[0]["share_chg"])
