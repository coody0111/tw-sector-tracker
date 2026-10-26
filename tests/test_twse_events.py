from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from scrapers.twse_events import _half_years, _roc_date, fetch_events, load_event_refs, merge_events, parse_events


def test_roc_date_both_formats():
    assert _roc_date("115年09月02日") == "2026-09-02"      # TWT49U
    assert _roc_date("110/10/08") == "2021-10-08"          # TWTAUU／TWTB8U
    assert _roc_date("合計") is None


def test_parse_events_strips_code_and_takes_ref_column():
    data = {"stat": "OK", "data": [
        ["110/10/08", "2364  ", "倫飛", "3.04", "24.01", "26.40", "21.65", "24.00", "--", "彌補虧損", "2364  ,20210929"],
        ["110/10/18", "6531", "愛普", "750.00", "--", "412.50", "337.50", "375.00", ""],      # 參考價缺 → 跳過
    ]}
    assert parse_events(data, "減資", 5, 7) == [
        {"stock_id": "2364", "date": "2021-10-08", "pre_close": 3.04, "ref": 24.01, "limit_up": 26.4,
         "open_base": 24.0, "base": 24.01, "src": "減資"}]
    assert parse_events({"stat": "查詢無資料"}, "減資", 5, 7) == []


def test_base_uses_open_auction_base_when_official_limit_up_disagrees_with_ref():
    """現金增資除權（如 6225 2026-08-18）：官方漲停價不是參考價 × 1.1 → 改用開盤競價基準（Debugger 2026-10-26）。"""
    normal = ["110年09月01日", "1465", "偉全", "12.95", "12.65", "0.3", "息", "13.90", "11.40", "12.65", "12.65"]
    rights = ["115年08月18日", "6225", "天瀚", "30.00", "18.00", "12.0", "權", "30.75", "25.20", "28.00", "18.00"]
    out = {r["stock_id"]: r for r in parse_events({"stat": "OK", "data": [normal, rights]}, "除權息", 7, 9)}
    assert out["1465"]["base"] == 12.65                     # limit_up_price(12.65)=13.90 跟官方一致
    assert out["6225"]["base"] == 28.0                      # limit_up_price(18)=19.8 ≠ 30.75 → 開盤競價基準


def test_half_years_split():
    assert list(_half_years(date(2020, 1, 1), date(2021, 2, 3))) == [
        (date(2020, 1, 1), date(2020, 6, 30)), (date(2020, 7, 1), date(2020, 12, 31)),
        (date(2021, 1, 1), date(2021, 2, 3))]


def test_merge_dedupes_same_stock_same_day_and_loads_refs(tmp_path):
    path = tmp_path / "events.csv"
    merge_events([{"stock_id": "6669", "date": "2026-09-02", "pre_close": 7800.0, "ref": 2600.0, "base": 2600.0,
                   "src": "除權息"}], path)
    out = merge_events([{"stock_id": "6669", "date": "2026-09-02", "pre_close": 7800.0, "ref": 2605.0, "base": 2605.0,
                         "src": "除權息"},
                        {"stock_id": "2364", "date": "2021-10-08", "pre_close": 3.04, "ref": 24.01, "base": 24.0,
                         "src": "減資"}], path)
    assert len(out) == 2
    refs = load_event_refs(path)
    assert refs == {("2026-09-02", "6669"): 2605.0, ("2021-10-08", "2364"): 24.0}   # 讀的是漲跌基準 base
    assert load_event_refs(tmp_path / "missing.csv") == {}


def test_fetch_events_queries_three_tables_per_half_year():
    resp = MagicMock(status_code=200, headers={"Content-Type": "application/json"})
    resp.json.return_value = {"stat": "OK", "data": [["110/10/08", "2364", "倫飛", "3.04", "24.01"]]}
    with patch("scrapers.official_prices._get_with_retry", return_value=resp) as get, \
         patch("scrapers.twse_events._check_twse_response"), patch("scrapers.twse_events.time.sleep"):
        rows = fetch_events(date(2021, 1, 1), date(2021, 12, 31))
    assert get.call_count == 3 * 2
    assert {r["src"] for r in rows} == {"除權息", "減資", "變更面額"}
    assert pd.DataFrame(rows)["stock_id"].eq("2364").all()
