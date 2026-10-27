from datetime import date

import duckdb
import pandas as pd

from recommend.publish import is_week_last_trading_day, missing_inputs, shareholder_asof

HOLIDAYS = {"2026-10-23", "2026-10-26"}


def _trading(d: str) -> bool:
    return date.fromisoformat(d).weekday() < 5 and d not in HOLIDAYS


def test_week_last_trading_day_handles_holidays():
    assert is_week_last_trading_day(date(2026, 10, 16), _trading)        # 週五
    assert not is_week_last_trading_day(date(2026, 10, 15), _trading)    # 週四，隔天週五開盤
    assert is_week_last_trading_day(date(2026, 10, 22), _trading)        # 週四，10/23 放假 → 集保資料日（實際 10/22 有一份）
    assert not is_week_last_trading_day(date(2026, 10, 27), _trading)    # 週二


def _db(tmp_path, inst, fh, sh):
    db = str(tmp_path / "t.db")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE)")
    con.execute("CREATE TABLE foreign_holdings (stock_id VARCHAR, date DATE)")
    con.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE)")
    for t, rows in (("institutional", inst), ("foreign_holdings", fh), ("shareholder", sh)):
        for r in rows:
            con.execute(f"INSERT INTO {t} VALUES (?, ?)", list(r))
    con.close()
    uni = tmp_path / "u.csv"
    pd.DataFrame([{"stock_id": "2330", "exchange": "TWSE"}, {"stock_id": "6488", "exchange": "TPEx"}]).to_csv(
        uni, index=False, encoding="utf-8-sig")
    return db, str(uni)


def test_missing_inputs_lists_each_market_and_shareholder(tmp_path):
    db, uni = _db(tmp_path, inst=[("2330", "2026-10-27")], fh=[], sh=[("2330", "2026-10-22")])
    assert missing_inputs(date(2026, 10, 27), _trading, db, uni) == ["上櫃三大法人", "上市外資持股", "上櫃外資持股"]


def test_ready_on_midweek_day_without_new_shareholder(tmp_path):
    full = [("2330", "2026-10-27"), ("6488", "2026-10-27")]
    db, uni = _db(tmp_path, inst=full, fh=full, sh=[("2330", "2026-10-22")])
    assert missing_inputs(date(2026, 10, 27), _trading, db, uni) == []
    assert shareholder_asof(date(2026, 10, 27), db) == "2026-10-22"


def test_week_last_day_waits_for_that_weeks_shareholder(tmp_path):
    full = [("2330", "2026-10-16"), ("6488", "2026-10-16")]
    db, uni = _db(tmp_path, inst=full, fh=full, sh=[("2330", "2026-10-08")])
    assert missing_inputs(date(2026, 10, 16), _trading, db, uni) == ["集保"]
    sub = tmp_path / "published"
    sub.mkdir()
    db2, uni2 = _db(sub, inst=full, fh=full, sh=[("2330", "2026-10-16")])
    assert missing_inputs(date(2026, 10, 16), _trading, db2, uni2) == []
