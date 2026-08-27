import duckdb
import pandas as pd
from processors.flow_watch import get_flow_watch


def _make_flow_db(tmp_path, name, institutional_rows, price_rows):
    """institutional_rows: list of (stock_id,'YYYY-MM-DD',total_net)
    price_rows: list of (stock_id,'YYYY-MM-DD',close,volume)"""
    db = str(tmp_path / name)
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE, total_net BIGINT)")
    if institutional_rows:
        con.executemany(
            "INSERT INTO institutional VALUES (?, ?, ?)",
            [(s, pd.to_datetime(d).date(), n) for (s, d, n) in institutional_rows],
        )
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE, volume BIGINT)")
    if price_rows:
        con.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?)",
            [(s, pd.to_datetime(d).date(), c, v) for (s, d, c, v) in price_rows],
        )
    con.close()
    return db


def test_get_flow_watch_ranks_by_today_net_buy_and_computes_ratio_and_turnover(tmp_path):
    institutional_rows = [
        ("2330", "2026-07-01", 5000000), ("2330", "2026-06-30", 1000000),
        ("2317", "2026-07-01", 3000000), ("2317", "2026-06-30", 3000000),
    ]
    price_rows = [
        ("2330", "2026-07-01", 600.0, 20000000),
        ("2317", "2026-07-01", 100.0, 50000000),
    ]
    db = _make_flow_db(tmp_path, "flow.db", institutional_rows, price_rows)
    universe_df = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
        {"stock_id": "2317", "stock_name": "鴻海", "meta_sector": "電子代工"},
    ])

    result = get_flow_watch(universe_df, db_path=db, trade_date="2026-07-01", top_n=10, avg_window=20)

    assert [r["stock_id"] for r in result] == ["2330", "2317"]  # 2330買超較多排第一
    assert result[0]["stock_name"] == "台積電"
    assert result[0]["net_buy_lots"] == 5000  # 5,000,000股/1000
    assert result[0]["vs_avg20_ratio"] == 5.0  # 今日500萬 / 過去一筆(6/30)100萬均值 = 5.0
    assert result[0]["turnover"] == round(600.0 * 20000000)


def test_get_flow_watch_returns_empty_list_when_no_institutional_data_for_date(tmp_path):
    db = _make_flow_db(tmp_path, "empty.db", [], [])
    result = get_flow_watch(pd.DataFrame(columns=["stock_id", "stock_name", "meta_sector"]),
                             db_path=db, trade_date="2026-07-01")
    assert result == []


def test_get_flow_watch_handles_zero_history_average_as_none_ratio(tmp_path):
    """歷史均值查不到（新股或資料不足）時，vs_avg20_ratio 該是 None，不能除以零。"""
    institutional_rows = [("9999", "2026-07-01", 1000000)]  # 只有今天一筆，沒有歷史
    price_rows = [("9999", "2026-07-01", 50.0, 1000000)]
    db = _make_flow_db(tmp_path, "nohist.db", institutional_rows, price_rows)
    universe_df = pd.DataFrame([{"stock_id": "9999", "stock_name": "測試股", "meta_sector": "測試"}])

    result = get_flow_watch(universe_df, db_path=db, trade_date="2026-07-01")

    assert result[0]["vs_avg20_ratio"] is None
