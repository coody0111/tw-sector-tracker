"""_retry_fetch() 的回歸測試（debug-tasks.md #6：TWSE/TPEx 籌碼抓取單邊整批失敗，
加重試機制。實測 2026-07-13 TPEx 三大法人/融資融券 API 當下正常，但當次抓取因暫時性
問題整批漏掉——這兩個 TPEx 端點沒有歷史回補路徑，失敗一次當天資料就永久遺失）。"""
from datetime import date

import pytest

import main
from main import _retry_fetch, _update_chips_db


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


import inspect
from datetime import date, datetime
from main import _build_run_summary, _push_html, run


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


def test_build_run_summary_intraday_mode_warnings_do_not_auto_include_no_push():
    """finding 3: warnings 只該帶真正的資料異常，不該帶「--no-push」這種正常設計行為
    （intraday 模式本來就永遠是 --no-push）。_build_run_summary() 是純函式、原封不動
    照抄呼叫端傳入的 warnings，不會自己塞任何東西——這裡明確給空 list，確認回傳的
    summary 不會憑空多出 --no-push 相關字樣。"""
    started = datetime(2026, 8, 26, 10, 30, 0)
    finished = datetime(2026, 8, 26, 10, 31, 25)
    summary = _build_run_summary(
        trade_date=date(2026, 8, 26), realtime=True,
        market_regime=None, margin_div={}, flow_watch=[],
        html_updated=False, git_pushed=False,
        started_at=started, finished_at=finished, warnings=[],
    )
    assert summary["warnings"] == []
    assert not any("no-push" in w or "no_push" in w for w in summary["warnings"])


def test_run_no_longer_auto_appends_no_push_warning_for_intraday_mode():
    """finding 3 的實際 bug 出在 run()：push=False（intraday 模式恆真）時，過去會無條件
    把「--no-push：本次未執行git commit/push」塞進 _run_warnings，讓
    compose_intraday_message() 的『資料異常』欄位在每次盤中通知都被誤報成有異常。
    git_pushed 欄位已經足夠表達「這次有沒有推」，不需要在 warnings 重複一份。

    run() 本身牽動大量外部資源（網路抓取、DuckDB、檔案 I/O），端對端呼叫測試成本
    過高、也超出這次修復範圍，這裡改用原始碼檢查直接鎖定這個字面字串不再出現，
    避免之後又被加回去。"""
    source = inspect.getsource(run)
    assert "--no-push：本次未執行git commit/push" not in source


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_push_html_returns_false_when_no_html_changes(monkeypatch):
    """finding 6: docs/*.html 沒有變動（git diff --cached --quiet 回 0）代表這次沒有東西
    需要推，_push_html() 要老實回傳 False，不能讓呼叫端誤以為網站已更新。"""
    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "diff"]:
            return _FakeCompletedProcess(returncode=0)  # 無變動
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("main.subprocess.run", fake_run)
    assert _push_html(date(2026, 8, 26)) is False


def test_push_html_returns_true_when_push_succeeds(monkeypatch):
    """finding 6: 完整 add → commit → pull --rebase → push 全部成功時，_push_html()
    要回傳 True，讓 run() 能把真實結果寫進 summary 的 git_pushed 欄位。"""
    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "diff"]:
            return _FakeCompletedProcess(returncode=1)  # 有變動
        return _FakeCompletedProcess(returncode=0)  # add/commit/pull/push 全部成功

    monkeypatch.setattr("main.subprocess.run", fake_run)
    assert _push_html(date(2026, 8, 26)) is True


def test_push_html_returns_false_when_git_command_raises(monkeypatch):
    """finding 6: git add/commit/push（check=True）任何一步丟例外都被外層 except 吞掉、
    只記 log——修復前這個分支完全不影響回傳值（原本是 None），呼叫端沒辦法分辨這次
    到底有沒有真的推上去。現在必須回傳 False，避免 Telegram 收盤訊息誤報「網站已更新」。"""
    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "diff"]:
            return _FakeCompletedProcess(returncode=1)  # 有變動，進入 commit
        raise RuntimeError("git commit failed")

    monkeypatch.setattr("main.subprocess.run", fake_run)
    assert _push_html(date(2026, 8, 26)) is False


def test_push_html_returns_false_when_pull_rebase_fails(monkeypatch):
    """finding 6: pull --rebase 失敗（非衝突，例如無 upstream/網路問題）這條路徑本來就
    不會 push，_push_html() 要回傳 False。"""
    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "diff"]:
            return _FakeCompletedProcess(returncode=1)  # 有變動
        if cmd[:2] == ["git", "pull"]:
            return _FakeCompletedProcess(returncode=1)  # rebase 失敗
        if cmd[:3] == ["git", "rev-parse", "--git-path"]:
            return _FakeCompletedProcess(returncode=1)  # 沒有 rebase 卡住
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("main.subprocess.run", fake_run)
    assert _push_html(date(2026, 8, 26)) is False


def _stub_all_chips_fetches(monkeypatch, empty_df):
    """把 _update_chips_db() 會呼叫的 backfill_chips()(TWSE三大法人/融資融券/外資持股%
    合併回補，2026-09-02改版)＋3個TPEx抓取函式全部換成假函式——這幾個測試只在意warnings
    有沒有正確附加，不該真的打TWSE/TPEx網路（之前一版忘記mock這些，測試會真的發HTTPS
    請求出去，違反Developer規則的「不要自己執行程式跑資料」，已修正）。"""
    monkeypatch.setattr(
        main, "backfill_chips",
        lambda *a, **k: {"institutional": 0, "margin": 0, "foreign_holdings": 0},
    )
    for name in ("fetch_institutional_tpex", "fetch_margin_all_tpex", "fetch_foreign_holding_tpex"):
        monkeypatch.setattr(main, name, lambda *a, **k: empty_df)


def test_update_chips_db_appends_price_import_failure_to_warnings(monkeypatch):
    """DuckDB 行情匯入失敗時，除了 logger.warning，也要附進 warnings list——
    2026-08-27 全分支 review 抓到的殘留項：舊版這類失敗只寫 log，排程通知的
    「資料異常」看不到，會誤報「資料完整性：正常」。"""
    import pandas as pd

    def _boom(*args, **kwargs):
        raise RuntimeError("匯入炸了")

    monkeypatch.setattr(main, "import_csv_prices", _boom)
    monkeypatch.setattr(main, "import_sector_stocks", lambda: None)
    _stub_all_chips_fetches(monkeypatch, pd.DataFrame())
    warnings: list = []

    _update_chips_db(date(2026, 8, 26), ["2330"], warnings=warnings)

    assert warnings == ["DuckDB 行情匯入失敗"]


def test_update_chips_db_appends_chips_backfill_failure_to_warnings(monkeypatch):
    """籌碼回補（backfill_chips()：TWSE三大法人/融資融券/外資持股%合併）失敗時，
    要附進warnings——這是margin_alerts的上游資料源，資料沒進去時通知不該顯示
    「資料完整性：正常」。2026-09-02改版：原本institutional/margin/foreign_holdings
    (TWSE)是各自獨立的單日抓取+fallback，各自有獨立的warning訊息；現在三個都併進
    backfill_chips()一次呼叫，失敗時是一個統一的警告訊息。"""
    import pandas as pd

    monkeypatch.setattr(main, "import_csv_prices", lambda **kwargs: 0)
    monkeypatch.setattr(main, "import_sector_stocks", lambda: None)

    def _boom(*args, **kwargs):
        raise RuntimeError("回補炸了")

    monkeypatch.setattr(main, "backfill_chips", _boom)
    monkeypatch.setattr(main, "fetch_institutional_tpex", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(main, "fetch_margin_all_tpex", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(main, "fetch_foreign_holding_tpex", lambda *a, **k: pd.DataFrame())
    warnings: list = []

    _update_chips_db(date(2026, 8, 26), ["2330"], warnings=warnings)

    assert "籌碼資料（TWSE 三大法人/融資融券/外資持股%）回補失敗" in warnings


def test_update_chips_db_warnings_stays_none_safe_when_not_passed(monkeypatch):
    """既有呼叫端不傳 warnings 時（None）要維持原行為，不能因為新參數而炸掉。"""
    import pandas as pd

    monkeypatch.setattr(main, "import_csv_prices", lambda **kwargs: 0)
    monkeypatch.setattr(main, "import_sector_stocks", lambda: None)
    _stub_all_chips_fetches(monkeypatch, pd.DataFrame())

    _update_chips_db(date(2026, 8, 26), [])  # 不傳 warnings，僅確認不 raise TypeError
