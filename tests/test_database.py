# tests/test_database.py
import duckdb
import pandas as pd

from screener.database import (
    get_chips_today,
    get_latest_total_shares,
    get_shareholder_top,
    get_shareholder_trend,
    import_csv_prices,
    init_db,
)


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
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute("""
        INSERT INTO shareholder VALUES
        ('2330', '2026-06-26', 20.0, 100, 5000000, 25000000, NULL, 0, 1500000, 6.0, 3000000, 12.0),
        ('2330', '2026-07-03', 21.0, 105, 5250000, 25000000, 1.0, 1, 1600000, 6.4, 2900000, 11.6)
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
    """只有一週資料時，prev_date/share_chg/lv12_chg/lv15_chg 應該是 NULL，不能報錯。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.execute(
        "INSERT INTO shareholder VALUES "
        "('9999', '2026-07-03', 15.0, 10, 100000, 1000000, NULL, 0, 60000, 6.0, 20000, 2.0)"
    )
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["prev_date"])
    assert pd.isna(df.iloc[0]["share_chg"])
    assert pd.isna(df.iloc[0]["lv12_chg"])
    assert pd.isna(df.iloc[0]["lv15_chg"])


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


def test_get_shareholder_top_returns_lv12_and_lv15_tiers(tmp_path, monkeypatch):
    """get_shareholder_top() 要回傳 400張(lv12)/1000張(lv15) 各自的現況張數、
    占比，以及查詢時現算的週張數變化（lv12_chg/lv15_chg），不落地存表。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder(con)
    con.close()

    df = get_shareholder_top()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["lv12_shares"] == 1_600_000
    assert row["lv12_pct"] == 6.4
    assert row["lv12_chg"] == 100_000     # 1,600,000 - 1,500,000
    assert row["lv15_shares"] == 2_900_000
    assert row["lv15_pct"] == 11.6
    assert row["lv15_chg"] == -100_000    # 2,900,000 - 3,000,000


def test_get_shareholder_top_excludes_impossible_pct_outlier(tmp_path, monkeypatch):
    """離群值防護(#2) 讀取端：lv12_15_pct 為不可能的 >= 99（TDCC 解析異常，例 2380 的 100.0）
    的股票不該進大戶持倉排行，否則會用假 week_chg 佔據榜單。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder(con)  # 2330 正常（20.0 / 21.0）
    con.execute(
        "INSERT INTO shareholder VALUES "
        "('2380', '2026-07-03', 100.0, 50, 9990000, 10000000, -63.59, 0, 5000000, 50.0, 4990000, 49.9)"
    )
    con.close()

    df = get_shareholder_top()
    ids = set(df["stock_id"])
    assert "2380" not in ids, "lv12_15_pct=100.0 的離群值股不該上榜"
    assert "2330" in ids, "正常股仍在榜上"


def _seed_shareholder_trend(con, rows):
    """建 shareholder 表並塞入 (stock_id, date, lv12_15_pct) 列，其餘欄位一律 NULL/0
    （get_shareholder_trend() 只取這三欄，不需要湊齊其他欄位的真實值）。"""
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR NOT NULL, date DATE NOT NULL,
            lv12_15_pct DOUBLE, lv12_15_cnt INTEGER, lv12_15_shares BIGINT,
            total_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE,
            PRIMARY KEY (stock_id, date)
        )
    """)
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, lv12_15_pct) VALUES (?, ?, ?)", rows
    )


def test_get_shareholder_trend_returns_last_n_weeks_oldest_to_newest(tmp_path, monkeypatch):
    """5週資料、要5筆，且必須是「舊到新」排序（畫走勢圖要照時間順序），不是DB查詢的
    ORDER BY date DESC那個新到舊順序（那是給get_shareholder_top()用的，這裡要反過來）。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder_trend(con, [
        ("2330", "2026-06-19", 60.0),
        ("2330", "2026-06-26", 61.0),
        ("2330", "2026-07-03", 62.5),
        ("2330", "2026-07-10", 63.0),
        ("2330", "2026-07-17", 64.0),
    ])
    con.close()

    result = get_shareholder_trend(weeks=5)

    assert result["2330"] == [
        {"date": "2026-06-19", "lv12_15_pct": 60.0},
        {"date": "2026-06-26", "lv12_15_pct": 61.0},
        {"date": "2026-07-03", "lv12_15_pct": 62.5},
        {"date": "2026-07-10", "lv12_15_pct": 63.0},
        {"date": "2026-07-17", "lv12_15_pct": 64.0},
    ]


def test_get_shareholder_trend_handles_fewer_than_requested_weeks(tmp_path, monkeypatch):
    """只有2筆歷史(新股/新納入追蹤)時，回傳這2筆，不是報錯或補假資料湊到5筆。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder_trend(con, [
        ("1101", "2026-07-10", 40.0),
        ("1101", "2026-07-17", 41.5),
    ])
    con.close()

    result = get_shareholder_trend(weeks=5)

    assert result["1101"] == [
        {"date": "2026-07-10", "lv12_15_pct": 40.0},
        {"date": "2026-07-17", "lv12_15_pct": 41.5},
    ]


def test_get_shareholder_trend_respects_weeks_param(tmp_path, monkeypatch):
    """weeks=3時只回傳最近3筆，不是全部歷史。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder_trend(con, [
        ("2454", "2026-06-19", 30.0),
        ("2454", "2026-06-26", 31.0),
        ("2454", "2026-07-03", 32.0),
        ("2454", "2026-07-10", 33.0),
        ("2454", "2026-07-17", 34.0),
    ])
    con.close()

    result = get_shareholder_trend(weeks=3)

    assert result["2454"] == [
        {"date": "2026-07-03", "lv12_15_pct": 32.0},
        {"date": "2026-07-10", "lv12_15_pct": 33.0},
        {"date": "2026-07-17", "lv12_15_pct": 34.0},
    ]


def test_get_shareholder_trend_excludes_outlier_pct(tmp_path, monkeypatch):
    """跟get_shareholder_top()同一個離群值防護(#2)：>=_MAX_VALID_HOLDER_PCT視為TDCC解析
    異常，整筆排除（不是只排除那個異常值、留其他欄位），避免走勢圖畫出不可能的數字。"""
    from scrapers.shareholder import _MAX_VALID_HOLDER_PCT
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    _seed_shareholder_trend(con, [
        ("3008", "2026-07-10", 70.0),
        ("3008", "2026-07-17", float(_MAX_VALID_HOLDER_PCT)),
    ])
    con.close()

    result = get_shareholder_trend(weeks=5)

    assert result["3008"] == [{"date": "2026-07-10", "lv12_15_pct": 70.0}]


def test_import_csv_prices_keeps_real_ohlc_from_csv(tmp_path, monkeypatch):
    """回歸測試：import_csv_prices() 原本不管CSV裡有沒有open/high/low欄位，一律寫死NULL，
    把scrapers/realtime.py真的抓到的OHLC資料在匯入這關直接丟掉。修正後應該真的從CSV讀出
    這3欄；同時也要能處理「舊格式CSV完全沒有這3欄」跟「新格式CSV有這3欄」混在同一批
    glob讀取的情況（union_by_name），不能因為schema不一致就出錯或把新格式也弄成NULL。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    csv_dir = tmp_path / "daily_prices"
    csv_dir.mkdir()
    monkeypatch.setattr(db_mod, "CSV_GLOB", str(csv_dir / "*.csv"))

    # 舊格式：沒有open/high/low欄位(pre-realtime era)
    (csv_dir / "2026-07-01.csv").write_text(
        "stock_id,stock_name,close,change,change_pct,volume\n"
        "2330,台積電,900.0,5.0,0.56,10000\n",
        encoding="utf-8-sig",
    )
    # 新格式：有open/high/low欄位(scrapers/realtime.py輸出)
    (csv_dir / "2026-07-02.csv").write_text(
        "stock_id,stock_name,close,change,change_pct,volume,open,high,low,time\n"
        "2330,台積電,905.0,5.0,0.56,12000,900.0,910.0,898.0,13:30:00\n",
        encoding="utf-8-sig",
    )

    db_mod.init_db()
    count = import_csv_prices()
    assert count == 2

    con = duckdb.connect(db_path)
    rows = con.execute(
        "SELECT date, open, high, low FROM daily_prices WHERE stock_id='2330' ORDER BY date"
    ).fetchall()
    con.close()

    old_row, new_row = rows
    assert old_row[1] is None and old_row[2] is None and old_row[3] is None, (
        "舊格式CSV沒有OHLC欄位，應該是NULL，不是編造的假值"
    )
    assert new_row[1] == 900.0 and new_row[2] == 910.0 and new_row[3] == 898.0, (
        "新格式CSV真的有OHLC資料時，匯入DB應該保留，不能被寫死成NULL"
    )


def test_get_latest_total_shares_per_stock_fallback(tmp_path, monkeypatch):
    """跟get_chips_today()一樣的per-stock fallback：每支股票各自取<=trade_date的
    最新一筆，不是整表取單一最新日期——某股集保資料比整表最新日期舊，仍要抓到
    自己的最新一筆，不是回空。"""
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, total_shares BIGINT)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-07-09', 100000000)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-07-16', 100000000)")
    con.execute("INSERT INTO shareholder VALUES ('2317', '2026-07-02', 50000000)")  # 更舊一週，沒跟上
    con.close()

    df = get_latest_total_shares("2026-07-16")

    # date 是 DuckDB DATE → pandas datetime64（Timestamp），跟本檔其他測試一致做法
    # （見 test_get_shareholder_top_returns_prev_date_and_share_chg），故只比日期部分
    row_2330 = df[df["stock_id"] == "2330"].iloc[0]
    assert row_2330["total_shares"] == 100000000
    assert str(row_2330["date"])[:10] == "2026-07-16"

    row_2317 = df[df["stock_id"] == "2317"].iloc[0]
    assert row_2317["total_shares"] == 50000000
    assert str(row_2317["date"])[:10] == "2026-07-02"


def test_get_latest_total_shares_returns_empty_dataframe_when_no_data(tmp_path, monkeypatch):
    import screener.database as db_mod
    db_path = str(tmp_path / "empty.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, total_shares BIGINT)")
    con.close()

    df = get_latest_total_shares("2026-07-16")
    assert df.empty


def test_import_csv_prices_survives_when_every_csv_lacks_ohlc(tmp_path, monkeypatch):
    """回歸測試（2026-08-28 實際把 daily_prices 打空的 bug）：

    union_by_name 只能在「有些檔案有、有些沒有」時補 NULL；若**所有** CSV 都缺
    open/high/low（backfill_yfinance 早期只寫 close/volume，又剛好 _clear_price_csvs()
    把含 OHLC 的舊檔全刪了），那欄在來源表根本不存在，原本寫死的
    `TRY_CAST(open AS DOUBLE) AS open` 會被 DuckDB 當成同名別名的自我參照，
    拋 BinderException 讓整批匯入失敗。

    而這一步發生在 reimport_db() 已經清空 daily_prices 之後——炸掉就等於資料全空，
    所以這裡必須「匯得進去」而不是「乾脆地失敗」。OHLC 欄位允許是 NULL。
    """
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    csv_dir = tmp_path / "daily_prices"
    csv_dir.mkdir()
    monkeypatch.setattr(db_mod, "CSV_GLOB", str(csv_dir / "*.csv"))

    # 兩個檔案都沒有 open/high/low（yfinance backfill 寫出來的格式）
    for day, close in (("2026-08-27", 494.0), ("2026-08-28", 543.0)):
        (csv_dir / f"{day}.csv").write_text(
            "stock_id,close,change,change_pct,volume,_date\n"
            f"8358,{close},49.0,9.92,39692,{day}\n",
            encoding="utf-8-sig",
        )

    db_mod.init_db()
    n = db_mod.import_csv_prices()

    assert n == 2, "所有 CSV 都缺 OHLC 時仍要成功匯入，不能拋 BinderException"
    con = duckdb.connect(db_path)
    rows = con.execute(
        "SELECT date, open, close FROM daily_prices WHERE stock_id='8358' ORDER BY date"
    ).fetchall()
    con.close()
    assert [r[2] for r in rows] == [494.0, 543.0]
    assert all(r[1] is None for r in rows), "缺席的 OHLC 欄位應為 NULL，不是 0 或報錯"


def _write_price_csv(csv_dir, day, stock_id="2330", close=900.0):
    (csv_dir / f"{day}.csv").write_text(
        "stock_id,close,change,change_pct,volume,_date" + '\n' +
        f"{stock_id},{close},1.0,0.11,10000,{day}" + '\n',
        encoding="utf-8-sig",
    )


def _setup_incremental_db(tmp_path, monkeypatch):
    import screener.database as db_mod
    db_path = str(tmp_path / "t.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    csv_dir = tmp_path / "daily_prices"
    csv_dir.mkdir()
    monkeypatch.setattr(db_mod, "CSV_GLOB", str(csv_dir / "*.csv"))
    db_mod.init_db()
    return db_mod, db_path, csv_dir


def test_import_csv_prices_incremental_only_touches_needed_days(tmp_path, monkeypatch):
    """每日流程不該每次重讀全部 CSV：DB 已是最新時，增量匯入只碰「最新兩天」，
    而不是把 400+ 個檔、41 萬筆原樣覆蓋回去（實測全量 6.69 秒 / 增量 0.14 秒）。"""
    db_mod, _db_path, csv_dir = _setup_incremental_db(tmp_path, monkeypatch)
    for day in ("2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"):
        _write_price_csv(csv_dir, day)

    assert db_mod.import_csv_prices() == 4          # 先全量建立
    n = db_mod.import_csv_prices(incremental=True)
    assert n == 2, "DB 已最新時只該重匯最新兩天（realtime 價要被收盤價覆蓋）"


def test_import_csv_prices_incremental_backfills_missing_middle_day(tmp_path, monkeypatch):
    """關鍵：增量不能只匯今天。某天匯入失敗留下的洞（缺交易日正是「近N日漲跌幅
    失真」的根因）要能自動補回來，不管缺的是哪一天。"""
    db_mod, db_path, csv_dir = _setup_incremental_db(tmp_path, monkeypatch)
    days = ("2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28")
    for day in days:
        _write_price_csv(csv_dir, day)
    db_mod.import_csv_prices()

    # 模擬 8/26 那天匯入失敗留下的洞
    con = duckdb.connect(db_path)
    con.execute("DELETE FROM daily_prices WHERE date = DATE '2026-08-26'")
    con.close()

    db_mod.import_csv_prices(incremental=True)

    con = duckdb.connect(db_path)
    got = [str(r[0]) for r in con.execute(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date").fetchall()]
    con.close()
    assert got == list(days), f"缺的 2026-08-26 應被自動補回，實際 {got}"


def test_import_csv_prices_incremental_matches_full_import(tmp_path, monkeypatch):
    """增量與全量的結果必須一致——省時間不能改變資料內容。"""
    db_mod, db_path, csv_dir = _setup_incremental_db(tmp_path, monkeypatch)
    for i, day in enumerate(("2026-08-25", "2026-08-26", "2026-08-27")):
        _write_price_csv(csv_dir, day, close=900.0 + i)
    db_mod.import_csv_prices()

    # 新的一天進來，走增量
    _write_price_csv(csv_dir, "2026-08-28", close=910.0)
    db_mod.import_csv_prices(incremental=True)
    con = duckdb.connect(db_path)
    incremental_rows = con.execute(
        "SELECT stock_id, date, close FROM daily_prices ORDER BY date").fetchall()
    con.close()

    # 同一批 CSV 從零全量重建，結果應完全相同
    db_mod.reimport_db()
    con = duckdb.connect(db_path)
    full_rows = con.execute(
        "SELECT stock_id, date, close FROM daily_prices ORDER BY date").fetchall()
    con.close()
    assert incremental_rows == full_rows


def test_import_csv_prices_incremental_falls_back_to_full_when_no_csv(tmp_path, monkeypatch):
    """沒有任何 CSV 時不該爆炸，回 0 筆即可（reimport 炸掉後的空狀態）。"""
    db_mod, _db_path, _csv_dir = _setup_incremental_db(tmp_path, monkeypatch)
    assert db_mod.import_csv_prices(incremental=True) == 0
