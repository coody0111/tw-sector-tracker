"""_retry_fetch() 的回歸測試（debug-tasks.md #6：TWSE/TPEx 籌碼抓取單邊整批失敗，
加重試機制。實測 2026-07-13 TPEx 三大法人/融資融券 API 當下正常，但當次抓取因暫時性
問題整批漏掉——這兩個 TPEx 端點沒有歷史回補路徑，失敗一次當天資料就永久遺失）。"""
import pytest

from main import _retry_fetch


class _CustomError(Exception):
    pass


def test_retry_fetch_returns_immediately_on_success():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = _retry_fetch(fn, backoff=(0, 0))
    assert result == "ok"
    assert len(calls) == 1


def test_retry_fetch_retries_transient_failure_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"

    result = _retry_fetch(fn, retries=3, backoff=(0, 0), retry_on=(ConnectionError,))
    assert result == "ok"
    assert len(calls) == 3


def test_retry_fetch_raises_last_exception_after_exhausting_retries():
    calls = []

    def fn():
        calls.append(1)
        raise ConnectionError(f"fail {len(calls)}")

    with pytest.raises(ConnectionError, match="fail 3"):
        _retry_fetch(fn, retries=3, backoff=(0, 0), retry_on=(ConnectionError,))
    assert len(calls) == 3


def test_retry_fetch_does_not_retry_excluded_exception_types():
    """retry_on 沒涵蓋到的例外型別（例如 TWSE『尚未發布』的 ValueError）要立即往外拋，
    不能被重試機制吃掉、延誤既有的日期回退邏輯。"""
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("not published yet")

    with pytest.raises(ValueError, match="not published yet"):
        _retry_fetch(fn, retries=3, backoff=(0, 0), retry_on=(_CustomError,))
    assert len(calls) == 1, "排除在 retry_on 之外的例外型別不該被重試"


def test_retry_fetch_passes_args_and_kwargs_through():
    def fn(a, b, c=None):
        return (a, b, c)

    result = _retry_fetch(fn, 1, 2, backoff=(0, 0), c=3)
    assert result == (1, 2, 3)

# 缺週回補的「只補缺的那幾週」邏輯已改用 scrapers/shareholder.py::plan_backfill_dates
# （見 tests/test_shareholder.py），main.py 本地曾經獨立實作過一份同用途的
# _missing_shareholder_dates，merge 時確認功能重複、已移除，測試隨之移除。


from datetime import date, datetime
from main import _build_run_summary


def test_build_run_summary_close_mode_includes_flow_watch():
    started = datetime(2026, 8, 26, 15, 0, 0)
    finished = datetime(2026, 8, 26, 15, 1, 32)
    summary = _build_run_summary(
        trade_date=date(2026, 8, 26),
        realtime=False,
        market_regime={"tier": "小漲"},
        margin_div={"bearish": [{"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10}]},
        flow_watch=[{"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000}],
        html_updated=True, git_pushed=True,
        started_at=started, finished_at=finished, warnings=[],
    )
    assert summary["status"] == "success"
    assert summary["mode"] == "close"
    assert summary["trade_date"] == "2026-08-26"
    assert summary["market_regime"] == "小漲"
    assert summary["market_regime_label"] == "小漲"
    assert summary["margin_alerts"] == [{"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10}]
    assert summary["flow_watch"] == [{"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000}]
    assert summary["html_updated"] is True
    assert summary["git_pushed"] is True
    assert summary["duration_seconds"] == 92


def test_build_run_summary_intraday_mode_excludes_flow_watch():
    """盤中模式不帶flow_watch欄位——避免run_scheduled.py誤把觀察用內容當盤中通知素材。"""
    started = datetime(2026, 8, 26, 10, 30, 0)
    finished = datetime(2026, 8, 26, 10, 31, 25)
    summary = _build_run_summary(
        trade_date=date(2026, 8, 26), realtime=True,
        market_regime=None, margin_div={}, flow_watch=[],
        html_updated=False, git_pushed=False,
        started_at=started, finished_at=finished, warnings=["TPEx逾時"],
    )
    assert summary["mode"] == "intraday"
    assert "flow_watch" not in summary
    assert summary["margin_alerts"] == []
    assert summary["market_regime"] is None
    assert summary["warnings"] == ["TPEx逾時"]
