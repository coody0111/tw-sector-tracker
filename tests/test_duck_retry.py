"""排程寫入 DuckDB 被查股的唯讀連線鎖住時要重試（storage/duck.py，2026-11-02 Cody）。"""
import inspect

import duckdb
import pytest

from storage import duck


def _flaky(fails: int, msg: str = "IO Error: Could not set lock on file"):
    calls = []

    def connect(path):
        calls.append(path)
        if len(calls) <= fails:
            raise duckdb.IOException(msg)
        return "con"
    return connect, calls


def test_retries_lock_then_connects(monkeypatch):
    connect, calls = _flaky(3)
    monkeypatch.setattr(duck.duckdb, "connect", connect)
    slept = []
    assert duck.connect_rw("x.db", sleep=slept.append) == "con"
    assert len(calls) == 4 and slept == [duck.WAIT_SECONDS] * 3


def test_gives_up_after_attempts(monkeypatch):
    connect, calls = _flaky(99)
    monkeypatch.setattr(duck.duckdb, "connect", connect)
    with pytest.raises(duckdb.IOException):
        duck.connect_rw("x.db", attempts=4, sleep=lambda s: None)
    assert len(calls) == 4


def test_other_io_errors_are_not_retried(monkeypatch):
    connect, calls = _flaky(99, "IO Error: Cannot open file: no such directory")
    monkeypatch.setattr(duck.duckdb, "connect", connect)
    with pytest.raises(duckdb.IOException):
        duck.connect_rw("x.db", sleep=lambda s: None)
    assert len(calls) == 1


def test_real_connection(tmp_path):
    con = duck.connect_rw(str(tmp_path / "a.db"))
    assert con.execute("SELECT 1").fetchone()[0] == 1
    con.close()


def test_scheduled_writers_use_retry():
    import main
    import recommend.daily
    import scrapers.backfill
    import scrapers.fundamentals
    import scrapers.insider_holdings
    import scrapers.mops_monthly_revenue
    import scrapers.mops_xbrl
    import scrapers.shareholder
    import screener.database
    import screener.patterns
    for m in (main, recommend.daily, scrapers.backfill, scrapers.fundamentals, scrapers.insider_holdings,
              scrapers.mops_monthly_revenue, scrapers.mops_xbrl, scrapers.shareholder, screener.database, screener.patterns):
        src = inspect.getsource(m)
        bare = [l for l in src.splitlines() if "duckdb.connect(" in l and "read_only" not in l and not l.strip().startswith(("#", '"'))]
        assert not bare, (m.__name__, bare)
