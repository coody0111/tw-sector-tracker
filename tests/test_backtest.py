import duckdb
import pandas as pd
import screener.backtest as backtest_module
from screener.backtest import run_backtest, scan_chips_rule, make_chips_rule_scanner, _build_price_index, _forward_return


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


def test_run_backtest_uses_volume_turnover_scanner_by_default(tmp_path, monkeypatch):
    rows = [("2330", f"2026-05-{d:02d}", 100.0, 100.0 + d) for d in range(1, 10)]
    db = _make_prices(tmp_path, rows)

    def fake_scanner(date_str, db_path):
        return [{"stock_id": "2330"}] if date_str == "2026-05-01" else []

    monkeypatch.setattr(backtest_module, "scan_volume_turnover", fake_scanner)
    df = run_backtest(db_path=db, horizons=(5,))

    assert len(df) == 1
    assert df.iloc[0]["stock_id"] == "2330"


def test_joint_buy_rule_uses_normalized_flow_and_liquidity(monkeypatch):
    rows = [
        {"stock_id": "2330", "date": "2026-07-01", "meta_sector": "晶圓代工", "both_streak": 2,
         "price_cum_pct": 1.0, "volume": 1000, "institutional_flow_ratio_pct": 0.2},
        {"stock_id": "1111", "date": "2026-07-01", "meta_sector": "測試", "both_streak": 4,
         "price_cum_pct": 5.0, "volume": 1000, "institutional_flow_ratio_pct": 0.01},
    ]
    monkeypatch.setattr(backtest_module, "scan_institutional", lambda *args, **kwargs: rows)
    picks = make_chips_rule_scanner("joint_buy")("2026-07-01", "ignored.db")
    assert [p["stock_id"] for p in picks] == ["2330"]
    assert make_chips_rule_scanner("joint_buy")("2026-07-02", "ignored.db") == [], \
        "法人資料尚未發布時的 fallback 不該把前一天訊號重複計數"


def test_foreign_continuation_backtest_matches_ui_top15(monkeypatch):
    rows = [
        {"stock_id": f"{2000+i}", "date": "2026-07-01", "meta_sector": "測試",
         "foreign_streak": 3 + i, "price_cum_pct": 5.0 + i}
        for i in range(20)
    ]
    monkeypatch.setattr(backtest_module, "scan_institutional", lambda *args, **kwargs: rows)
    picks = make_chips_rule_scanner("foreign_continuation")("2026-07-01", "top15-ignored.db")
    assert len(picks) == 15
    assert picks[0]["stock_id"] == "2019"


def test_foreign_continuation_ablation_variants_use_isolated_ranking(monkeypatch):
    """foreign_continuation_streak_only/price_only 沿用跟 foreign_continuation 完全一樣的
    篩選門檻（foreign_streak>=3 且 price_cum_pct>=5），只有排序依據不同——用來回答「排除價格
    動能之後，法人連買本身還有沒有效」這個消融對照問題（見 2026-07-18 bug-reports.md）。"""
    rows = [
        {"stock_id": "A", "date": "2026-07-01", "meta_sector": "測試", "foreign_streak": 20, "price_cum_pct": 5.0},
        {"stock_id": "B", "date": "2026-07-01", "meta_sector": "測試", "foreign_streak": 3, "price_cum_pct": 50.0},
    ]
    monkeypatch.setattr(backtest_module, "scan_institutional", lambda *args, **kwargs: rows)

    streak_only = make_chips_rule_scanner("foreign_continuation_streak_only")("2026-07-01", "ignored.db")
    price_only = make_chips_rule_scanner("foreign_continuation_price_only")("2026-07-01", "ignored.db")

    assert [p["stock_id"] for p in streak_only] == ["A", "B"], "純連買天數排序，A（20日）該排第一"
    assert [p["stock_id"] for p in price_only] == ["B", "A"], "純價格漲幅排序，B（+50%）該排第一"


def test_backtest_chips_config_covers_all_continuation_ablation_rules():
    """每個 CHIPS_RULES 都要有對應的 CHIPS_RULE_CONFIG，否則 run_chips_rule_backtests()
    會在跑到該規則時 KeyError——這是純粹的設定完整性檢查，不用真的跑回測。"""
    for rule in backtest_module.CHIPS_RULES:
        assert rule in backtest_module.CHIPS_RULE_CONFIG, f"{rule} 缺少 CHIPS_RULE_CONFIG 設定"


def _make_tdcc_db(tmp_path, name, trading_days):
    db = str(tmp_path / name)
    con = duckdb.connect(db)
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, streak INTEGER, week_chg DOUBLE)")
    con.execute("INSERT INTO shareholder VALUES ('2330','2026-07-03',2,1.5)")
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE, change_pct DOUBLE)")
    for d in trading_days:
        con.execute("INSERT INTO daily_prices VALUES ('2330', ?, 100.0, 0.1)", [d])
    con.close()
    return db


def test_tdcc_rule_delays_signal_by_publish_lag(tmp_path):
    """集保快照日（週五）本身不該發訊號——TDCC 實際公布會晚幾個交易日（見
    _TDCC_PUBLISH_LAG_TRADING_DAYS 說明），回測若直接在快照日下單，等於用了「當時
    實際上還查不到」的資料，是前瞻偏誤。訊號要延後到快照日+3個交易日才發，模擬
    「這天才真的查得到」（2026-07-18 bug-reports.md 記錄的修復）。"""
    trading_days = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07", "2026-07-08"]
    db = _make_tdcc_db(tmp_path, "tdcc.db", trading_days)

    # 快照日(07-03)本身跟延遲天數內(07-06/07-07)都還查不到，不該發訊號
    assert scan_chips_rule("2026-07-03", db, "tdcc_accumulation") == []
    assert scan_chips_rule("2026-07-06", db, "tdcc_accumulation") == []
    assert scan_chips_rule("2026-07-07", db, "tdcc_accumulation") == []
    # 快照日+3個交易日(07-08)才真的查得到，這天才發訊號
    assert scan_chips_rule("2026-07-08", db, "tdcc_accumulation")


def test_tdcc_rule_does_not_repeat_signal_after_publish_day(tmp_path):
    """公布延遲那天發過一次訊號後，再下一個交易日不該把同一份資料重複算成新訊號。"""
    trading_days = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
                     "2026-07-08", "2026-07-09"]
    db = _make_tdcc_db(tmp_path, "tdcc2.db", trading_days)

    assert scan_chips_rule("2026-07-08", db, "tdcc_accumulation")          # 公布日
    assert scan_chips_rule("2026-07-09", db, "tdcc_accumulation") == []    # 隔天不重複


def test_chips_rule_skips_dates_before_institutional_history(tmp_path, monkeypatch):
    db = str(tmp_path / "inst_range.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE)")
    con.execute("INSERT INTO institutional VALUES ('2330','2026-04-27')")
    con.close()

    def should_not_run(*args, **kwargs):
        raise AssertionError("資料源開始前不應呼叫 scan_institutional")

    monkeypatch.setattr(backtest_module, "scan_institutional", should_not_run)
    assert scan_chips_rule("2026-04-26", db, "joint_buy") == []


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


def test_regime_at_classifies_market_trend(tmp_path):
    from screener.backtest import _market_index, _regime_at
    # 造一段大盤：前 22 天每天 +0.5%(累積約 +11%)→ D 應判「多頭」
    rows = []
    price = 100.0
    for d in range(1, 26):
        price *= 1.005
        rows.append(("MKT", f"2026-05-{d:02d}", price, price))
    db = _make_prices_with_change(tmp_path, rows)
    idx = _market_index(db)
    sdates = sorted(idx.keys())
    reg = _regime_at(idx, sdates, pd.Timestamp("2026-05-25"), lookback=20, up=3.0, down=-3.0)
    assert reg == "多頭"


def test_print_summary_runs_with_new_columns(capsys):
    from screener.backtest import print_summary
    df = pd.DataFrame([
        {"signal_date":"2026-05-01","stock_id":"2330","entry_price":100.0,"no_fill":False,
         "regime":"多頭","ret_5":9.4,"bench_5":3.0,"excess_5":6.4},
        {"signal_date":"2026-05-02","stock_id":"2454","entry_price":50.0,"no_fill":True,
         "regime":"盤整","ret_5":-2.0,"bench_5":0.0,"excess_5":-2.0},
    ])
    print_summary(df, horizons=(5,))
    out = capsys.readouterr().out
    assert "超額" in out
    assert "中位數" in out
    assert "P25/P75" in out
    assert "期望值" not in out
    assert "訊號日 1 個" in out
    assert "股票 1 檔" in out
    assert "樣本期偏短" in out
    assert "訊號日不足" in out
    assert "多頭" in out or "regime" in out.lower()
    # 空 df 不 crash
    print_summary(pd.DataFrame(), horizons=(5,))


def test_print_summary_bearish_uses_negative_excess_and_keeps_limit_up(capsys):
    from screener.backtest import print_summary
    df = pd.DataFrame([
        {"signal_date":"2026-05-01","stock_id":"2330","entry_price":100.0,"no_fill":False,
         "regime":"盤整","ret_5":-3.0,"bench_5":0.0,"excess_5":-3.0},
        {"signal_date":"2026-05-02","stock_id":"2454","entry_price":50.0,"no_fill":True,
         "regime":"盤整","ret_5":5.0,"bench_5":0.0,"excess_5":5.0},
    ])

    print_summary(
        df, horizons=(5,), skip_no_fill=False, success_direction="negative",
    )
    out = capsys.readouterr().out
    assert "避險命中(超額<0)" in out
    assert "  50%" in out
    assert "訊號 2 筆" in out
    assert "風險警示不剔除漲停 1" in out


def test_margin_bearish_backtest_uses_observation_semantics(monkeypatch):
    calls = []

    def fake_run_backtest(*args, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(backtest_module, "run_backtest", fake_run_backtest)
    backtest_module.run_chips_rule_backtests("margin_bearish", db_path="ignored.db")

    assert calls[0]["cost_pct"] == 0.0
    assert backtest_module.CHIPS_RULE_CONFIG["margin_bearish"]["success_direction"] == "negative"
    assert backtest_module.CHIPS_RULE_CONFIG["margin_bearish"]["skip_no_fill"] is False


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
