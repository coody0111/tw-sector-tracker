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
