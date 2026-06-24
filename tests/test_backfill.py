from datetime import date
from unittest.mock import patch

import pandas as pd

from scrapers.backfill import _first_month_start, _iter_weekdays, backfill_twse_monthly


def test_first_month_start_crosses_year_boundary():
    assert _first_month_start(date(2026, 1, 15), 6) == date(2025, 8, 1)


def test_iter_weekdays_skips_weekends():
    days = list(_iter_weekdays(date(2026, 1, 2), date(2026, 1, 5)))
    assert days == [date(2026, 1, 2), date(2026, 1, 5)]


def test_backfill_twse_monthly_uses_daily_all_and_filters_universe():
    merged = []

    def fake_fetch(trade_date):
        if trade_date == date(2026, 1, 1):
            raise ValueError("holiday")
        return pd.DataFrame({
            "stock_id": ["2330", "2317", "9999"],
            "stock_name": ["台積電", "鴻海", "測試"],
            "close": [905.0, 102.0, 1.0],
            "change": [5.0, -1.0, 0.0],
            "change_pct": [0.56, -0.97, 0.0],
            "volume": [12345, 8000, 1],
        })

    def fake_merge(path, rows):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill.fetch_twse_daily_prices", side_effect=fake_fetch), \
            patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_twse_monthly(
            ["2330", "2317"],
            months=1,
            output_dir="unused",
            sleep_sec=0,
            today=date(2026, 1, 2),
        )

    assert written == 1
    assert merged[0][0] == "2026-01-02.csv"
    assert [row["stock_id"] for row in merged[0][1]] == ["2330", "2317"]
