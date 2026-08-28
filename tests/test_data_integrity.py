# tests/test_data_integrity.py
"""近N日窗口的資料完整性守門測試。

回歸來源（2026-08-28）：金居 8358 的「5日漲幅」顯示 +100.37%，實際是
2026-07-30→08-28 將近一個月的漲幅——daily_prices 缺了 8/07~8/24 共 15 個交易日，
而 `ORDER BY date DESC LIMIT N` 數的是「實際存在的資料列」不是交易日。
當時全市場 1040 檔有 1035 檔（99.5%）的 5 日窗口被拉長，中位數跨 29 個日曆天。
"""
import datetime as dt

import duckdb
import pytest

from screener.data_integrity import (
    check_price_continuity,
    find_gaps,
    max_span_days,
    window_is_reliable,
)


def test_max_span_days_accounts_for_weekends_and_holidays():
    """N 個交易日的合理跨度要含週末：每滿 5 個交易日夾一個週末（+2 天）。"""
    assert max_span_days(5) == 5 + 2 + 9      # 一個週末 + 連假緩衝
    assert max_span_days(10) == 10 + 4 + 9    # 兩個週末
    # 單調遞增：窗口愈長，容許跨度愈大
    spans = [max_span_days(n) for n in (5, 7, 10, 14, 20, 60)]
    assert spans == sorted(spans)


def test_max_span_days_rejects_non_positive():
    with pytest.raises(ValueError):
        max_span_days(0)


def test_window_is_reliable_accepts_normal_week():
    """正常的 5 個交易日：週五→隔週五，跨 7 個日曆天。"""
    assert window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 8, 21), 5)


def test_window_is_reliable_tolerates_a_long_weekend():
    """含連假的 5 個交易日仍要放行，不能因為國定假日就把正常資料判成有洞。"""
    assert window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 8, 16), 5)


def test_window_is_reliable_rejects_the_jinju_case():
    """本回歸的主角：跨 29 個日曆天卻標成「近5日」，必須擋下。"""
    assert not window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 7, 30), 5)


def test_window_is_reliable_rejects_missing_dates():
    """資料不足（取不到窗口起點）一律視為不可信，不能當成 0% 或直接算。"""
    assert not window_is_reliable(dt.date(2026, 8, 28), None, 5)
    assert not window_is_reliable(None, dt.date(2026, 8, 21), 5)


def test_window_is_reliable_rejects_reversed_dates():
    """起點比終點還晚（資料排序異常）不該被當成合理窗口。"""
    assert not window_is_reliable(dt.date(2026, 8, 21), dt.date(2026, 8, 28), 5)


def test_find_gaps_ignores_weekends():
    """週五→週一隔 3 天是正常的，不能報成斷層。"""
    dates = [
        dt.date(2026, 8, 21),  # 五
        dt.date(2026, 8, 24),  # 一
        dt.date(2026, 8, 25),
        dt.date(2026, 8, 26),
    ]
    assert find_gaps(dates) == []


def test_find_gaps_reports_real_hole():
    """真的缺一段（8/06→8/25）要被抓出來，並回報斷層的前後兩端。"""
    dates = [dt.date(2026, 8, 4), dt.date(2026, 8, 6), dt.date(2026, 8, 25)]
    assert find_gaps(dates) == [(dt.date(2026, 8, 6), dt.date(2026, 8, 25))]


def test_find_gaps_handles_unsorted_and_short_input():
    assert find_gaps([]) == []
    assert find_gaps([dt.date(2026, 8, 28)]) == []
    # 未排序輸入也要得到相同結果
    unsorted_dates = [dt.date(2026, 8, 25), dt.date(2026, 8, 4), dt.date(2026, 8, 6)]
    assert find_gaps(unsorted_dates) == [(dt.date(2026, 8, 6), dt.date(2026, 8, 25))]


def _con_with_dates(dates):
    con = duckdb.connect()
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    if dates:
        con.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?)",
            [("2330", d, 900.0) for d in dates],
        )
    return con


def test_check_price_continuity_flags_gap():
    """有斷層時要回 ok=False，並在訊息裡指出缺在哪，方便直接照著補。"""
    today = dt.date.today()
    dates = [today - dt.timedelta(days=n) for n in (0, 1, 40, 41)]
    con = _con_with_dates(dates)
    try:
        result = check_price_continuity(con, lookback_days=90)
    finally:
        con.close()
    assert result["ok"] is False
    assert result["gaps"]
    assert "缺漏" in result["message"]


def test_check_price_continuity_passes_on_clean_data():
    """連續資料（只夾週末）不該被誤報成有洞。"""
    today = dt.date.today()
    dates = [today - dt.timedelta(days=n) for n in range(0, 10)]
    con = _con_with_dates(dates)
    try:
        result = check_price_continuity(con, lookback_days=90)
    finally:
        con.close()
    assert result["ok"] is True
    assert result["gaps"] == []
    assert result["latest"] == max(dates)


def test_check_price_continuity_handles_empty_table():
    """空表要回 ok=False 而不是假裝正常（reimport 炸掉後就是這個狀態）。"""
    con = _con_with_dates([])
    try:
        result = check_price_continuity(con, lookback_days=90)
    finally:
        con.close()
    assert result["ok"] is False
    assert result["latest"] is None
