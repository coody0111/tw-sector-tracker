"""TPEx 官網報表（可查歷史日期）三支籌碼解析函式的測試；回應格式取自 2025-09-24 實際資料。"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from scrapers.chips import (
    TPExBlockedError,
    fetch_foreign_holding_tpex_hist,
    fetch_institutional_tpex_hist,
    fetch_margin_tpex_hist,
)

D = date(2025, 9, 24)

# 穩懋 3105：外資(不含自營商) 4、外資自營商 7、投信 13、自營商自行 16、自營商合計 22、三大合計 23
INST_ROW = ["3105", "穩懋", "1,987,050", "913,300", "1,073,750", "0", "0", "0",
            "1,987,050", "913,300", "1,073,750", "2,000", "0", "2,000",
            "30,034", "253,500", "-223,466", "11,709", "57,471", "-45,762",
            "41,743", "310,971", "-269,228", "806,522"]
MARGIN_ROW = ["3105", "穩懋", "7,698", "133", "401", "0", "7,430", "206", "7.01", "105,985",
              "466", "0", "16", "0", "450", "1", "0.42", "105,985", "1", ""]
QFII_ROW = ["1", "8455", "大拓-KY", "25,219,056", "3,071,750", "22,147,306", "12.18%", "87.81%", "100%", ""]


def _resp(rows, date_str="20250924", stat="ok", content_type="application/json"):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": content_type}
    resp.json.return_value = {"stat": stat, "date": date_str, "tables": [{"data": rows}]}
    return resp


def test_institutional_maps_same_definitions_as_daily_openapi():
    """dealer_net 要取自營商「合計」（自行＋避險），跟每日流程 OpenAPI Dealers-Difference 同口徑。"""
    with patch("scrapers.chips.requests.get", return_value=_resp([INST_ROW])):
        df = fetch_institutional_tpex_hist(D)
    row = df.iloc[0].to_dict()
    assert row == {
        "stock_id": "3105", "date": "2025-09-24", "foreign_net": 1073750,
        "trust_net": 2000, "dealer_net": -269228, "total_net": 806522,
    }


def test_institutional_raises_when_layout_self_check_fails():
    """欄位位置一變（合計對不上），要報錯而不是靜默寫入錯欄。"""
    broken = INST_ROW.copy()
    broken[23] = "1"
    with patch("scrapers.chips.requests.get", return_value=_resp([broken])):
        with pytest.raises(ValueError, match="欄位格式"):
            fetch_institutional_tpex_hist(D)


def test_non_trading_day_returns_empty_when_response_date_differs():
    """查假日時官網可能回最近交易日的資料；日期對不上要當作沒資料，避免寫成錯的日期。"""
    with patch("scrapers.chips.requests.get", return_value=_resp([INST_ROW], date_str="20250923")):
        assert fetch_institutional_tpex_hist(D).empty
    with patch("scrapers.chips.requests.get", return_value=_resp([MARGIN_ROW], date_str="20250923")):
        assert fetch_margin_tpex_hist(D).empty
    with patch("scrapers.chips.requests.get", return_value=_resp([QFII_ROW], date_str="20250923")):
        assert fetch_foreign_holding_tpex_hist(D).empty


def test_html_response_raises_blocked_error():
    with patch("scrapers.chips.requests.get", return_value=_resp([], content_type="text/html")):
        with pytest.raises(TPExBlockedError):
            fetch_margin_tpex_hist(D)


def test_margin_maps_balances_and_changes():
    with patch("scrapers.chips.requests.get", return_value=_resp([MARGIN_ROW])):
        df = fetch_margin_tpex_hist(D)
    assert df.iloc[0].to_dict() == {
        "stock_id": "3105", "date": "2025-09-24", "margin_balance": 7430,
        "margin_change": -268, "short_balance": 450, "short_change": -16,
    }


def test_margin_skips_row_when_balance_unparseable():
    bad = MARGIN_ROW.copy()
    bad[6] = "--"
    with patch("scrapers.chips.requests.get", return_value=_resp([bad, MARGIN_ROW])):
        df = fetch_margin_tpex_hist(D)
    assert len(df) == 1


def test_foreign_holding_takes_stock_id_and_pct_columns():
    with patch("scrapers.chips.requests.get", return_value=_resp([QFII_ROW])):
        df = fetch_foreign_holding_tpex_hist(D)
    assert df.iloc[0].to_dict() == {"stock_id": "8455", "date": "2025-09-24", "foreign_pct": 87.81}
