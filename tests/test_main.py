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
