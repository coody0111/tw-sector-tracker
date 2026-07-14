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
    # 訊號日 05-01（收盤90，刻意跟進場價不同以確保測到日期沒抓錯）；
    # D+1(05-02) 開盤 100 進，D+1+5(05-07) 收 110 → +10%
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 8)]
    rows[0] = ("2330", "2026-05-01", 100.0, 90.0)     # 訊號日收盤 90（刻意跟進場價不同）
    rows[-1] = ("2330", "2026-05-07", 108.0, 110.0)   # 出場日收盤 110
    rows[1] = ("2330", "2026-05-02", 100.0, 101.0)    # 進場日開盤 100、收盤 101（刻意不同，確認用的是開盤）
    db = _make_prices(tmp_path, rows)
    close_map, open_map, stock_dates = _build_price_index(db)
    entry, ret = _forward_return(close_map, open_map, stock_dates, "2330",
                                 pd.Timestamp("2026-05-01"), 5)
    assert entry == 100.0            # 用 D+1(05-02) 開盤 100，不是 D(05-01) 收盤 90，也不是 D+1 收盤 101
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


def _make_prices_with_change(tmp_path, rows):
    db = str(tmp_path / "bt2.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, close DOUBLE, change_pct DOUBLE)")
    prev = {}
    ins = []
    for (s, d, o, c) in rows:
        chg = 0.0 if s not in prev else round((c/prev[s]-1)*100, 4)
        prev[s] = c
        ins.append((s, pd.to_datetime(d).date(), o, c, chg))
    con.executemany("INSERT INTO daily_prices VALUES (?,?,?,?,?)", ins)
    con.close()
    return db


def test_run_backtest_excess_return_vs_market(tmp_path):
    # 2330 D+1→D+1+5 漲 10%；同期大盤(這裡只有 2330 一檔→大盤=它自己)→ excess≈0
    # 再加一檔 9999 全程不動，把大盤拉低，讓 2330 有正 excess
    rows = []
    for d in range(1, 10):
        rows.append(("2330", f"2026-05-{d:02d}", 100.0, 100.0))
        rows.append(("9999", f"2026-05-{d:02d}", 50.0, 50.0))
    # 2330 進場日(05-02)開盤100、出場日(05-07)收110
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-02","2026-05-07"))]
    rows += [("2330","2026-05-02",100.0,100.0), ("2330","2026-05-07",100.0,110.0)]
    # change_pct：給 2330 出場日 +10、其餘 0，讓大盤等權指數只被 2330 的 +10 稍微拉抬
    db = _make_prices_with_change(tmp_path, rows)

    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []

    df = run_backtest(scanner, db_path=db, horizons=(5,))
    r = df.iloc[0]
    assert r["bench_5"] > 0                 # 大盤同期>0(2330 自己的漲幅也拉抬等權指數)
    assert r["excess_5"] < r["ret_5"]      # 扣掉大盤後 < 原始報酬
    assert abs(r["excess_5"] - (r["ret_5"] - r["bench_5"])) < 1e-6  # cost 之後仍成立


def test_run_backtest_flags_limit_up_no_fill(tmp_path):
    # D(05-01)收100，D+1(05-02)開110(+10%>9.5%漲停)→ 買不到
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 10)]
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-01","2026-05-02"))]
    rows += [("2330","2026-05-01",100.0,100.0), ("2330","2026-05-02",110.0,111.0)]
    db = _make_prices(tmp_path, rows)

    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []

    df = run_backtest(scanner, db_path=db, horizons=(5,))
    assert bool(df.iloc[0]["no_fill"]) is True


def test_run_backtest_deducts_cost(tmp_path):
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0) for d in range(1, 10)]
    rows = [r for r in rows if not (r[0]=="2330" and r[1] in ("2026-05-02","2026-05-07"))]
    rows += [("2330","2026-05-02",100.0,100.0), ("2330","2026-05-07",100.0,110.0)]
    db = _make_prices(tmp_path, rows)
    def scanner(ds, dbp):
        return [{"stock_id":"2330","close":100.0}] if ds=="2026-05-01" else []
    df = run_backtest(scanner, db_path=db, horizons=(5,), cost_pct=0.6)
    assert df.iloc[0]["ret_5"] == round(10.0 - 0.6, 2)   # 9.4


def test_run_backtest_preserves_entry_price_when_later_horizon_lacks_data(tmp_path):
    """回歸：entry_price 不該被『資料不夠導致某天期算不出來』的 horizon 覆蓋成 None。
    只給 8 個交易日（05-01 訊號日 + 7 天），horizons=(5,14) 時 h=5 資料夠、h=14 不夠——
    entry_price 應該保留 h=5 算出的正確值，不能被 h=14 的 (None, None) 蓋掉。"""
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0 + d) for d in range(1, 9)]  # 05-01 ~ 05-08
    db = _make_prices(tmp_path, rows)

    def fake_scanner(date_str, db_path):
        return [{"stock_id": "2330", "close": 100.0}] if date_str == "2026-05-01" else []

    df = run_backtest(fake_scanner, db_path=db, horizons=(5, 14))
    row = df.iloc[0]
    assert row["ret_5"] is not None, "h=5 有足夠未來資料應該算得出來"
    assert row["ret_14"] is None, "h=14 資料不夠應該是 None（這是預期行為，不是本次修的 bug）"
    assert row["entry_price"] is not None, "entry_price 不該被 h=14 的失敗覆蓋成 None（這是本次修的 bug）"
    assert row["entry_price"] == 100.0
