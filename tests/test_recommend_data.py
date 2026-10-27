import duckdb
import pandas as pd

from recommend.data import load_panel


def _db(tmp_path):
    path = str(tmp_path / "t.db")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,"
                " close DOUBLE, volume BIGINT, change DOUBLE, change_pct DOUBLE)")
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT,"
                " dealer_net BIGINT, total_net BIGINT)")
    con.execute("CREATE TABLE foreign_holdings (stock_id VARCHAR, date DATE, foreign_pct DOUBLE)")
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, total_shares BIGINT)")
    for d, c in (("2026-01-05", 100), ("2026-01-06", 110), ("2026-01-07", 111)):
        con.execute("INSERT INTO daily_prices VALUES ('2330', ?, ?, ?, ?, ?, 1000, 1, 1)", [d, c, c, c, c])
    con.execute("INSERT INTO institutional VALUES ('2330', '2026-01-06', 5000, 100, 0, 5100)")
    con.execute("INSERT INTO foreign_holdings VALUES ('2330', '2026-01-06', 70.5)")
    con.execute("INSERT INTO shareholder VALUES ('2330', '2026-01-06', 80.0, 1000000)")
    con.close()
    uni = tmp_path / "u.csv"
    pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "exchange": "TWSE", "meta_sector": "半導體",
                   "sub_sector": "", "note": ""}]).to_csv(uni, index=False, encoding="utf-8-sig")
    return path, str(uni)


def test_load_panel_merges_tables_and_asof_holders(tmp_path):
    db, uni = _db(tmp_path)
    p = load_panel(db_path=db, universe_path=uni)
    assert list(p["date"].dt.strftime("%m-%d")) == ["01-05", "01-06", "01-07"]
    r6 = p[p["date"] == "2026-01-06"].iloc[0]
    assert r6["foreign_net"] == 5000 and r6["foreign_pct"] == 70.5
    assert r6["big_pct"] == 80.0                       # 資料日當天可用
    r7 = p[p["date"] == "2026-01-07"].iloc[0]
    assert r7["big_pct"] == 80.0 and pd.isna(r7["foreign_net"])  # 集保 asof 往後帶；當天沒籌碼為 NaN
    assert r7["big_date"] == pd.Timestamp("2026-01-06")
    assert p["total_shares"].iloc[0] == 1_000_000      # 集保之前的日子用最早一筆往回補
    assert p["meta_sector"].iloc[0] == "半導體"


def test_event_factors_and_multiplier_back_adjust_before_event():
    """還原價：事件日前的價格 × 參考價／前收；事件當天起不乘（2026-10-27，規格 §11）。"""
    from recommend.data import adj_multiplier, event_factors
    px = pd.DataFrame({"stock_id": "6669", "date": pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"]),
                       "close": [7095.0, 7800.0, 2610.0, 2475.0]})
    ev = pd.DataFrame([{"stock_id": "6669", "date": "2026-09-02", "pre_close": 7800.0, "ref": 2615.0}])
    m = adj_multiplier(px, event_factors(ev, px))
    assert list(m.round(6)) == [round(2615 / 7800, 6)] * 2 + [1.0, 1.0]
    assert round(7800 * m.iloc[1], 2) == 2615.0                    # 除權前一天還原後接得上除權當天


def test_event_without_pre_close_uses_previous_close_and_chains_events():
    from recommend.data import adj_multiplier, event_factors
    px = pd.DataFrame({"stock_id": "8101", "date": pd.to_datetime(["2024-08-01", "2024-11-19", "2025-07-01", "2025-07-02"]),
                       "close": [1.90, 10.45, 20.0, 19.0]})
    ev = pd.DataFrame([{"stock_id": "8101", "date": "2024-11-19", "pre_close": None, "ref": 9.50},    # TWT84U 補的，沒有前收
                       {"stock_id": "8101", "date": "2025-07-02", "pre_close": 20.0, "ref": 19.0}])
    f = event_factors(ev, px)
    assert round(f.iloc[0]["factor"], 6) == round(9.50 / 1.90, 6)  # 前收用事件日前最後一筆收盤
    m = adj_multiplier(px, f)
    assert round(m.iloc[0], 6) == round(5.0 * 0.95, 6) and round(m.iloc[2], 6) == 0.95 and m.iloc[3] == 1.0


def test_load_panel_attaches_adj_from_events(tmp_path):
    db, uni = _db(tmp_path)
    ev = tmp_path / "ev.csv"
    pd.DataFrame([{"stock_id": "2330", "date": "2026-01-07", "pre_close": 110.0, "ref": 99.0, "src": "除權息"}]).to_csv(ev, index=False)
    p = load_panel(db_path=db, universe_path=uni, events_path=str(ev))
    assert list(p["adj"].round(6)) == [0.9, 0.9, 1.0] and list(p["close"]) == [100, 110, 111]   # 原始價不動
    assert (load_panel(db_path=db, universe_path=uni)["adj"] == 1.0).all()             # 沒有事件表
