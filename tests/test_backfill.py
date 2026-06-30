from datetime import date
from unittest.mock import patch

import pandas as pd

from scrapers.backfill import _first_month_start, _iter_weekdays, backfill_twse_monthly


def test_first_month_start_crosses_year_boundary():
    assert _first_month_start(date(2026, 1, 15), 6) == date(2025, 8, 1)


def test_iter_weekdays_skips_weekends():
    days = list(_iter_weekdays(date(2026, 1, 2), date(2026, 1, 5)))
    assert days == [date(2026, 1, 2), date(2026, 1, 5)]


def test_backfill_twse_monthly_uses_daily_all_and_filters_universe(tmp_path):
    merged = []

    fake_twse_rows = {"2026-01-02": [
        {"_date": "2026-01-02", "stock_id": "2330", "stock_name": "台積電",
         "close": 905.0, "change": 5.0, "change_pct": 0.56, "volume": 12345},
        {"_date": "2026-01-02", "stock_id": "2317", "stock_name": "鴻海",
         "close": 102.0, "change": -1.0, "change_pct": -0.97, "volume": 8000},
    ]}

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill._fetch_twse_all_days", return_value=fake_twse_rows), \
         patch("scrapers.backfill._fetch_tpex_all_days", return_value={}), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_twse_monthly(
            ["2330", "2317"],
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 1, 2),
        )

    assert written == 1
    assert merged[0][0] == "2026-01-02.csv"
    assert [row["stock_id"] for row in merged[0][1]] == ["2330", "2317"]
