from datetime import date
from unittest.mock import patch

from scrapers.backfill import (
    _first_month_start,
    _iter_weekdays,
    _looks_like_twse_block,
    backfill_twse_monthly,
)


class _FakeResp:
    def __init__(self, status_code, content_type):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}


def test_first_month_start_crosses_year_boundary():
    assert _first_month_start(date(2026, 1, 15), 6) == date(2025, 8, 1)


def test_iter_weekdays_skips_weekends():
    days = list(_iter_weekdays(date(2026, 1, 2), date(2026, 1, 5)))
    assert days == [date(2026, 1, 2), date(2026, 1, 5)]


def test_looks_like_twse_block_detects_html_redirect():
    assert _looks_like_twse_block(_FakeResp(307, "text/html")) is True


def test_looks_like_twse_block_allows_normal_json():
    assert _looks_like_twse_block(_FakeResp(200, "application/json;charset=utf-8")) is False


def test_backfill_twse_monthly_writes_per_stock_rows(tmp_path):
    """Phase 1 現在實際呼叫的是 _fetch_stock_months（逐股逐月），不是舊版的 _fetch_twse_all_days。"""
    merged = []

    def fake_fetch(sid, month_starts, stop_event=None):
        return sid, [{
            "stock_id": sid, "close": 100.0, "change": 1.0,
            "change_pct": 1.0, "volume": 100, "_date": "2026-01-02",
        }]

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill._fetch_stock_months", side_effect=fake_fetch), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_twse_monthly(
            ["2330", "2317"],
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 1, 2),
            exchange_map={"2330": "TWSE", "2317": "TWSE"},
        )

    assert written == 1
    assert merged[0][0] == "2026-01-02.csv"
    assert sorted(row["stock_id"] for row in merged[0][1]) == ["2317", "2330"]


def test_backfill_twse_monthly_aborts_without_writing_when_blocked(tmp_path):
    """TWSE 封鎖、且沒有 TPEx 股票時，不該寫入任何 CSV，避免覆蓋掉現有歷史資料。"""
    merged = []

    def fake_fetch_blocked(sid, month_starts, stop_event=None):
        if stop_event is not None:
            stop_event.set()
        return sid, []

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill._fetch_stock_months", side_effect=fake_fetch_blocked), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_twse_monthly(
            ["2330"],
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 1, 2),
        )

    assert written == 0
    assert merged == []


def test_backfill_twse_monthly_still_writes_tpex_when_twse_blocked(tmp_path):
    """TWSE 被封鎖不該連累 TPEx——Phase 2 走 FinMind，是不同服務，照常執行並寫入。"""
    merged = []

    def fake_fetch_blocked(sid, month_starts, stop_event=None):
        if stop_event is not None:
            stop_event.set()
        return sid, []

    def fake_finmind(stock_ids, start_date, end_date, day_rows, token, sleep_sec=0.5):
        for sid in stock_ids:
            day_rows["2026-01-02"].append({
                "stock_id": sid, "close": 50.0, "change": 0.5,
                "change_pct": 1.0, "volume": 10,
            })
        return len(stock_ids)

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill._fetch_stock_months", side_effect=fake_fetch_blocked), \
         patch("scrapers.backfill._fetch_finmind_history", side_effect=fake_finmind), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_twse_monthly(
            ["2330", "3213"],
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 1, 2),
            exchange_map={"2330": "TWSE", "3213": "TPEx"},
            finmind_token="fake-token",
        )

    assert written == 1
    assert merged[0][0] == "2026-01-02.csv"
    assert [row["stock_id"] for row in merged[0][1]] == ["3213"]
