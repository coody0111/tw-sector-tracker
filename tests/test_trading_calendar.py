from datetime import date
from unittest.mock import patch

import pytest

import scrapers.trading_calendar as tc
from scrapers.trading_calendar import calendar_status, merge_trading_days, month_status, update_calendar


@pytest.fixture
def cal_path(tmp_path, monkeypatch):
    path = tmp_path / "trading_calendar.csv"
    monkeypatch.setattr(tc, "CALENDAR_PATH", path)
    tc._load.cache_clear()
    yield path
    tc._load.cache_clear()


def test_month_status_past_month_confirms_every_day():
    """整月已過：每一天都確認，FMTQIK 沒列的平日（例 2026-09-25 中秋）是休市。"""
    trading = [date(2026, 9, d) for d in range(1, 31) if date(2026, 9, d).weekday() < 5 and d not in (25, 28)]
    st = month_status(date(2026, 9, 1), trading, as_of=date(2026, 10, 24))
    assert len(st) == 30
    assert st[date(2026, 9, 24)] is True
    assert st[date(2026, 9, 25)] is False
    assert st[date(2026, 9, 27)] is False  # 週日


def test_month_status_current_month_only_up_to_last_published_day():
    """當月：只確認到已公布的最後一個交易日，之後（含今天）不知道就不寫。"""
    trading = [date(2026, 10, 21), date(2026, 10, 22)]
    st = month_status(date(2026, 10, 1), trading, as_of=date(2026, 10, 24))
    assert max(st) == date(2026, 10, 22)
    assert date(2026, 10, 23) not in st


def test_calendar_status_none_when_not_covered(cal_path):
    merge_trading_days([date(2026, 10, 22)], as_of=date(2026, 10, 24), path=cal_path)
    assert calendar_status(date(2026, 10, 22)) is True
    assert calendar_status(date(2026, 10, 20)) is False  # 當月清單沒有、又在最後公布日之前
    assert calendar_status(date(2026, 10, 23)) is None   # 還沒公布 → 交給假日清單


def test_is_trading_day_prefers_calendar_over_weekday_rule(cal_path):
    """2025-01-23（週四）不是交易日：舊假日清單沒有它，行事曆有就要以行事曆為準。"""
    from config import is_trading_day
    jan = [date(2025, 1, d) for d in range(1, 32) if date(2025, 1, d).weekday() < 5 and d not in (1, 23, 24, 27, 28, 29, 30, 31)]
    merge_trading_days(jan, as_of=date(2026, 10, 24), path=cal_path)
    assert is_trading_day("2025-01-23") is False
    assert is_trading_day("2025-01-22") is True
    assert is_trading_day("2030-01-02") is True  # 沒涵蓋 → 退回週末＋假日清單


def test_update_calendar_skips_confirmed_months_and_stops_when_blocked(cal_path):
    from scrapers.chips import TWSEBlockedError
    merge_trading_days([date(2026, 8, 3)], as_of=date(2026, 10, 24), path=cal_path)  # 8 月已整月確認
    calls = []

    def fake_month(m):
        calls.append(m)
        if m.month == 10:
            raise TWSEBlockedError("擋")
        return [{"date": date(m.year, m.month, 1)}]

    with patch("scrapers.taiex._fetch_taiex_month", side_effect=fake_month):
        n = update_calendar(date(2026, 8, 1), today=date(2026, 10, 24), sleep_sec=0)
    assert calls == [date(2026, 9, 1), date(2026, 10, 1)]
    assert n == 1
    assert calendar_status(date(2026, 9, 1)) is True
