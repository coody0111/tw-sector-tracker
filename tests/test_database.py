# tests/test_database.py
import duckdb
import pandas as pd

from screener.database import get_chips_today, get_shareholder_top


def _make_chips_tables(con):
    con.execute("""CREATE TABLE institutional (
        stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT,
        dealer_net BIGINT, total_net BIGINT)""")
    con.execute("""CREATE TABLE margin (
        stock_id VARCHAR, date DATE, margin_balance BIGINT, margin_change BIGINT,
        short_balance BIGINT, short_change BIGINT)""")


def test_get_chips_today_falls_back_to_latest_available_date(tmp_path, monkeypatch):
    """institutional/margin 沒有『今天』資料時（盤後才發布、正常延遲一天），get_chips_today
    應 fallback 到最新可用日期，而不是回空（會讓族群頁外資/投信/融資全顯示「─」）。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _make_chips_tables(con)
    # 只有 07-07 有資料；請求的 today=07-08 沒有
    con.execute("INSERT INTO institutional VALUES ('2330','2026-07-07',1000,200,50,1250)")
    con.execute("INSERT INTO margin VALUES ('2330','2026-07-07',5000,-100,300,20)")
    con.close()

    df = get_chips_today("2026-07-08")
    assert len(df) == 1, "應 fallback 到 07-07 而不是回空"
    row = df.iloc[0]
    assert row["stock_id"] == "2330"
    assert row["foreign_net"] == 1000
    assert row["margin_balance"] == 5000


def test_get_chips_today_inst_and_margin_fall_back_independently(tmp_path, monkeypatch):
    """institutional 跟 margin 若各自停在不同日期（例如 margin 又更慢一天），
    兩張表應各自 fallback 到自己的最新日期，不會因為對不到同一天而漏。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _make_chips_tables(con)
    con.execute("INSERT INTO institutional VALUES ('2330','2026-07-07',1000,200,50,1250)")
    con.execute("INSERT INTO margin VALUES ('2330','2026-07-06',5000,-100,300,20)")  # margin 更舊一天
    con.close()

    df = get_chips_today("2026-07-08")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["foreign_net"] == 1000      # institutional fallback 07-07
    assert row["margin_balance"] == 5000   # margin fallback 07-06


def test_get_chips_today_per_stock_fallback_not_table_wide(tmp_path, monkeypatch):
    """真實情境：某天(07-07) margin 只有 TWSE 股(2330)、TPEx 股(6488)最新只到 07-06。
    若用『整張表最新日 07-07』會漏掉 TPEx 股的融資（顯示─）；per-stock fallback 應讓
    每支股票各退到自己的最新一筆。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _make_chips_tables(con)
    # 兩支都有 institutional 07-07
    con.execute("INSERT INTO institutional VALUES ('2330','2026-07-07',1000,200,50,1250),('6488','2026-07-07',300,10,5,315)")
    # margin：TWSE 股 2330 有 07-07；TPEx 股 6488 最新只到 07-06（07-07 那天 TPEx margin 沒抓到）
    con.execute("INSERT INTO margin VALUES ('2330','2026-07-07',5000,-100,300,20),('6488','2026-07-06',800,30,10,2)")
    con.close()

    df = get_chips_today("2026-07-08").set_index("stock_id")
    assert df.loc["2330", "margin_balance"] == 5000
    # 關鍵：TPEx 股不能因為 07-07 沒有它的 margin 就變 NULL，要退到自己的 07-06
    assert df.loc["6488", "margin_balance"] == 800, "TPEx 股融資應 per-stock fallback 到 07-06，不是被整表 MAX(07-07) 漏掉"


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


def test_get_rolling_returns_price_ratio(tmp_path, monkeypatch):
    """近N日累積漲跌 = 收盤價比值（最新交易日 rn1 / N交易日前 rn(N+1) − 1）×100；
    資料不足回 None。用收盤價比值、不是複利 change_pct（避免捨入漂移，兩頁一致）。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    # A: 8 交易日。rn1=110、rn6(5日前)=100→近5日+10%、rn8(7日前)=88→近7日+25%
    A = [('2026-06-26', 88), ('2026-06-27', 90), ('2026-06-30', 100), ('2026-07-01', 101),
         ('2026-07-02', 102), ('2026-07-03', 103), ('2026-07-04', 105), ('2026-07-07', 110)]
    for d, c in A:
        con.execute("INSERT INTO daily_prices VALUES ('AAAA', ?, ?)", [d, c])
    # B: 只有 4 天 → 近5/7/10/14 全部不足、回 None
    for d, c in [('2026-07-02', 50), ('2026-07-03', 51), ('2026-07-04', 52), ('2026-07-07', 55)]:
        con.execute("INSERT INTO daily_prices VALUES ('BBBB', ?, ?)", [d, c])
    con.close()

    r = db_mod.get_rolling_returns((5, 7, 10, 14))
    assert r["AAAA"][5] == 10.0    # (110-100)/100
    assert r["AAAA"][7] == 25.0    # (110-88)/88
    assert r["AAAA"][10] is None   # 只有8天，不足10日前(rn11)
    assert r["AAAA"][14] is None
    assert r["BBBB"][5] is None    # 4天不足5日前(rn6)
    assert r["BBBB"][7] is None
