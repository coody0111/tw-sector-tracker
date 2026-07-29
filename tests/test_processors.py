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


def test_calc_meta_chips_signals_margin_not_zeroed_when_margin_lags_inst(tmp_path):
    """回歸（#5）：margin 整表比 institutional 晚一天時，舊版用 institutional 的 today
    去過濾 margin → margin_change_today/balance 全被歸零。修正後 margin 用自己的最新日期，
    數字不該歸零。"""
    db_path = tmp_path / "test.db"
    universe = _make_universe([
        ("1101", "測試族群", "TWSE"),
        ("1102", "測試族群", "TWSE"),
    ])
    # institutional 最新到 07-07；margin 最新只到 07-06（晚一天）
    _seed_chips_db(db_path, [
        ("1101", "2026-07-06", 1000, 100),
        ("1101", "2026-07-07", 1000, 100),
        ("1102", "2026-07-06", 500, 50),
        ("1102", "2026-07-07", 500, 50),
    ], margin_rows=[
        ("1101", "2026-07-06", 10000, 800),
        ("1102", "2026-07-06", 5000, 300),
    ])

    result = calc_meta_chips_signals(universe, db_path=str(db_path), lookback=5)
    # margin 應退到自己的 07-06、加總 800+300=1100，不該因對不到 institutional 的 07-07 而歸零
    assert result["測試族群"]["margin_change_today"] == 1100, "margin 落後一天時不該被歸零"
    assert result["測試族群"]["margin_balance_today"] == 15000


# ── get_stock_chips_ranking（#3 margin skew / #4 NaN close）──────────────
from processors.performance import get_stock_chips_ranking


def _seed_ranking_db(db_path, inst_rows, margin_rows, price_rows):
    """inst:(sid,date,fn,tn) margin:(sid,date,bal,chg) price:(sid,date,close,change_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT)")
    con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?)", inst_rows)
    con.execute("CREATE TABLE margin (stock_id VARCHAR, date DATE, margin_balance BIGINT, margin_change BIGINT)")
    con.executemany("INSERT INTO margin VALUES (?, ?, ?, ?)", margin_rows)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE, change_pct DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?)", price_rows)
    con.close()


def test_get_stock_chips_ranking_margin_alert_survives_margin_lag(tmp_path):
    """回歸（#3）：margin 比 institutional 晚一天時，舊版用 MAX(institutional) 去查 margin
    → 融資警示整批消失。修正後 margin 用自己最新日期，警示仍在。"""
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([("2330", "台積電", "半導體")], columns=["stock_id", "stock_name", "meta_sector"])
    _seed_ranking_db(
        db_path,
        inst_rows=[("2330", "2026-07-07", 1000, 100)],       # institutional 最新 07-07
        margin_rows=[("2330", "2026-07-06", 100000, 8000)],  # margin 只到 07-06、融資 +8%
        price_rows=[("2330", "2026-07-07", 950.0, 1.5)],
    )
    result = get_stock_chips_ranking(universe, db_path=str(db_path))
    assert len(result["margin_alerts"]) == 1, "margin 落後一天時融資警示不該消失（#3）"
    assert result["margin_alerts"][0]["stock_id"] == "2330"


def test_margin_alert_uses_previous_balance_as_denominator(tmp_path):
    """今日餘額 100,000、增加 5,000：以今日餘額算剛好 5% 不會觸發，
    但以前一日 95,000 為分母是 5.26%，應正確觸發。"""
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([("2330", "台積電", "半導體")], columns=["stock_id", "stock_name", "meta_sector"])
    _seed_ranking_db(
        db_path,
        inst_rows=[("2330", "2026-07-07", 1000, 100)],
        margin_rows=[("2330", "2026-07-07", 100000, 5000)],
        price_rows=[("2330", "2026-07-07", 950.0, 1.5)],
    )
    result = get_stock_chips_ranking(universe, db_path=str(db_path))
    assert result["margin_alerts"][0]["alert_pct"] == 5.26
    assert result["margin_alerts"][0]["prev_margin_balance"] == 95000


def test_get_stock_chips_ranking_handles_null_close_without_crash(tmp_path):
    """回歸（#4）：某檔 close 為 NULL（停牌/全額交割）→ DuckDB→pandas 變 NaN。
    舊版 price_map 沒洗 NaN，chips_generator._price_cell 的 int(nan) 會 crash、整頁停更。
    這裡驗 get_stock_chips_ranking 回傳的 close 是 None（已洗），不是 NaN。"""
    import math
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([("2330", "台積電", "半導體")], columns=["stock_id", "stock_name", "meta_sector"])
    _seed_ranking_db(
        db_path,
        inst_rows=[("2330", "2026-07-07", 5000, 100)],       # 外資大買 → 進 top_buy
        margin_rows=[("2330", "2026-07-07", 100000, 200)],
        price_rows=[("2330", "2026-07-07", None, None)],      # close = NULL
    )
    result = get_stock_chips_ranking(universe, db_path=str(db_path))
    buys = result["foreign_top_buy"]
    assert len(buys) == 1
    close = buys[0]["close"]
    assert close is None or not (isinstance(close, float) and math.isnan(close)), \
        "NULL close 應洗成 None、不是 NaN（避免 _price_cell int(nan) crash）"


def test_get_stock_chips_ranking_carries_per_row_data_date(tmp_path):
    """新 🔴（融資跨交易日混用）：per-stock 取最新一筆時，兩交易所進度不同會靜默混用不同
    交易日。每一列要帶自己的真實資料日期 data_date，畫面才能誠實標示，不會把前一天的數字
    謊報成同一天。"""
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame(
        [("2330", "台積電", "半導體"), ("6488", "環球晶", "半導體")],
        columns=["stock_id", "stock_name", "meta_sector"],
    )
    _seed_ranking_db(
        db_path,
        # 法人：2330(上市)停在 07-08、6488(上櫃)到 07-09（兩所進度差一天）
        inst_rows=[("2330", "2026-07-08", 5000, 100), ("6488", "2026-07-09", 6000, 200)],
        # margin：2330 只到 07-08、6488 到 07-09，兩檔都觸發融資警示(>5%)
        margin_rows=[("2330", "2026-07-08", 100000, 8000), ("6488", "2026-07-09", 100000, 9000)],
        price_rows=[("2330", "2026-07-08", 950.0, 1.5), ("6488", "2026-07-09", 600.0, 2.0)],
    )
    result = get_stock_chips_ranking(universe, db_path=str(db_path))

    # margin 警示每列帶自己的資料日期（不是統一 chips_date）
    md = {a["stock_id"]: a["data_date"] for a in result["margin_alerts"]}
    assert md["2330"] == "2026-07-08"
    assert md["6488"] == "2026-07-09"

    # 外資榜同樣帶 per-row 資料日期（同一個 per-stock-latest 病）
    fd = {r["stock_id"]: r["data_date"] for r in result["foreign_top_buy"]}
    assert fd["2330"] == "2026-07-08"
    assert fd["6488"] == "2026-07-09"


def test_get_stock_chips_ranking_survives_missing_foreign_holdings_table(tmp_path):
    """外資持股%（foreign_holdings）是新資料源，這張表可能還沒建立（例如尚未跑過任何一次
    _update_chips_db）。缺這張表不該讓整個籌碼排行連 institutional/margin 都一起壞掉——
    只有 foreign_pct 那個欄位缺值（None），其他既有資料照常回傳。"""
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([("2330", "台積電", "半導體")], columns=["stock_id", "stock_name", "meta_sector"])
    _seed_ranking_db(
        db_path,
        inst_rows=[("2330", "2026-07-07", 1000, 100)],
        margin_rows=[("2330", "2026-07-07", 100000, 8000)],
        price_rows=[("2330", "2026-07-07", 950.0, 1.5)],
    )
    result = get_stock_chips_ranking(universe, db_path=str(db_path))
    assert len(result["foreign_top_buy"]) == 1, "缺 foreign_holdings 表不該讓整個籌碼排行回空"
    assert result["foreign_top_buy"][0]["foreign_pct"] is None


# ── 大盤分級儀表板（Market Regime Dashboard）───────────────────────────
from processors.performance import (
    calc_market_breadth,
    calc_capital_concentration,
    classify_market_regime,
)


def _breadth_prices(pcts):
    """pcts: list of change_pct → prices_df（stock_id 自動編號）"""
    rows = [[f"{1000+i}", f"股{i}", 100.0, 0.0, p, 1000] for i, p in enumerate(pcts)]
    return _make_price_df(rows)


def test_calc_market_breadth_basic_ratio():
    prices = _breadth_prices([1.0, 2.0, -1.0, 0.0])  # 2 漲 1 跌 1 平
    b = calc_market_breadth(prices)
    assert b["up_count"] == 2
    assert b["down_count"] == 1
    assert b["flat_count"] == 1
    assert b["total"] == 4
    assert abs(b["breadth_ratio"] - 0.5) < 1e-9


def test_calc_market_breadth_all_up():
    b = calc_market_breadth(_breadth_prices([1.0, 3.0, 0.5]))
    assert b["breadth_ratio"] == 1.0


def test_calc_market_breadth_empty_is_safe():
    b = calc_market_breadth(pd.DataFrame())
    assert b["total"] == 0
    assert b["breadth_ratio"] == 0.0


def test_calc_market_breadth_ignores_nan_change_pct():
    prices = _breadth_prices([1.0, -1.0])
    prices.loc[len(prices)] = ["9999", "無行情", None, None, float("nan"), 0]
    b = calc_market_breadth(prices)
    assert b["total"] == 2  # NaN 不計入分母


def test_calc_capital_concentration_heavyweight_leading():
    # 權值股(2330,2454) 大漲，非權值股(1111,2222) 收黑 → divergence 明顯為正
    prices = _make_price_df([
        ["2330", "台積電", 900, 20, 2.5, 1000],
        ["2454", "聯發科", 800, 10, 1.5, 1000],
        ["1111", "小型A", 50, -1, -1.0, 1000],
        ["2222", "小型B", 60, -1, -1.0, 1000],
    ])
    c = calc_capital_concentration(prices, ["2330", "2454"])
    assert c["heavyweight_avg_pct"] == 2.0
    assert c["broad_avg_pct"] == -1.0
    assert c["divergence"] == 3.0  # 2.0 - (-1.0)


def test_calc_capital_concentration_broad_leading():
    # 非權值股領漲、權值股收黑 → divergence 為負（中小型輪動）
    prices = _make_price_df([
        ["2330", "台積電", 900, -9, -1.0, 1000],
        ["1111", "小型A", 50, 1, 2.0, 1000],
        ["2222", "小型B", 60, 1, 2.0, 1000],
    ])
    c = calc_capital_concentration(prices, ["2330"])
    assert c["heavyweight_avg_pct"] == -1.0
    assert c["broad_avg_pct"] == 2.0
    assert c["divergence"] == -3.0


def test_calc_capital_concentration_missing_side_returns_none():
    # 沒有任何權值股在盤面 → heavyweight_avg 與 divergence 皆 None（無法比較）
    prices = _make_price_df([
        ["1111", "小型A", 50, 1, 2.0, 1000],
    ])
    c = calc_capital_concentration(prices, ["2330"])
    assert c["heavyweight_avg_pct"] is None
    assert c["divergence"] is None


def test_classify_regime_five_tiers_at_boundaries():
    # 大漲：指數 ≥ +1.5% 且廣度 ≥ 65%
    assert classify_market_regime(1.5, 0.65, None)["tier"] == "大漲"
    # 小漲：指數 ≥ +0.3% 且廣度 ≥ 50%
    assert classify_market_regime(0.3, 0.50, None)["tier"] == "小漲"
    # 持平：-0.3% ~ +0.3%
    assert classify_market_regime(0.0, 0.50, None)["tier"] == "持平"
    # 小跌：指數 ≤ -0.3% 且廣度 ≤ 50%
    assert classify_market_regime(-0.3, 0.40, None)["tier"] == "小跌"
    # 大跌：指數 ≤ -1.5% 且廣度 ≤ 35%
    assert classify_market_regime(-1.5, 0.30, None)["tier"] == "大跌"


def test_classify_regime_index_up_but_weak_breadth_falls_to_flat():
    """指數落在『小漲』區間（+0.6%）但廣度不到 50% → 保守退回『持平』。"""
    assert classify_market_regime(0.6, 0.45, None)["tier"] == "持平"


def test_classify_regime_strong_index_medium_breadth_degrades_to_small_up():
    """指數 +2%（大漲區）但廣度只有 55%（<65%）→ 降級到『小漲』，不是大漲也不是持平。"""
    assert classify_market_regime(2.0, 0.55, None)["tier"] == "小漲"


def test_classify_regime_concentration_directions():
    # 落差 ≥ 門檻且為正 → 權值股撐盤
    r1 = classify_market_regime(0.5, 0.45, divergence=2.9)
    assert r1["is_concentrated"] is True
    assert r1["concentration_direction"] == "權值股撐盤"
    # 落差 ≥ 門檻且為負 → 中小型輪動
    r2 = classify_market_regime(0.1, 0.55, divergence=-2.5)
    assert r2["is_concentrated"] is True
    assert r2["concentration_direction"] == "中小型輪動"
    # 落差在門檻內 → 不標記集中
    r3 = classify_market_regime(0.1, 0.50, divergence=1.0)
    assert r3["is_concentrated"] is False
    assert r3["concentration_direction"] is None
    # divergence 為 None（無法比較）→ 不標記集中，不 crash
    r4 = classify_market_regime(0.1, 0.50, divergence=None)
    assert r4["is_concentrated"] is False


def test_calc_stock_sparklines_includes_daily_volume_and_ratio(tmp_path):
    import duckdb
    from processors.performance import calc_stock_sparklines

    db_path = str(tmp_path / "volume-history.db")
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE, volume BIGINT,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2330", "2026-07-13", 1.0, 10000, 900.0, 905.0, 898.0, 901.0),
            ("2330", "2026-07-14", -0.5, 20000, 901.0, 902.0, 895.0, 896.0),
            ("2330", "2026-07-15", 1.5, 45000, 896.0, 910.0, 895.0, 909.0),
        ],
    )
    con.close()

    result = calc_stock_sparklines(
        pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=3
    )["2330"]

    assert result["pcts"] == [1.0, -0.5, 1.5]
    assert result["volumes"] == [10000, 20000, 45000]
    assert result["dates"] == ["07/13", "07/14", "07/15"]
    assert result["avg_volume"] == 15000
    assert result["vol_ratio"] == 3.0


def test_calc_stock_sparklines_includes_ohlc_for_candlestick_chart(tmp_path):
    """Cody要求個股走勢圖用K棒(candlestick)呈現——確認calc_stock_sparklines()
    有把open/high/low/close這四個欄位的近N日歷史一併回傳，供前端畫K棒。"""
    import duckdb
    from processors.performance import calc_stock_sparklines

    db_path = str(tmp_path / "ohlc-history.db")
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE, volume BIGINT,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2330", "2026-07-14", -0.5, 20000, 901.0, 902.0, 895.0, 896.0),
            ("2330", "2026-07-15", 1.5, 45000, 896.0, 910.0, 895.0, 909.0),
        ],
    )
    con.close()

    result = calc_stock_sparklines(
        pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=2
    )["2330"]

    assert result["opens"] == [901.0, 896.0]
    assert result["highs"] == [902.0, 910.0]
    assert result["lows"] == [895.0, 895.0]
    assert result["closes"] == [896.0, 909.0]


# ── _streak_and_windows_as_of（任意時間點的 streak/上週/本週窗口回推）─────
from processors.performance import _streak_and_windows_as_of


def test_streak_and_windows_as_of_computes_this_and_last_week():
    """thisWeek=最近5天(index 5~9)複利報酬，lastWeek=再往前5天(index 0~4)。
    全部+1.0%：thisWeek=(1.01^5-1)*100≈5.10，lastWeek同理也≈5.10。"""
    daily_pcts = [1.0] * 10  # index 0~9，10天歷史，cutoff_index=9剛好卡在邊界
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result is not None
    assert result["this_week_pct"] == 5.1
    assert result["last_week_pct"] == 5.1
    assert result["streak"] == 10  # 連漲10天(index 0~9全部+1.0%)


def test_streak_and_windows_as_of_returns_none_when_insufficient_history():
    """cutoff_index=8時只有9天資料(index 0~8)，不足10天(thisWeek5+lastWeek5)，回None。"""
    daily_pcts = [1.0] * 9
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=8)
    assert result is None


def test_streak_and_windows_as_of_streak_resets_on_direction_change():
    """連漲3天後轉跌，streak應該是-1(今天跌，只算今天這1天)，不是累加正負號混合。"""
    daily_pcts = [1.0, -0.5, -0.5, -0.5, 1.0, 1.0, 1.0, 1.0, 1.0, -0.3]
    # index 9(今天)是-0.3，往前看index 8是+1.0方向不同 → streak=-1
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result["streak"] == -1


def test_streak_and_windows_as_of_zero_pct_breaks_streak_to_zero():
    """今天漲跌%剛好是0(持平)時，streak視為0（跟streak_utils.calc_streak()既有慣例一致）。"""
    daily_pcts = [1.0] * 9 + [0.0]
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result["streak"] == 0


def test_streak_and_windows_as_of_five_days_ago_reuses_todays_last_week_as_this_week():
    """驗證窗口重疊關係：cutoff_index往前推5(等於算「5天前的今天」)時，它的this_week_pct
    應該等於原本cutoff_index算出來的last_week_pct（同一個窗口，只是換了個稱呼）——
    這是轉折點回推算法能省一次計算的關鍵前提，必須驗證是真的邏輯保證，不是巧合。"""
    daily_pcts = [0.5, 0.5, -0.3, -0.3, -0.3, 1.2, 1.2, 1.2, 1.2, 1.2, 0.8, 0.8, 0.8, 0.8, 0.8]
    today = _streak_and_windows_as_of(daily_pcts, cutoff_index=14)
    five_days_ago = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert five_days_ago is not None
    assert five_days_ago["this_week_pct"] == today["last_week_pct"]


def test_streak_and_windows_as_of_returns_none_when_cutoff_index_out_of_bounds():
    """cutoff_index超過daily_pcts實際長度時(呼叫端參數對不上)，要回None，不能讓切片
    悄悄回傳過短/空的窗口、_compound()對空list算出0.0這種「看起來有效但其實是假資料」
    的結果（code review抓到：這違反Global Constraints「資料不足時回None，不硬湊」）。"""
    daily_pcts = [1.0] * 5  # 只有5天資料
    result = _streak_and_windows_as_of(daily_pcts, cutoff_index=9)
    assert result is None


# ── calc_meta_heatgrid_windows（族群熱區格每日窗口 + 5天前回推）──────────
import duckdb
from processors.performance import calc_meta_heatgrid_windows


def _seed_heatgrid_db(db_path, price_rows):
    """price_rows: list of (stock_id, date, change_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)", price_rows)
    con.close()


def test_calc_meta_heatgrid_windows_computes_today_and_five_days_ago(tmp_path):
    """15天歷史，單一族群單一股票，全部+1.0%（連漲）：today跟5天前都應該算得出來(不是None)。"""
    db_path = tmp_path / "test.db"
    rows = [("1000", f"2026-06-{d:02d}", 1.0) for d in range(1, 16)]  # 06-01~06-15，15天
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    assert "測試族群" in result
    row = result["測試族群"]
    assert row["streak_today"] == 15
    assert row["streak_5d_ago"] == 10
    assert row["this_week_pct_today"] is not None
    assert row["last_week_pct_5d_ago"] is not None


def test_calc_meta_heatgrid_windows_five_days_ago_none_when_insufficient_history(tmp_path):
    """只有10天歷史：today算得出來(剛好卡在邊界)，5天前不足9天(_streak_and_windows_as_of的
    cutoff_index=4<9)，5天前的欄位應該是None，但不影響today的值。"""
    db_path = tmp_path / "test.db"
    rows = [("2000", f"2026-06-{d:02d}", 1.0) for d in range(1, 11)]  # 10天
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "2000", "meta_sector": "資料不足族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    row = result["資料不足族群"]
    assert row["streak_today"] == 10
    assert row["this_week_pct_today"] is not None
    assert row["streak_5d_ago"] is None
    assert row["last_week_pct_5d_ago"] is None


def test_calc_meta_heatgrid_windows_averages_multiple_stocks_in_same_meta(tmp_path):
    """族群內兩檔股票，每日取平均漲跌%再算streak/window，不是逐股各自算。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 16):
        rows.append(("3000", f"2026-06-{d:02d}", 2.0))
        rows.append(("3001", f"2026-06-{d:02d}", 0.0))
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "3000", "meta_sector": "混合族群"},
        {"stock_id": "3001", "meta_sector": "混合族群"},
    ])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    # 每日平均 = (2.0+0.0)/2 = 1.0，15天複利 this_week_today ≈ (1.01^5-1)*100 = 5.10
    assert result["混合族群"]["this_week_pct_today"] == 5.1


def test_calc_meta_heatgrid_windows_returns_empty_dict_when_no_price_data(tmp_path):
    db_path = tmp_path / "empty.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.close()
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))
    assert result == {}


def test_calc_meta_heatgrid_windows_none_when_sector_has_real_gap_inside_window(tmp_path):
    """族群在today_index往前10天的視窗內有真實缺值(例如剛掛牌，之前完全沒交易)時，
    不能被fillna(0.0)悄悄頂替成假的平盤天數算出看似有效的streak/window_pct——
    這是code review抓到的問題：Task 1的cutoff_index<9只防「歷史太短」，不防
    「全市場聯集夠長，但這個族群自己在視窗內有缺值」這種情況。"""
    db_path = tmp_path / "test.db"
    # 全市場有20天資料(足夠長)，但這個族群只在最近8天有交易(前12天完全沒進DB)，
    # 今天視窗(today_index往前10天)會涵蓋到這個族群還沒交易的日子 → 應該是None
    rows = [("4000", f"2026-06-{d:02d}", 1.0) for d in range(13, 21)]  # 只有8天
    _seed_heatgrid_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "4000", "meta_sector": "剛掛牌族群"}])

    result = calc_meta_heatgrid_windows(universe, db_path=str(db_path))

    row = result["剛掛牌族群"]
    assert row["streak_today"] is None
    assert row["this_week_pct_today"] is None


import duckdb
from processors.performance import calc_meta_rank_history


def _seed_rank_history_db(db_path, price_rows):
    """price_rows: list of (stock_id, date, change_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?)", price_rows)
    con.close()


def test_calc_meta_rank_history_ranks_metas_by_weekly_compound_return(tmp_path):
    """3個族群、剛好1週(5個交易日)資料：每天固定漲跌%，驗證複利報酬排序正確，
    本週排名=1的族群in_top10_this_week應為True。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 6):  # 5天
        rows.append(("A1", f"2026-06-{d:02d}", 3.0))   # 族群A：每天+3%
        rows.append(("B1", f"2026-06-{d:02d}", 1.0))   # 族群B：每天+1%
        rows.append(("C1", f"2026-06-{d:02d}", -2.0))  # 族群C：每天-2%
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "A1", "meta_sector": "族群A"},
        {"stock_id": "B1", "meta_sector": "族群B"},
        {"stock_id": "C1", "meta_sector": "族群C"},
    ])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert result["族群A"]["weekly_ranks"] == [1]
    assert result["族群B"]["weekly_ranks"] == [2]
    assert result["族群C"]["weekly_ranks"] == [3]
    assert result["族群A"]["in_top10_this_week"] is True
    assert result["族群C"]["in_top10_this_week"] is True  # 只有3個族群，前10名門檻涵蓋全部


def test_calc_meta_rank_history_uses_current_classification_not_historical(tmp_path):
    """驗證ADR-0001的核心承諾：排名一律用『現在傳進來的』universe_df分類回推，不管
    歷史上這支股票曾經屬於哪個族群——同一批價格資料，換一個universe_df(股票改分類)，
    排名歷史應該跟著變。"""
    db_path = tmp_path / "test.db"
    rows = [("X1", f"2026-06-{d:02d}", 5.0) for d in range(1, 6)]
    _seed_rank_history_db(db_path, rows)

    universe_old = pd.DataFrame([{"stock_id": "X1", "meta_sector": "舊分類族群"}])
    universe_new = pd.DataFrame([{"stock_id": "X1", "meta_sector": "新分類族群"}])

    result_old = calc_meta_rank_history(universe_old, db_path=str(db_path), weeks_back=5)
    result_new = calc_meta_rank_history(universe_new, db_path=str(db_path), weeks_back=5)

    assert "舊分類族群" in result_old and "新分類族群" not in result_old
    assert "新分類族群" in result_new and "舊分類族群" not in result_new
    assert result_new["新分類族群"]["weekly_ranks"] == result_old["舊分類族群"]["weekly_ranks"]


def test_calc_meta_rank_history_counts_consecutive_top10_streak(tmp_path):
    """3週資料，某族群連續3週都是排名第1(前10)：consecutive_weeks_in_top10應為3。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 16):  # 15天 = 3週
        rows.append(("A1", f"2026-06-{d:02d}", 3.0))   # 永遠第一
        rows.append(("B1", f"2026-06-{d:02d}", 1.0))
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([
        {"stock_id": "A1", "meta_sector": "常勝族群"},
        {"stock_id": "B1", "meta_sector": "普通族群"},
    ])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert result["常勝族群"]["weekly_ranks"] == [1, 1, 1]
    assert result["常勝族群"]["in_top10_this_week"] is True
    assert result["常勝族群"]["consecutive_weeks_in_top10"] == 3


def test_calc_meta_rank_history_last_top10_week_when_not_currently_ranked(tmp_path):
    """12個族群(1個主角+11個陪榜)、4週資料：族群總數>10，前10名門檻才有意義。
    主角族群前2週表現最強(排名1)，後2週表現墊底(排名12，掉出前10)。驗證not
    in_top10_this_week時，能回頭找出「最近一次進前10是第幾週、當時排第幾名」。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 21):  # 20天 = 4週
        rows.append(("A1", f"2026-06-{d:02d}", 5.0))
    for d in range(1, 21):
        # 11個陪榜族群，確保族群總數是12個(>10)，這樣排名不是全部都算前10
        for i in range(11):
            rows.append((f"P{i}", f"2026-06-{d:02d}", 0.5))
    # 讓A1只在前2週表現最好(第1名)，後2週表現變最差(單獨改後兩週的change_pct)
    rows = [r for r in rows if not (r[0] == "A1" and int(r[1][-2:]) > 10)]
    rows += [("A1", f"2026-06-{d:02d}", -5.0) for d in range(11, 21)]  # 後兩週變最差
    _seed_rank_history_db(db_path, rows)

    universe_rows = [{"stock_id": "A1", "meta_sector": "起伏族群"}]
    universe_rows += [{"stock_id": f"P{i}", "meta_sector": f"陪榜{i}"} for i in range(11)]
    universe = pd.DataFrame(universe_rows)

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    row = result["起伏族群"]
    assert row["weekly_ranks"][0] == 1   # 第1週最強
    assert row["weekly_ranks"][1] == 1   # 第2週最強
    assert row["weekly_ranks"][-1] > 10  # 本週(最後一週)跌到10名外
    assert row["in_top10_this_week"] is False
    assert row["last_top10_week_index"] == 1  # 最近一次進前10是index1(第2週)
    assert row["last_top10_rank"] == 1


def test_calc_meta_rank_history_never_in_top10_returns_none_lookback(tmp_path):
    """族群近5週都沒進過前10：last_top10_week_index/last_top10_rank都要是None，
    不是隨便回0或其他假值。"""
    db_path = tmp_path / "test.db"
    rows = []
    for d in range(1, 6):
        rows.append(("A1", f"2026-06-{d:02d}", -5.0))  # 永遠墊底
        for i in range(11):
            rows.append((f"P{i}", f"2026-06-{d:02d}", 1.0))
    _seed_rank_history_db(db_path, rows)
    universe_rows = [{"stock_id": "A1", "meta_sector": "常年墊底"}]
    universe_rows += [{"stock_id": f"P{i}", "meta_sector": f"陪榜{i}"} for i in range(11)]
    universe = pd.DataFrame(universe_rows)

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    row = result["常年墊底"]
    assert row["in_top10_this_week"] is False
    assert row["last_top10_week_index"] is None
    assert row["last_top10_rank"] is None
    assert row["consecutive_weeks_in_top10"] == 0


def test_calc_meta_rank_history_partial_weeks_when_insufficient_history(tmp_path):
    """只有8天歷史(不滿2週=10天)：只能算出1個完整週，weekly_ranks長度應該是1，
    不強湊成weeks_back(5)長度、不用假資料補足。"""
    db_path = tmp_path / "test.db"
    rows = [("A1", f"2026-06-{d:02d}", 1.0) for d in range(1, 9)]  # 8天
    _seed_rank_history_db(db_path, rows)
    universe = pd.DataFrame([{"stock_id": "A1", "meta_sector": "新資料族群"}])

    result = calc_meta_rank_history(universe, db_path=str(db_path), weeks_back=5)

    assert len(result["新資料族群"]["weekly_ranks"]) == 1


def test_calc_meta_rank_history_returns_empty_dict_when_no_price_data(tmp_path):
    db_path = tmp_path / "empty.db"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, change_pct DOUBLE)")
    con.close()
    universe = pd.DataFrame([{"stock_id": "1000", "meta_sector": "測試族群"}])

    result = calc_meta_rank_history(universe, db_path=str(db_path))
    assert result == {}


def test_calc_avg20_close_returns_average_of_available_days(tmp_path):
    import duckdb
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?)",
        [
            ("2330", "2026-07-13", 900.0),
            ("2330", "2026-07-14", 910.0),
            ("2330", "2026-07-15", 920.0),
        ],
    )
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)

    assert result["2330"] == 910.0  # (900+910+920)/3


def test_calc_avg20_close_uses_actual_days_when_insufficient_history(tmp_path):
    """股票只有8天歷史(不滿20天lookback窗口)：用實際8天平均，不強湊、不回None。"""
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20-partial.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?)",
        [("2330", f"2026-07-{d:02d}", 100.0 + d) for d in range(1, 9)],  # 8天
    )
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)

    expected = round(sum(100.0 + d for d in range(1, 9)) / 8, 2)
    assert result["2330"] == expected


def test_calc_avg20_close_returns_empty_dict_when_no_price_data(tmp_path):
    import duckdb
    from processors.performance import calc_avg20_close

    db_path = str(tmp_path / "avg20-empty.db")
    con = duckdb.connect(db_path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.close()

    result = calc_avg20_close(pd.DataFrame([{"stock_id": "2330"}]), db_path=db_path, lookback=20)
    assert result == {}
