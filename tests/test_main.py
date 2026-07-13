"""_retry_fetch() 的回歸測試（debug-tasks.md #6：TWSE/TPEx 籌碼抓取單邊整批失敗，
加重試機制。實測 2026-07-13 TPEx 三大法人/融資融券 API 當下正常，但當次抓取因暫時性
問題整批漏掉——這兩個 TPEx 端點沒有歷史回補路徑，失敗一次當天資料就永久遺失）。"""
import pytest

from main import _missing_shareholder_dates, _retry_fetch


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


# ---------------------------------------------------------------------------
# _missing_shareholder_dates（debug-tasks.md #7：--backfill-shareholder 舊版是無腦
# 「往回數 N 週」重抓，不是「補缺的那幾週」——真實案例 06-18 缺口就是這樣被漏掉的：
# available[:weeks] 視窗剛好沒涵蓋到它，即使 DB 已有更新的週也不會回頭補。）
# ---------------------------------------------------------------------------

def test_missing_shareholder_dates_finds_gap_within_window():
    """真實情境：TDCC 最新 3 筆可查週別是 07-09/07-03/06-26，DB 只有 07-09、06-26
    （06-26 之前先跳過了 07-03，之後才 backfill 補回來），07-03 應被抓出來補。"""
    available = ["20260709", "20260703", "20260626"]
    existing = {"20260709", "20260626"}
    assert _missing_shareholder_dates(available, existing, weeks=3) == ["20260703"]


def test_missing_shareholder_dates_returns_oldest_to_newest():
    """回傳順序必須舊到新——save_to_db 的 streak 計算依賴依序寫入，順序反了會算出
    方向相反的假 week_chg（歷史 bug）。"""
    available = ["20260709", "20260703", "20260626"]
    existing: set = set()
    assert _missing_shareholder_dates(available, existing, weeks=3) == ["20260626", "20260703", "20260709"]


def test_missing_shareholder_dates_empty_when_all_present():
    """DB 已有最近 weeks 筆可查週別的全部資料時，不該重複抓取。"""
    available = ["20260709", "20260703", "20260626"]
    existing = {"20260709", "20260703", "20260626"}
    assert _missing_shareholder_dates(available, existing, weeks=3) == []


def test_missing_shareholder_dates_ignores_gaps_outside_window():
    """weeks 視窗外的缺口不在這次處理範圍（要調大 weeks 才會涵蓋到）——這不是 bug，
    只是視窗大小的取捨，跟「視窗內缺口一定要補到」是兩回事。"""
    available = ["20260709", "20260703", "20260626", "20260618"]
    existing = {"20260709", "20260703", "20260626"}  # 06-18 缺，但 weeks=3 視窗看不到它
    assert _missing_shareholder_dates(available, existing, weeks=3) == []
    assert _missing_shareholder_dates(available, existing, weeks=4) == ["20260618"]
