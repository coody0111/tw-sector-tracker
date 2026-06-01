import pandas as pd
import pytest
from pathlib import Path
from datetime import date
from storage.csv_writer import CsvWriter

@pytest.fixture
def tmp_writer(tmp_path):
    return CsvWriter(base_dir=str(tmp_path))

def test_write_sector_stocks(tmp_writer, tmp_path):
    records = [
        {"sector_type": "industry", "sector_name": "半導體", "sector_code": "C023100",
         "stock_id": "2330", "stock_name": "台積電"},
        {"sector_type": "concept", "sector_name": "AI", "sector_code": "",
         "stock_id": "2330", "stock_name": "台積電"},
    ]
    trade_date = date(2026, 5, 29)
    tmp_writer.write_sector_stocks(records, trade_date)

    industry_path = tmp_path / "sectors" / "industry_sectors.csv"
    concept_path = tmp_path / "sectors" / "concept_sectors.csv"
    assert industry_path.exists()
    assert concept_path.exists()

    df = pd.read_csv(industry_path)
    assert "sector_name" in df.columns
    assert df.iloc[0]["stock_id"] == 2330

def test_write_daily_prices(tmp_writer, tmp_path):
    df = pd.DataFrame({
        "stock_id": ["2330"],
        "stock_name": ["台積電"],
        "close": [905.0],
        "change": [5.0],
        "change_pct": [0.56],
        "volume": [12345],
    })
    trade_date = date(2026, 5, 29)
    tmp_writer.write_daily_prices(df, trade_date)

    path = tmp_path / "daily_prices" / "2026-05-29.csv"
    assert path.exists()
    result = pd.read_csv(path)
    assert len(result) == 1

def test_append_changes_log(tmp_writer, tmp_path):
    changes = [
        {"date": "2026-05-29", "sector_type": "concept", "sector_name": "AI",
         "stock_id": "2330", "stock_name": "台積電", "action": "added"},
    ]
    tmp_writer.append_changes(changes)
    tmp_writer.append_changes(changes)  # append twice

    path = tmp_path / "changes" / "changes_log.csv"
    df = pd.read_csv(path)
    assert len(df) == 2  # both rows present

def test_write_sector_performance(tmp_writer, tmp_path):
    records = [
        {"sector_type": "industry", "sector_name": "半導體",
         "avg_change_pct": 1.5, "up_count": 10, "down_count": 2, "flat_count": 1},
    ]
    trade_date = date(2026, 5, 29)
    tmp_writer.write_sector_performance(records, trade_date)

    path = tmp_path / "sector_performance" / "2026-05-29.csv"
    assert path.exists()
