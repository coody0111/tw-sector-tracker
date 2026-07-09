import json
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from scrapers.taiex import (
    fetch_taiex_index,
    _parse_taiex_response,
    _roc_to_date,
    _to_float,
)
from scrapers.chips import TWSEBlockedError

# 真實 FMTQIK 回應格式（2026-07 實測，見 scrapers/taiex.py docstring）
MOCK_RESPONSE = {
    "stat": "OK",
    "date": "20260701",
    "title": "115年07月 大盤統計資訊",
    "fields": ["日期", "成交股數", "成交金額", "成交筆數",
               "發行量加權股價指數", "漲跌點數"],
    "data": [
        ["115/07/01", "14,683,404,939", "1,367,817,795,171", "6,457,744", "47,018.99", "893.08"],
        ["115/07/02", "11,740,053,658", "1,083,583,417,368", "5,564,334", "46,744.16", "-274.83"],
    ],
    "notes": [],
}


# ── 純解析函式 ────────────────────────────────────────────

def test_parse_taiex_response_extracts_close_and_change():
    rows = _parse_taiex_response(MOCK_RESPONSE, content_type="application/json")
    assert len(rows) == 2
    first = rows[0]
    assert first["date"] == date(2026, 7, 1)
    assert first["close"] == 47018.99
    assert first["change"] == 893.08
    # prev_close = 47018.99 - 893.08 = 46125.91 → +1.94%
    assert abs(first["change_pct"] - round(893.08 / 46125.91 * 100, 2)) < 0.01


def test_parse_taiex_response_handles_negative_change():
    rows = _parse_taiex_response(MOCK_RESPONSE, content_type="application/json")
    second = rows[1]
    assert second["change"] == -274.83
    assert second["change_pct"] < 0
    # 07/02 的 prev_close 應等於 07/01 的收盤（連續性檢查）
    assert abs((second["close"] - second["change"]) - 47018.99) < 0.01


def test_parse_taiex_response_accepts_json_string():
    rows = _parse_taiex_response(json.dumps(MOCK_RESPONSE), content_type="application/json")
    assert rows[0]["close"] == 47018.99


def test_parse_taiex_response_raises_on_block_page():
    with pytest.raises(TWSEBlockedError):
        _parse_taiex_response("<html>因為安全性考量，您所執行的頁面無法呈現。</html>",
                              content_type="text/html")


def test_parse_taiex_response_raises_on_bad_stat():
    with pytest.raises(TWSEBlockedError):
        _parse_taiex_response({"stat": "很抱歉，沒有符合條件的資料!"},
                              content_type="application/json")


def test_parse_taiex_response_raises_on_missing_fields():
    """欄位名稱變更/缺漏（例如擋頁塞了別的 JSON）也要當擋頁，不要 silently 回空。"""
    with pytest.raises(TWSEBlockedError):
        _parse_taiex_response({"stat": "OK", "fields": ["foo", "bar"], "data": [["1", "2"]]},
                              content_type="application/json")


# ── 輔助函式 ─────────────────────────────────────────────

def test_roc_to_date():
    assert _roc_to_date("115/07/01") == date(2026, 7, 1)
    assert _roc_to_date("bad") is None


def test_to_float_strips_commas_and_handles_blanks():
    assert _to_float("47,018.99") == 47018.99
    assert _to_float("-274.83") == -274.83
    assert _to_float("--") is None
    assert _to_float("") is None


# ── fetch_taiex_index（含日期挑選 + fallback）───────────────

def _mock_get(mock_get, response=MOCK_RESPONSE, ctype="application/json"):
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(response)
    mock_resp.headers = {"Content-Type": ctype}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp


def test_fetch_taiex_index_picks_exact_date():
    with patch("scrapers.taiex.requests.get") as mock_get:
        _mock_get(mock_get)
        result = fetch_taiex_index(date(2026, 7, 2))
    assert result["date"] == date(2026, 7, 2)
    assert result["close"] == 46744.16


def test_fetch_taiex_index_falls_back_to_latest_available():
    """要 07/03 但當月只發布到 07/02 → 退到 07/02，不報錯。"""
    with patch("scrapers.taiex.requests.get") as mock_get:
        _mock_get(mock_get)
        result = fetch_taiex_index(date(2026, 7, 3))
    assert result["date"] == date(2026, 7, 2)


def test_fetch_taiex_index_raises_when_no_data_on_or_before():
    """要的日期比當月最早一筆還早 → 無可用資料，拋 ValueError。"""
    with patch("scrapers.taiex.requests.get") as mock_get:
        _mock_get(mock_get)
        with pytest.raises(ValueError):
            fetch_taiex_index(date(2026, 6, 30))


def test_fetch_taiex_index_raises_twse_blocked_on_html():
    with patch("scrapers.taiex.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = "<html>因為安全性考量...</html>"
        mock_resp.headers = {"Content-Type": "text/html; charset=UTF-8"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        with pytest.raises(TWSEBlockedError):
            fetch_taiex_index(date(2026, 7, 2))
