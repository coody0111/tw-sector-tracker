from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from scrapers.chips import TWSEBlockedError
from scrapers.official_prices import (
    backfill_official_prices,
    finalize_rows,
    parse_tpex_daily_quotes,
    parse_twse_mi_index,
)

D = date(2026, 10, 22)
_TWSE_FIELDS = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價",
                "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"]


def _twse(rows, d="20261022"):
    return {"stat": "OK", "date": d, "tables": [
        {"title": "大盤統計資訊", "fields": ["指數", "收盤指數"], "data": [["發行量加權股價指數", "27,000"]]},
        {"title": "每日收盤行情", "fields": _TWSE_FIELDS, "data": rows},
    ]}


def _tw_row(sid, close, sign, diff, vol="12,990,000"):
    return [sid, "名稱", vol, "1", "1", "2,400.00", "2,420.00", "2,380.00", close, sign, diff, "", "", "", "", ""]


def test_parse_twse_mi_index_signs_and_skips_no_trade():
    rows = parse_twse_mi_index(_twse([
        _tw_row("2330", "2,385.00", "<p style= color:green>-</p>", "25.00"),
        _tw_row("2317", "200.50", "<p style= color:red>+</p>", "1.50"),
        _tw_row("1101", "--", "<p> </p>", "0.00"),           # 無成交 → 不寫
        _tw_row("2412", "120.00", "<p>X</p>", "0.00"),        # 除權息 → 交給前一日收盤反推
    ]), D)
    by = {r["stock_id"]: r for r in rows}
    assert set(by) == {"2330", "2317", "2412"}
    assert by["2330"]["close"] == 2385.0 and by["2330"]["change"] == -25.0
    assert by["2330"]["volume"] == 12990  # 股 → 張
    assert by["2317"]["change"] == 1.5
    assert by["2412"]["change"] is None


def test_parse_twse_mi_index_holiday_and_layout_change():
    assert parse_twse_mi_index(_twse([], d="20261021"), D) is None  # 回應不是這天 → 休市
    with pytest.raises(ValueError):
        parse_twse_mi_index({"stat": "OK", "date": "20261022", "tables": [{"fields": ["代號"], "data": []}]}, D)


def test_parse_tpex_daily_quotes():
    data = {"stat": "ok", "date": "20261022", "tables": [{
        "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數"],
        "data": [["6488", "環球晶", "450.00", "-5.00", "455.00", "458.00", "449.00", "452", "1,234,000"],
                 ["8299", "群聯", "---", "0.00", "", "", "", "", "0"]],
    }]}
    rows = parse_tpex_daily_quotes(data, D)
    assert [r["stock_id"] for r in rows] == ["6488"]
    assert rows[0]["change"] == -5.0 and rows[0]["volume"] == 1234
    assert parse_tpex_daily_quotes({**data, "date": "20261021"}, D) is None


def test_finalize_rows_fills_ex_rights_change_from_prev_close_and_filters_universe():
    rows = [
        {"stock_id": "2412", "stock_name": "", "open": 1, "high": 1, "low": 1, "close": 120.0, "change": None, "volume": 1},
        {"stock_id": "2330", "stock_name": "", "open": 1, "high": 1, "low": 1, "close": 110.0, "change": 10.0, "volume": 1},
        {"stock_id": "9999", "stock_name": "", "open": 1, "high": 1, "low": 1, "close": 5.0, "change": 0.0, "volume": 1},
    ]
    out = finalize_rows(rows, {"2412": 125.0}, {"2412", "2330"})
    by = {r["stock_id"]: r for r in out}
    assert set(by) == {"2412", "2330"}
    assert by["2412"]["change"] == -5.0 and by["2412"]["change_pct"] == -4.0
    assert by["2330"]["change_pct"] == 10.0  # 官方漲跌以參考價為基準：10 / (110-10)
    assert all(r["source"] == "official" for r in out)
    assert rows[0]["change"] is None  # 不改傳入的 rows


def _r(sid, close):
    return {"stock_id": sid, "stock_name": "", "open": close, "high": close, "low": close,
            "close": close, "change": 0.0, "volume": 1000}


def test_backfill_official_prices_writes_deletes_holiday_resumes_and_stops(tmp_path):
    out = tmp_path / "daily_prices"
    out.mkdir()
    # 10-19 已是官方 → 跳過；10-21 有 Yahoo 佔位列、官方說休市 → 刪；10-22 只有上市 → 不寫；10-23 被擋 → 停
    pd.DataFrame([{**_r("2330", 2400), "change_pct": 0, "source": "official"}]).to_csv(out / "2026-10-19.csv", index=False)
    pd.DataFrame([_r("2330", 2400)]).to_csv(out / "2026-10-21.csv", index=False)

    def twse(d):
        if d == date(2026, 10, 23):
            raise TWSEBlockedError("擋")
        return None if d == date(2026, 10, 21) else [_r("2330", 2410)]

    def tpex(d):
        return None if d in (date(2026, 10, 21), date(2026, 10, 22)) else [_r("6488", 450)]

    with patch("scrapers.official_prices.fetch_twse_day", side_effect=twse), \
         patch("scrapers.official_prices.fetch_tpex_day", side_effect=tpex), \
         patch("config.is_trading_day", side_effect=lambda d: d != "2026-10-21"), \
         patch("scrapers.official_prices.time.sleep"):
        stats = backfill_official_prices(["2330", "6488"], date(2026, 10, 19), date(2026, 10, 24),
                                         output_dir=str(out), sleep_sec=0)

    assert stats == {"written": 1, "skipped": 1, "holidays": 1, "partial": 1, "stopped": "2026-10-23"}
    assert not (out / "2026-10-21.csv").exists()
    assert not (out / "2026-10-22.csv").exists()
    written = pd.read_csv(out / "2026-10-20.csv", dtype={"stock_id": str})
    assert sorted(written["stock_id"]) == ["2330", "6488"]
    assert (written["source"] == "official").all()
    assert not (tmp_path / "daily_prices_backup").exists()  # 已有官方 CSV＝續跑，不再備份


def test_backfill_official_first_run_backs_up_existing_csvs(tmp_path):
    """第一次跑（目錄裡還沒有官方 CSV）：開始覆寫前先把現有 CSV 整份複製一份。"""
    out = tmp_path / "daily_prices"
    out.mkdir()
    pd.DataFrame([_r("2330", 2400)]).to_csv(out / "2026-10-20.csv", index=False)
    with patch("scrapers.official_prices.fetch_twse_day", return_value=[_r("2330", 2410)]), \
         patch("scrapers.official_prices.fetch_tpex_day", return_value=[_r("6488", 450)]), \
         patch("scrapers.official_prices.time.sleep"):
        backfill_official_prices(["2330", "6488"], date(2026, 10, 20), date(2026, 10, 20),
                                 output_dir=str(out), sleep_sec=0)
    backups = list((tmp_path / "daily_prices_backup").iterdir())
    assert len(backups) == 1
    old = pd.read_csv(backups[0] / "2026-10-20.csv", dtype={"stock_id": str})
    assert "source" not in old.columns  # 備份的是覆寫前的原檔


def test_backfill_official_keeps_csv_when_empty_but_calendar_says_trading_day(tmp_path):
    """官方兩邊都回空、但行事曆說是交易日（還沒公布／偶發空回應）：不能刪掉有效的 CSV。"""
    out = tmp_path / "daily_prices"
    out.mkdir()
    pd.DataFrame([_r("2330", 2400)]).to_csv(out / "2026-10-22.csv", index=False)
    with patch("scrapers.official_prices.fetch_twse_day", return_value=None), \
         patch("scrapers.official_prices.fetch_tpex_day", return_value=None), \
         patch("config.is_trading_day", return_value=True), \
         patch("scrapers.official_prices.time.sleep"):
        stats = backfill_official_prices(["2330"], date(2026, 10, 22), date(2026, 10, 22),
                                         output_dir=str(out), sleep_sec=0)
    assert (out / "2026-10-22.csv").exists()
    assert stats["holidays"] == 0 and stats["partial"] == 1


def test_tpex_ex_dividend_uses_previous_next_ref_price():
    """上櫃除息日官方漲跌欄是「除息」：用前一天的「次日參考價」算，不是前一天收盤。"""
    data = {"stat": "ok", "date": "20261022", "tables": [{
        "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "成交股數", "次日 參考價"],
        "data": [["6488", "環球晶", "98.00", "除息 ", "97", "99", "96", "1,000", "98.00"]],
    }]}
    rows = parse_tpex_daily_quotes(data, D)
    assert rows[0]["change"] is None and rows[0]["next_ref"] == 98.0
    out = finalize_rows(rows, {"6488": 96.0}, {"6488"})  # 前一天的次日參考價 96（前收是 100）
    assert out[0]["change"] == 2.0
    assert out[0]["change_pct"] == round(2 / 96 * 100, 2)


def test_get_with_retry_retries_network_errors_then_raises():
    import requests
    from scrapers import official_prices as op
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise requests.exceptions.ChunkedEncodingError("IncompleteRead")
        return "ok"

    with patch("scrapers.official_prices.requests.get", side_effect=flaky), \
         patch("scrapers.official_prices.time.sleep"):
        assert op._get_with_retry("u", {}, {}) == "ok"
    assert len(calls) == 3

    with patch("scrapers.official_prices.requests.get",
               side_effect=requests.exceptions.ConnectionError("down")), \
         patch("scrapers.official_prices.time.sleep"), pytest.raises(requests.RequestException):
        op._get_with_retry("u", {}, {})


def test_backfill_official_stops_instead_of_crashing_on_network_error(tmp_path):
    import requests
    out = tmp_path / "daily_prices"
    out.mkdir()
    with patch("scrapers.official_prices.fetch_twse_day",
               side_effect=requests.exceptions.ChunkedEncodingError("IncompleteRead")), \
         patch("scrapers.official_prices.fetch_tpex_day", return_value=None), \
         patch("scrapers.official_prices.time.sleep"):
        stats = backfill_official_prices(["2330"], date(2026, 10, 20), date(2026, 10, 22),
                                         output_dir=str(out), sleep_sec=0)
    assert stats["stopped"] == "2026-10-20"
