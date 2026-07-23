from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
from scrapers.tpex import fetch_daily_prices

MOCK_TPEX = [
    {"Date": "1150605", "SecuritiesCompanyCode": "6188", "CompanyName": "泰碩",
     "Close": "84.10", "Change": "-2.30", "Open": "85.00", "High": "85.50",
     "Low": "83.80", "TradingShares": "2294000", "TransactionAmount": "193000000",
     "TransactionNumber": "500", "LatestBidPrice": "84.10", "LatesAskPrice": "84.20",
     "Capitals": "100000000", "NextLimitUp": "92.50", "NextLimitDown": "75.70"},
    {"Date": "1150605", "SecuritiesCompanyCode": "3529", "CompanyName": "力旺",
     "Close": "3100.00", "Change": "50.00", "Open": "3050.00", "High": "3120.00",
     "Low": "3040.00", "TradingShares": "500000", "TransactionAmount": "1550000000",
     "TransactionNumber": "1200", "LatestBidPrice": "3100.00", "LatesAskPrice": "3105.00",
     "Capitals": "200000000", "NextLimitUp": "3410.00", "NextLimitDown": "2790.00"},
]

def test_fetch_tpex_returns_dataframe():
    with patch("scrapers.tpex.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_TPEX
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 6, 5))

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["stock_id", "stock_name", "close", "change", "change_pct", "volume", "open", "high", "low"]
    assert len(df) == 2

def test_fetch_tpex_parses_values():
    with patch("scrapers.tpex.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_TPEX
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 6, 5))

    row = df[df["stock_id"] == "6188"].iloc[0]
    assert row["close"] == 84.10
    assert row["change"] == -2.30
    assert row["change_pct"] < 0
    assert row["volume"] == 2294  # 2294000 // 1000 = 2294 張
    assert row["open"] == 85.00
    assert row["high"] == 85.50
    assert row["low"] == 83.80

def test_fetch_tpex_returns_all_rows():
    with patch("scrapers.tpex.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_TPEX
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 6, 5))

    assert len(df) == 2
