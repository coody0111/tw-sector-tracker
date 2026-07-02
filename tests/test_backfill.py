from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from scrapers.backfill import (
    _fetch_yfinance_one_stock,
    _first_month_start,
    _iter_weekdays,
    _looks_like_twse_block,
    backfill_twse_monthly,
    backfill_yfinance,
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


def _make_yf_history(dates: list, closes: list, volumes: list = None):
    """建立一個假的 yf.Ticker().history() 回傳值（DatetimeIndex + Close/Volume 欄位）。
    真正的 yfinance 回傳值 index.name 是 'Date'，reset_index() 後才會變成 'Date' 欄位，
    這裡要跟真實行為一致，不然 reset_index() 會變成 'index' 欄位，測試就測不出真實情境。"""
    volumes = volumes or [1000] * len(dates)
    idx = pd.to_datetime(dates)
    idx.name = "Date"
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_fetch_yfinance_one_stock_skips_buffer_day_fake_zero(monkeypatch):
    """緩衝天數（start_date 之前）不該出現在輸出裡，且第一個真正的交易日
    要用緩衝天數的收盤價算出真實漲跌，不是假的 0。"""
    hist = _make_yf_history(
        ["2026-06-27", "2026-06-29", "2026-06-30"],  # 6/27 是緩衝天（start=6/29 之前）
        [100.0, 105.0, 110.0],
    )
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=fake_ticker), \
         patch("scrapers.backfill.time.sleep"):
        sid, rows = _fetch_yfinance_one_stock("2330", "2330.TW", "2026-06-29", "2026-07-01")

    assert [r["_date"] for r in rows] == ["2026-06-29", "2026-06-30"]
    first = rows[0]
    assert first["close"] == 105.0
    assert first["change"] == 5.0
    assert first["change_pct"] == 5.0  # (105-100)/100*100，不是假的 0


def test_fetch_yfinance_one_stock_pauses_every_n_completions():
    """pause_state 計數滿 pause_every 時，剛好完成那支的 worker 要自己暫停。"""
    hist = _make_yf_history(["2026-06-29", "2026-06-30"], [100.0, 101.0])
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = hist

    pause_state = {"lock": __import__("threading").Lock(), "count": 1}  # 這支會是第 2 支
    slept = []

    with patch("yfinance.Ticker", return_value=fake_ticker), \
         patch("scrapers.backfill.time.sleep", side_effect=lambda s: slept.append(s)):
        _fetch_yfinance_one_stock(
            "2330", "2330.TW", "2026-06-29", "2026-07-01",
            pause_state=pause_state, pause_every=2,
        )

    assert pause_state["count"] == 2
    # 除了一開始的隨機延遲，還要有一次落在 5~10 秒區間的暫停
    assert any(5 <= s <= 10 for s in slept)


def test_backfill_yfinance_writes_per_stock_rows(tmp_path):
    merged = []

    def fake_fetch(sid, ticker, start_date, end_date, pause_state=None):
        return sid, [{
            "stock_id": sid, "close": 100.0, "change": 1.0,
            "change_pct": 1.0, "volume": 100, "_date": "2026-06-29",
        }]

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    with patch("scrapers.backfill._fetch_yfinance_one_stock", side_effect=fake_fetch), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        written = backfill_yfinance(
            ["2330", "3213"],
            exchange_map={"2330": "TWSE", "3213": "TPEx"},
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 6, 29),
        )

    assert written == 1
    assert merged[0][0] == "2026-06-29.csv"
    assert sorted(row["stock_id"] for row in merged[0][1]) == ["2330", "3213"]


def test_backfill_yfinance_skips_clean_when_success_rate_low(tmp_path):
    """大部分股票失敗（疑似被限流）時，不該清空舊 CSV，避免覆蓋掉現有歷史資料。"""
    (tmp_path / "2025-01-01.csv").write_text("stock_id,close\n9999,1.0\n", encoding="utf-8")
    merged = []

    def fake_fetch_mostly_fail(sid, ticker, start_date, end_date, pause_state=None):
        if sid == "2330":
            return sid, [{
                "stock_id": sid, "close": 100.0, "change": 1.0,
                "change_pct": 1.0, "volume": 100, "_date": "2026-06-29",
            }]
        return sid, []  # 其餘都失敗，模擬被限流

    def fake_merge(path, rows, overwrite=False):
        merged.append((path.name, rows))
        return True

    stock_ids = ["2330", "2317", "2454", "3213"]  # 只有 1/4 成功，成功率 25% < 50%

    with patch("scrapers.backfill._fetch_yfinance_one_stock", side_effect=fake_fetch_mostly_fail), \
         patch("scrapers.backfill._merge_into_csv", side_effect=fake_merge):
        backfill_yfinance(
            stock_ids,
            exchange_map={"2330": "TWSE"},
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 6, 29),
        )

    # 舊的錨點檔案應該還在，沒有被清空邏輯刪掉
    assert (tmp_path / "2025-01-01.csv").exists()


def test_backfill_yfinance_ticker_suffix_mapping(tmp_path):
    """TWSE 對應 .TW，其餘（包含未知代號）對應 .TWO，跟 backfill_twse_monthly 的
    分類慣例（明確 TWSE 才算 TWSE，其餘一律當非 TWSE）一致。"""
    seen_tickers = {}

    def fake_fetch(sid, ticker, start_date, end_date, pause_state=None):
        seen_tickers[sid] = ticker
        return sid, []

    with patch("scrapers.backfill._fetch_yfinance_one_stock", side_effect=fake_fetch), \
         patch("scrapers.backfill._merge_into_csv", return_value=False):
        backfill_yfinance(
            ["2330", "3213", "9999"],
            exchange_map={"2330": "TWSE", "3213": "TPEx"},  # 9999 沒在 map 裡
            months=1,
            output_dir=str(tmp_path),
            today=date(2026, 6, 29),
        )

    assert seen_tickers["2330"] == "2330.TW"
    assert seen_tickers["3213"] == "3213.TWO"
    assert seen_tickers["9999"] == "9999.TWO"
