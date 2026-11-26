from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

import scripts.healthcheck as hc


def _weekday(d: date):
    return d.weekday() < 5


def _days(end: date, n: int) -> list[date]:
    return [d.date() for d in pd.bdate_range(end=end, periods=n)]


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    c.execute("CREATE TABLE shareholder (stock_id VARCHAR, date DATE)")
    c.execute("CREATE TABLE monthly_revenue (stock_id VARCHAR, revenue_month DATE)")
    for t in ("institutional", "margin", "foreign_holdings"):
        c.execute(f"CREATE TABLE {t} (stock_id VARCHAR, date DATE)")
    yield c
    c.close()


def _prices(con, days, n=30, skip=()):
    for d in days:
        if d in skip:
            continue
        for i in range(n):
            con.execute("INSERT INTO daily_prices VALUES (?, ?, 1.0)", [f"{i:04d}", d])


# 2026-11-26 是週四
THU_AFTER_CLOSE = datetime(2026, 11, 26, 16, 0)
THU_MORNING = datetime(2026, 11, 26, 10, 0)


def test_prices_ok(con):
    _prices(con, _days(date(2026, 11, 26), 40))
    r = hc.check_prices(con, THU_AFTER_CLOSE, _weekday)
    assert r["status"] == "ok" and r["next_step"] is None


def test_prices_missing_one_day_suggests_official_backfill(con):
    days = _days(date(2026, 11, 26), 40)
    _prices(con, days, skip={date(2026, 11, 19)})   # 11/19 那次的洞
    r = hc.check_prices(con, THU_AFTER_CLOSE, _weekday)
    assert r["status"] == "fail"
    assert "2026-11-19" in r["detail"]
    assert r["next_step"] == "python main.py --backfill-official 2026-11-19"


def test_prices_partial_day_is_fail(con):
    days = _days(date(2026, 11, 26), 40)
    _prices(con, days, skip={date(2026, 11, 19)})
    _prices(con, [date(2026, 11, 19)], n=10)       # 只抓到 10/30
    r = hc.check_prices(con, THU_AFTER_CLOSE, _weekday)
    assert r["status"] == "fail" and "只抓到一部分" in r["detail"]
    assert "--backfill-official 2026-11-19" in r["next_step"]


def test_prices_many_missing_suggests_yf_with_warning(con):
    days = _days(date(2026, 11, 26), 40)
    _prices(con, days, skip=set(days[-10:-5]))
    r = hc.check_prices(con, THU_AFTER_CLOSE, _weekday)
    assert r["status"] == "fail" and "--backfill-yf" in r["next_step"] and "Cody" in r["next_step"]
    assert "20 個月" in r["next_step"]


def test_prices_today_not_expected_before_15(con):
    _prices(con, _days(date(2026, 11, 25), 40))     # 只到昨天
    assert hc.check_prices(con, THU_MORNING, _weekday)["status"] == "ok"
    assert hc.check_prices(con, THU_AFTER_CLOSE, _weekday)["status"] == "fail"


def test_prices_intraday_today_rows_not_partial(con):
    # 盤中今天只寫進一部分（即時行情），15 點前不該被算成「只抓到一部分」（2026-11-26 Debugger 🔴）
    _prices(con, _days(date(2026, 11, 25), 40))
    _prices(con, [date(2026, 11, 26)], n=10)
    assert hc.check_prices(con, THU_MORNING, _weekday)["status"] == "ok"


def test_prices_warn_when_calendar_unknown_and_no_rows_today(con):
    # 日曆還沒收今天（None）：stale 不算今天；15 點後平日沒行情要 warn
    _prices(con, _days(date(2026, 11, 25), 40))
    unknown_today = lambda d: None if d == date(2026, 11, 26) else d.weekday() < 5  # noqa: E731
    r = hc.check_prices(con, THU_AFTER_CLOSE, unknown_today)
    assert r["status"] == "warn" and "還沒有行情" in r["detail"]
    assert hc.check_prices(con, THU_MORNING, unknown_today)["status"] == "ok"


def test_chips_lag(con):
    ids = {"TWSE": {"0001", "0002"}, "TPEx": {"0003", "0004"}}
    for t in ("institutional", "margin", "foreign_holdings"):
        for d in _days(date(2026, 11, 25), 10):
            for sid in ("0001", "0002", "0003", "0004"):
                con.execute(f"INSERT INTO {t} VALUES (?, ?)", [sid, d])
    assert hc.check_chips(con, THU_AFTER_CLOSE, ids, _weekday)["status"] == "ok"   # 今天的晚上才有，落後 1 正常
    r = hc.check_chips(con, datetime(2026, 11, 30, 16, 0), ids, _weekday)          # 週一：落後 3 個交易日
    assert r["status"] == "fail" and r["next_step"] == "python main.py --backfill-chips 14"


def test_shareholder_lag(con):
    con.execute("INSERT INTO shareholder VALUES ('0001', '2026-11-20')")
    assert hc.check_shareholder(con, date(2026, 11, 26))["status"] == "ok"
    assert hc.check_shareholder(con, date(2026, 12, 8))["status"] == "warn"


def test_shareholder_empty_is_fail(con):
    assert hc.check_shareholder(con, date(2026, 11, 26))["status"] == "fail"


@pytest.mark.parametrize("today,status", [
    (date(2026, 11, 26), "ok"),    # 10 月的，11 月正常
    (date(2026, 12, 12), "ok"),    # 11 月營收 12/10 前公布，給到 12 號
    (date(2026, 12, 13), "warn"),
    (date(2027, 1, 2), "warn"),    # 落後 3 個月
])
def test_monthly_lag(con, today, status):
    con.execute("INSERT INTO monthly_revenue VALUES ('0001', '2026-10-01')")
    r = hc.check_monthly(con, today, "月營收", "monthly_revenue", "revenue_month", "python main.py --update-fundamentals")
    assert r["status"] == status


def test_exit_code():
    ok, warn, fail = ({"status": s} for s in ("ok", "warn", "fail"))
    assert hc.exit_code([ok, ok]) == 0
    assert hc.exit_code([ok, warn]) == 1
    assert hc.exit_code([warn, fail]) == 2


def test_main_missing_db_points_to_data_dir(tmp_path, capsys):
    assert hc.main(["--data-dir", str(tmp_path)]) == 2
    assert "--data-dir" in capsys.readouterr().out


def test_main_lock_error_returns_3(tmp_path, monkeypatch, capsys):
    (tmp_path / "screener.db").write_bytes(b"")
    def _locked(*a, **k):
        raise duckdb.IOException("IO Error: Could not set lock on file")
    monkeypatch.setattr(hc, "run", _locked)
    assert hc.main(["--data-dir", str(tmp_path)]) == 3
    assert "稍後再跑" in capsys.readouterr().out


def test_main_json_end_to_end(tmp_path, monkeypatch, capsys):
    db = tmp_path / "screener.db"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    c.close()
    fake = [hc._result("行情", "warn", "x", "do y")]
    monkeypatch.setattr(hc, "run", lambda data_dir, now: fake)
    assert hc.main(["--json", "--data-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert '"exit_code": 1' in out and '"next_step": "do y"' in out
