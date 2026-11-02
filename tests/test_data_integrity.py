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
    missing_days,
    window_is_reliable,
)


def NO_CAL(d):
    """日曆沒涵蓋：測舊的「跨度＋連假緩衝」退回規則。"""
    return None


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
    assert window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 8, 21), 5, NO_CAL)


def test_window_is_reliable_tolerates_a_long_weekend():
    """含連假的 5 個交易日仍要放行，不能因為國定假日就把正常資料判成有洞。"""
    assert window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 8, 16), 5, NO_CAL)


def test_window_is_reliable_rejects_the_jinju_case():
    """本回歸的主角：跨 29 個日曆天卻標成「近5日」，必須擋下。"""
    assert not window_is_reliable(dt.date(2026, 8, 28), dt.date(2026, 7, 30), 5, NO_CAL)


def test_window_is_reliable_rejects_missing_dates():
    """資料不足（取不到窗口起點）一律視為不可信，不能當成 0% 或直接算。"""
    assert not window_is_reliable(dt.date(2026, 8, 28), None, 5, NO_CAL)
    assert not window_is_reliable(None, dt.date(2026, 8, 21), 5, NO_CAL)


def test_window_is_reliable_rejects_reversed_dates():
    """起點比終點還晚（資料排序異常）不該被當成合理窗口。"""
    assert not window_is_reliable(dt.date(2026, 8, 21), dt.date(2026, 8, 28), 5, NO_CAL)


def test_find_gaps_ignores_weekends():
    """週五→週一隔 3 天是正常的，不能報成斷層。"""
    dates = [
        dt.date(2026, 8, 21),  # 五
        dt.date(2026, 8, 24),  # 一
        dt.date(2026, 8, 25),
        dt.date(2026, 8, 26),
    ]
    assert find_gaps(dates, NO_CAL) == []


def test_find_gaps_reports_real_hole():
    """真的缺一段（8/06→8/25）要被抓出來，並回報斷層的前後兩端。"""
    dates = [dt.date(2026, 8, 4), dt.date(2026, 8, 6), dt.date(2026, 8, 25)]
    assert find_gaps(dates, NO_CAL) == [(dt.date(2026, 8, 6), dt.date(2026, 8, 25))]


def test_find_gaps_handles_unsorted_and_short_input():
    assert find_gaps([], NO_CAL) == []
    assert find_gaps([dt.date(2026, 8, 28)], NO_CAL) == []
    # 未排序輸入也要得到相同結果
    unsorted_dates = [dt.date(2026, 8, 25), dt.date(2026, 8, 4), dt.date(2026, 8, 6)]
    assert find_gaps(unsorted_dates, NO_CAL) == [(dt.date(2026, 8, 6), dt.date(2026, 8, 25))]


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
        result = check_price_continuity(con, lookback_days=90, is_trading=NO_CAL)
    finally:
        con.close()
    assert result["ok"] is False
    assert result["gaps"]
    assert "缺" in result["message"]


def test_check_price_continuity_passes_on_clean_data():
    """連續資料（只夾週末）不該被誤報成有洞。"""
    today = dt.date.today()
    dates = [today - dt.timedelta(days=n) for n in range(0, 10)]
    con = _con_with_dates(dates)
    try:
        result = check_price_continuity(con, lookback_days=90, is_trading=NO_CAL)
    finally:
        con.close()
    assert result["ok"] is True
    assert result["gaps"] == []
    assert result["latest"] == max(dates)


def test_check_price_continuity_handles_empty_table():
    """空表要回 ok=False 而不是假裝正常（reimport 炸掉後就是這個狀態）。"""
    con = _con_with_dates([])
    try:
        result = check_price_continuity(con, lookback_days=90, is_trading=NO_CAL)
    finally:
        con.close()
    assert result["ok"] is False
    assert result["latest"] is None


# ── 有官方交易日曆時（2026-11-03 code review：只缺 1 天也要抓到）──────────────

def _cal(holidays=()):
    """假日曆：週一到週五是交易日，holidays 另外休市。"""
    return lambda d: d.weekday() < 5 and d not in set(holidays)


def test_calendar_find_gaps_catches_single_missing_day():
    dates = [dt.date(2026, 10, 19), dt.date(2026, 10, 20), dt.date(2026, 10, 22)]   # 缺 10/21（三）
    gaps = find_gaps(dates, _cal())
    assert gaps == [(dt.date(2026, 10, 20), dt.date(2026, 10, 22))]
    assert missing_days(gaps, _cal()) == [dt.date(2026, 10, 21)]


def test_calendar_find_gaps_skips_real_holidays():
    hol = [dt.date(2026, 10, 23), dt.date(2026, 10, 26)]
    assert find_gaps([dt.date(2026, 10, 22), dt.date(2026, 10, 27)], _cal(hol)) == []


def test_calendar_window_counts_exact_trading_days():
    cal = _cal()
    assert window_is_reliable(dt.date(2026, 10, 30), dt.date(2026, 10, 23), 5, cal)        # 剛好 5 個交易日
    assert not window_is_reliable(dt.date(2026, 10, 30), dt.date(2026, 10, 21), 5, cal)    # 7 個：中間缺了 2 天


def test_calendar_unknown_days_fall_back_to_span_rule():
    half = lambda d: None if d >= dt.date(2026, 11, 1) else d.weekday() < 5
    assert window_is_reliable(dt.date(2026, 11, 6), dt.date(2026, 10, 30), 5, half)       # 退回跨度規則


def _con_with_counts(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE)")
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, 1.0)",
                    [(str(i), d) for d, n in rows for i in range(n)])
    return con


def test_check_reports_missing_stale_and_partial():
    days = [dt.date(2026, 10, d) for d in (19, 20, 22, 23, 26, 27)]       # 缺 10/21；10/27 只有 3 筆
    con = _con_with_counts([(d, 10) for d in days[:-1]] + [(days[-1], 3)])
    try:
        r = check_price_continuity(con, is_trading=_cal(), today=dt.date(2026, 10, 29))
    finally:
        con.close()
    assert r["ok"] is False and r["missing"] == [dt.date(2026, 10, 21)]
    assert r["stale"] == [dt.date(2026, 10, 28), dt.date(2026, 10, 29)]
    assert r["partial"] == [(dt.date(2026, 10, 27), 3)]
    assert "2026-10-21" in r["message"] and "只抓到一部分" in r["message"] and "--reimport" not in r["message"]


def test_check_clean_with_calendar():
    days = [dt.date(2026, 10, d) for d in (26, 27, 28, 29, 30)]
    con = _con_with_counts([(d, 10) for d in days])
    try:
        r = check_price_continuity(con, is_trading=_cal(), today=dt.date(2026, 11, 1))   # 11/1 週日
    finally:
        con.close()
    assert r["ok"] is True and r["stale"] == [] and r["partial"] == []


def test_main_warning_lists_days():
    import main
    msg = main._price_health_warning({"latest": dt.date(2026, 10, 27), "gaps": [1], "missing": [dt.date(2026, 10, 21)],
                                      "stale": [dt.date(2026, 10, 28)], "partial": [(dt.date(2026, 10, 27), 3)]})
    assert "缺 10/21" in msg and "落後 1 個交易日" in msg and "只抓到一部分：10/27" in msg


# ── 籌碼到齊與落後（code review #3 #5）──────────────────────────────

def _chips_con(rows):
    """rows：[(date, n)]，institutional 表在那天塞 n 檔（股號 0..n-1，皆屬同一市場）。"""
    con = duckdb.connect()
    con.execute("CREATE TABLE institutional (stock_id VARCHAR, date DATE)")
    con.executemany("INSERT INTO institutional VALUES (?, ?)", [(str(i), d) for d, n in rows for i in range(n)])
    return con


def test_market_day_complete_rejects_partial_day():
    from screener.data_integrity import market_day_complete
    ids = {str(i) for i in range(100)}
    days = [dt.date(2026, 10, d) for d in (19, 20, 21, 22, 27)]
    con = _chips_con([(d, 100) for d in days[:-1]] + [(days[-1], 34)])
    try:
        assert market_day_complete(con, "institutional", days[-2], ids)
        assert not market_day_complete(con, "institutional", days[-1], ids)       # 34 筆 < 100 × 80%
        assert not market_day_complete(con, "institutional", dt.date(2026, 10, 28), ids)
    finally:
        con.close()


def test_chips_freshness_warns_only_when_lag_over_one_day():
    from screener.data_integrity import chips_freshness
    ids = {"TPEx": {str(i) for i in range(50)}}
    con = _chips_con([(dt.date(2026, 10, d), 50) for d in (26, 27, 28)])
    try:
        cal = lambda d: d.weekday() < 5
        ok = chips_freshness(con, dt.date(2026, 10, 29), ids, cal, tables=(("institutional", "三大法人"),))
        late = chips_freshness(con, dt.date(2026, 10, 30), ids, cal, tables=(("institutional", "三大法人"),))
    finally:
        con.close()
    assert ok == [] and late == ["上櫃三大法人只到 10/28（落後 2 個交易日）"]


def test_main_runs_chips_freshness():
    import inspect
    import main
    assert "chips_freshness(_con, date.today(), _ids)" in inspect.getsource(main.run)
