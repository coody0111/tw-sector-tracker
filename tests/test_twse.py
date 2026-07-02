from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
import pytest
from scrapers.twse import fetch_daily_prices
from scrapers.chips import TWSEBlockedError

MOCK_RESPONSE = {
    "stat": "OK",
    "date": "20260529",
    "fields": ["證券代號","證券名稱","成交股數","成交筆數","成交金額",
               "開盤價","最高價","最低價","收盤價","漲跌(+/-)","漲跌價差",
               "最後揭示買價","最後揭示買量","最後揭示賣價","最後揭示賣量","本益比"],
    "data": [
        ["2330","台積電","12,345,000","5,000","11,111,111,000",
         "900.00","910.00","898.00","905.00","+","5.00",
         "904.00","100","906.00","200","30.00"],
        ["2317","鴻海","8,000,000","3,000","816,000,000",
         "102.00","103.00","101.00","102.00","-","1.00",
         "102.00","50","103.00","80","15.00"],
    ]
}

def test_fetch_daily_prices_returns_dataframe():
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 5, 29))

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["stock_id", "stock_name", "close", "change", "change_pct", "volume"]
    assert len(df) == 2

def test_fetch_daily_prices_parses_values():
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 5, 29))

    tsmc = df[df["stock_id"] == "2330"].iloc[0]
    assert tsmc["close"] == 905.00
    assert tsmc["change"] == 5.00
    assert abs(tsmc["change_pct"] - round(5.00 / 900.00 * 100, 2)) < 0.01
    assert tsmc["volume"] == 12345  # 12,345,000 股 / 1000 = 12,345 張

def test_fetch_daily_prices_handles_negative_change():
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 5, 29))

    hon_hai = df[df["stock_id"] == "2317"].iloc[0]
    assert hon_hai["change"] == -1.00
    assert hon_hai["change_pct"] < 0

def test_fetch_daily_prices_raises_on_bad_stat():
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"stat": "FAIL"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        try:
            fetch_daily_prices(date(2026, 5, 29))
            assert False, "should have raised"
        except ValueError as e:
            assert "FAIL" in str(e)

def test_fetch_daily_prices_raises_twse_blocked_on_html_response():
    """TWSE 擋頁：非 JSON + content-type 是 html，應該拋 TWSEBlockedError，
    而不是被誤當成合法 CSV 硬解析（重現 2026-07-02 的 UnboundLocalError 前置 bug：
    Error tokenizing data. C error: Expected 1 fields in line 7, saw 2）。
    """
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Type": "text/html; charset=UTF-8"}
        mock_resp.content = b"<html><body>403 Forbidden</body></html>"
        mock_get.return_value = mock_resp

        with pytest.raises(TWSEBlockedError):
            fetch_daily_prices(date(2026, 7, 2))

def test_fetch_daily_prices_raises_twse_blocked_on_unparseable_non_html():
    """content-type 沒標 html，但內容根本不是合法 CSV（欄位數量不一致），
    也要視為擋頁，不能讓 pandas ParserError 原封不動地往外噴。
    """
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Type": "text/plain; charset=UTF-8"}
        mock_resp.content = "a\nb\nc\nd\ne\nf\ng,h\n".encode("utf-8-sig")
        mock_get.return_value = mock_resp

        with pytest.raises(TWSEBlockedError):
            fetch_daily_prices(date(2026, 7, 2))

def test_fetch_daily_prices_parses_legit_csv_response():
    """非 JSON 但確實是合法 CSV（瀏覽器 UA 觸發）時，仍要能正常解析，不誤判成擋頁。"""
    csv_text = (
        "證券代號,證券名稱,成交股數,成交筆數,成交金額,開盤價,最高價,最低價,"
        "收盤價,漲跌價差,成交筆數2\n"
        "2330,台積電,\"12,345,000\",5000,\"11,111,111,000\",900.00,910.00,898.00,905.00,5.00,5000\n"
    )
    with patch("scrapers.twse.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Type": "text/csv; charset=UTF-8"}
        mock_resp.content = csv_text.encode("utf-8-sig")
        mock_get.return_value = mock_resp

        df = fetch_daily_prices(date(2026, 7, 2))

    assert len(df) == 1
    assert df.iloc[0]["stock_id"] == "2330"
