"""_retry_fetch() 的回歸測試（debug-tasks.md #6：TWSE/TPEx 籌碼抓取單邊整批失敗，
加重試機制。實測 2026-07-13 TPEx 三大法人/融資融券 API 當下正常，但當次抓取因暫時性
問題整批漏掉——這兩個 TPEx 端點沒有歷史回補路徑，失敗一次當天資料就永久遺失）。"""
import json
from datetime import date

import pytest

import main
from main import (
    _retry_fetch, _update_chips_db, _update_shareholder_db,
    _update_fundamentals_db, _update_insider_holdings_db,
)


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


def test_update_shareholder_db_skips_when_realtime(monkeypatch):
    """2026-09-07需求：集保回補只在收盤模式跑，盤中每15分鐘一次的節奏跑不起單週
    20-30分鐘的回補——realtime=True時完全不該呼叫_backfill_shareholder()。"""
    calls = []
    monkeypatch.setattr(main, "_backfill_shareholder", lambda **k: calls.append(k))

    _update_shareholder_db(realtime=True)

    assert calls == []


def test_update_shareholder_db_calls_backfill_when_not_realtime(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_backfill_shareholder", lambda **k: calls.append(k))

    _update_shareholder_db(realtime=False)

    assert calls == [{"weeks": 4}]


def test_update_shareholder_db_appends_failure_to_warnings(monkeypatch):
    def _boom(**k):
        raise RuntimeError("集保回補炸了")

    monkeypatch.setattr(main, "_backfill_shareholder", _boom)
    warnings: list = []

    _update_shareholder_db(realtime=False, warnings=warnings)

    assert "集保大戶資料回補失敗" in warnings


def test_update_shareholder_db_warnings_stays_none_safe_when_not_passed(monkeypatch):
    monkeypatch.setattr(main, "_backfill_shareholder", lambda **k: None)

    _update_shareholder_db(realtime=False)  # 不傳warnings，僅確認不raise TypeError


def test_update_fundamentals_db_skips_when_realtime(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_update_fundamentals", lambda: calls.append(1))

    _update_fundamentals_db(realtime=True)

    assert calls == []


def test_update_fundamentals_db_calls_update_when_not_realtime(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_update_fundamentals", lambda: calls.append(1))

    _update_fundamentals_db(realtime=False)

    assert calls == [1]


def test_update_fundamentals_db_appends_failure_to_warnings(monkeypatch):
    def _boom():
        raise RuntimeError("基本面更新炸了")

    monkeypatch.setattr(main, "_update_fundamentals", _boom)
    warnings: list = []

    _update_fundamentals_db(realtime=False, warnings=warnings)

    assert "官方基本面（月營收/季報）更新失敗" in warnings


class _FakeConn:
    """模擬screener.database.get_conn()回傳值，只支援_update_insider_holdings_db()
    用到的單一MAX(report_date)查詢。"""

    def __init__(self, latest_report_date):
        self._latest = latest_report_date

    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return (self._latest,)


def test_update_insider_holdings_db_skips_when_realtime(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=True)

    assert calls == []


def test_update_insider_holdings_db_skips_when_this_month_already_has_data(monkeypatch):
    """董監持股逐股查詢成本高(17分鐘起跳)，本月已經有資料時不該再觸發一次。"""
    today = date.today()
    monkeypatch.setattr(
        "screener.database.get_conn",
        lambda: _FakeConn(date(today.year, today.month, 1)),
    )
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=False)

    assert calls == []


def _first_of_month_shift(base: date, months_back: int) -> date:
    y, m = base.year, base.month - months_back
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def test_update_insider_holdings_db_skips_when_previous_month_already_has_data(monkeypatch):
    """report_date 是資料所屬月份，最新只會到上個月（10 月時是 09-01）。
    舊 gate 拿它跟「這個月」比永遠不成立，每天重抓 38 分鐘把收盤排程拖到逾時（2026-10-21）。"""
    monkeypatch.setattr(
        "screener.database.get_conn",
        lambda: _FakeConn(_first_of_month_shift(date.today(), 1)),
    )
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=False)

    assert calls == []


def test_update_insider_holdings_db_updates_when_two_months_behind(monkeypatch):
    monkeypatch.setattr(
        "screener.database.get_conn",
        lambda: _FakeConn(_first_of_month_shift(date.today(), 2)),
    )
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=False)

    assert calls == [1]


def test_update_insider_holdings_db_updates_when_data_is_stale(monkeypatch):
    monkeypatch.setattr(
        "screener.database.get_conn",
        lambda: _FakeConn(date(2020, 1, 1)),
    )
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=False)

    assert calls == [1]


def test_update_insider_holdings_db_updates_when_no_existing_data(monkeypatch):
    monkeypatch.setattr("screener.database.get_conn", lambda: _FakeConn(None))
    calls = []
    monkeypatch.setattr(main, "_update_insider_holdings", lambda: calls.append(1))

    _update_insider_holdings_db(realtime=False)

    assert calls == [1]


def test_update_insider_holdings_db_appends_failure_to_warnings(monkeypatch):
    monkeypatch.setattr("screener.database.get_conn", lambda: _FakeConn(None))

    def _boom():
        raise RuntimeError("董監持股炸了")

    monkeypatch.setattr(main, "_update_insider_holdings", _boom)
    warnings: list = []

    _update_insider_holdings_db(realtime=False, warnings=warnings)

    assert "董監持股更新失敗" in warnings


def test_quote_trade_date_takes_most_common_quote_date():
    """休市日即時源回的是前一交易日報價：用報價自己標的日期判斷，避免寫成休市日的複本。"""
    import pandas as pd
    from main import _quote_trade_date
    df = pd.DataFrame({"stock_id": ["2330", "2317", "6488"], "quote_date": ["20260924", "20260924", "20260923"]})
    assert _quote_trade_date(df) == date(2026, 9, 24)


def test_quote_trade_date_none_when_no_usable_date():
    """官方收盤 API 沒有 quote_date 欄、或欄位是空字串時回 None，交給既有 2330 探測防呆。"""
    import pandas as pd
    from main import _quote_trade_date
    assert _quote_trade_date(None) is None
    assert _quote_trade_date(pd.DataFrame({"stock_id": ["2330"], "close": [1.0]})) is None
    assert _quote_trade_date(pd.DataFrame({"stock_id": ["2330"], "quote_date": [""]})) is None


def test_run_skips_price_write_when_quote_date_differs():
    """run() 寫行情前要先比對報價日期；端對端成本高，同既有做法用原始碼鎖定這道防呆。"""
    source = inspect.getsource(run)
    assert "_quote_trade_date(prices_df)" in source
    assert "quote_day != trade_date" in source


def test_backtest_recommend_cli_wires_all_strategies():
    """--backtest-recommend 要把載入→特徵→所有策略→交易→報告→案例庫指標串起來（端對端要真 DB，改用原始碼檢查）。"""
    from main import backtest_recommend_cli
    src = inspect.getsource(backtest_recommend_cli)
    for name in ("load_panel", "add_price_features", "add_chip_features", "ALL_STRATEGIES",
                 "run_trades", "report", "winner_episodes", "catch_rate", "blowup_rate", "case_hits"):
        assert name in src


def test_backtest_recommend_cli_has_warmup_and_filters_signals_from_start():
    """hi90 需要 90 天回看：要往前多載預熱期，訊號只取 start 之後（Debugger 2026-10-24 🟡1）。"""
    from main import backtest_recommend_cli
    src = inspect.getsource(backtest_recommend_cli)
    assert "warmup_start" in src and 'sig["date"] >= pd.Timestamp(start)' in src


def test_build_run_summary_includes_recommend_only_in_close_mode():
    started = datetime(2026, 10, 22, 15, 0, 0)
    finished = datetime(2026, 10, 22, 15, 5, 0)
    rec = {"trade_date": "2026-10-22", "new": [], "header": {}, "active": [], "invalid": []}
    common = dict(trade_date=date(2026, 10, 22), market_regime=None, margin_div={}, flow_watch=[],
                  html_updated=True, git_pushed=True, started_at=started, finished_at=finished, warnings=[])
    assert _build_run_summary(realtime=False, recommend=rec, **common)["recommend"]["trade_date"] == "2026-10-22"
    assert "recommend" not in _build_run_summary(realtime=True, recommend=rec, **common)


def test_close_run_does_not_publish_recommend():
    """收盤 15:00 當天籌碼還沒公布 → 推薦改由 publish_recommend 在資料到齊後發布（2026-10-27 Cody：時間一定要對齊）。"""
    source = inspect.getsource(run)
    assert "run_daily(" not in source and "generate_recommend_html(" not in source


def test_repair_ex_rights_cli_skips_when_events_unavailable_and_reimports_after_repair(monkeypatch):
    import main as m
    import scrapers.official_prices as op
    import scrapers.twse_events as te
    import screener.database as db
    calls = []
    monkeypatch.setattr(te, "update_events", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("被擋")))
    monkeypatch.setattr(op, "repair_event_changes", lambda refs: calls.append("repair") or {"files": 1, "rows": 2})
    m.repair_ex_rights_cli()
    assert calls == []                                   # 拿不到參考價就不修
    monkeypatch.setattr(te, "update_events", lambda *a, **k: None)
    monkeypatch.setattr(te, "load_event_refs", lambda: {("2021-10-08", "2364"): 24.01})
    monkeypatch.setattr(m, "init_db", lambda: None)
    monkeypatch.setattr(db, "reimport_db", lambda: calls.append("reimport") or 10)
    monkeypatch.setattr(m, "_repair_price_outliers", lambda: calls.append("outliers"))
    m.repair_ex_rights_cli()
    assert calls == ["repair", "reimport", "outliers"]


def test_backfill_official_cli_passes_event_refs():
    import inspect
    from main import backfill_official_cli
    src = inspect.getsource(backfill_official_cli)
    assert "_refresh_twse_events(start)" in src and "event_refs=load_event_refs()" in src


def _publish_env(monkeypatch, tmp_path, prev, waiting=(), sh_asof="2026-10-16", day="2026-10-23"):
    import recommend.publish as pub
    import main as m
    path = tmp_path / "recommend_payload.json"
    if prev is not None:
        path.write_text(json.dumps(prev, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(m, "RECOMMEND_PAYLOAD_PATH", path)
    calls = []
    monkeypatch.setattr(m, "_update_chips_db", lambda d, ids, warnings=None: calls.append("chips"))
    monkeypatch.setattr(m, "_backfill_shareholder", lambda weeks=4: calls.append("shareholder"))
    monkeypatch.setattr(m, "_refresh_twse_events", lambda start: True)
    monkeypatch.setattr(m, "generate_recommend_html", lambda p: calls.append("html"))
    monkeypatch.setattr(m, "_push_html", lambda d: calls.append(("push", d.isoformat())) or True)
    monkeypatch.setattr(m, "_taiex_vs_ma20", lambda d: {"taiex_above_ma20": False, "taiex_ma20_gap": -0.039})
    monkeypatch.setattr(pub, "latest_price_date", lambda: date.fromisoformat(day))
    monkeypatch.setattr(pub, "missing_inputs", lambda d, f: list(waiting))
    monkeypatch.setattr(pub, "shareholder_asof", lambda d: sh_asof)
    return m, path, calls


def _prev_payload(**kw):
    card = {"stock_id": "6213", "stock_name": "聯茂"}
    return {"trade_date": "2026-10-23", "shareholder_date": "2026-10-16", "inputs_complete": True,
            "new": [{"sector": "銅箔基板", "count": 1, "cards": [card]}], **kw}


def _fake_run_daily(monkeypatch, days, prev_cards, new_ids=("6213", "6672"), withdrawn=()):
    import recommend.daily as rd
    payload = {"trade_date": "2026-10-23", "shareholder_date": "2026-10-16", "header": {}, "active": [], "invalid": [],
               "new": [{"sector": "銅箔基板", "count": len(new_ids), "cards": [{"stock_id": s} for s in new_ids]}],
               "withdrawn": list(withdrawn)}
    monkeypatch.setattr(rd, "run_daily", lambda day=None, prev_new=None: days.append(day) or prev_cards.append(prev_new)
                        or dict(payload))


def test_publish_waits_until_inputs_complete(monkeypatch, tmp_path):
    m, path, calls = _publish_env(monkeypatch, tmp_path, None, waiting=["上市三大法人", "集保"])
    out = m.publish_recommend(summary_path=str(tmp_path / "s.json"))
    assert out["updated"] is False and out["waiting"] == ["上市三大法人", "集保"]
    assert calls == ["chips", "shareholder"] and not path.exists()
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["mode"] == "publish"


def test_publish_first_time_for_new_signal_day(monkeypatch, tmp_path):
    days, prev_cards = [], []
    m, path, calls = _publish_env(monkeypatch, tmp_path, _prev_payload(trade_date="2026-10-22"))   # 前一天的版本
    _fake_run_daily(monkeypatch, days, prev_cards)
    out = m.publish_recommend()
    assert out["updated"] and out["first"] and out["added"] == [] and days == ["2026-10-23"] and prev_cards == [None]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["inputs_complete"] is True and saved["taiex_above_ma20"] is False and saved["taiex_ma20_gap"] == -0.039
    assert calls == ["chips", "shareholder", "html", ("push", "2026-10-23")]


def test_publish_skips_when_already_published_with_complete_inputs(monkeypatch, tmp_path):
    m, path, calls = _publish_env(monkeypatch, tmp_path, _prev_payload())
    assert m.publish_recommend()["updated"] is False and calls == ["chips", "shareholder"]


def test_publish_reruns_old_close_version_and_reports_added_withdrawn(monkeypatch, tmp_path):
    """舊版收盤推薦（沒有 inputs_complete，籌碼晚一天）或集保更新 → 同一訊號日重跑，比對新增／撤回。
    舊版 → first=True（Cody 沒看過完整版，發完整訊息，2026-10-27）；集保更新 → first=False（只發差異）。"""
    days, prev_cards = [], []
    withdrawn = [{"stock_id": "3537", "reason": "法人…"}]
    m, path, calls = _publish_env(monkeypatch, tmp_path, _prev_payload(inputs_complete=None))
    _fake_run_daily(monkeypatch, days, prev_cards, withdrawn=withdrawn)
    out = m.publish_recommend()
    assert out["updated"] and out["first"] and out["added"] == ["6672"] and out["withdrawn"] == withdrawn
    assert prev_cards == [[{"stock_id": "6213", "stock_name": "聯茂"}]]
    m2, _, _ = _publish_env(monkeypatch, tmp_path, _prev_payload(), sh_asof="2026-10-23")      # 集保更新
    _fake_run_daily(monkeypatch, days, prev_cards)
    out2 = m2.publish_recommend()
    assert out2["updated"] and not out2["first"]


def test_fundamentals_fetched_once_per_day(monkeypatch, tmp_path):
    """同一天手動重跑 main.py 不再重抓月營收／季報（2026-10-27 Cody）；失敗不寫戳記，下次會重試。"""
    import main as m
    stamp = tmp_path / "fundamentals_last_update.txt"
    monkeypatch.setattr(m, "FUNDAMENTALS_STAMP_PATH", stamp)
    calls = []
    monkeypatch.setattr(m, "_update_fundamentals", lambda: calls.append(1))
    m._update_fundamentals_db(False)
    m._update_fundamentals_db(False)
    assert calls == [1] and stamp.read_text(encoding="utf-8") == date.today().isoformat()
    stamp.write_text("2000-01-01", encoding="utf-8")       # 昨天以前抓的 → 今天要再抓
    m._update_fundamentals_db(False)
    assert calls == [1, 1]
    m._update_fundamentals_db(True)                        # 盤中不抓
    assert calls == [1, 1]


def test_fundamentals_failure_does_not_write_stamp(monkeypatch, tmp_path):
    import main as m
    stamp = tmp_path / "s.txt"
    monkeypatch.setattr(m, "FUNDAMENTALS_STAMP_PATH", stamp)
    monkeypatch.setattr(m, "_update_fundamentals", lambda: (_ for _ in ()).throw(RuntimeError("API 掛了")))
    warnings = []
    m._update_fundamentals_db(False, warnings=warnings)
    assert not stamp.exists() and warnings == ["官方基本面（月營收/季報）更新失敗"]


def test_rerun_of_past_trading_day_uses_saved_close_csv_for_pages():
    """2026-10-30 00:49：盤前重跑時 mis 逾時只拿到 560／1,035 檔 → 族群績效頁一半「無行情」被推上網站。
    報價日期 ≠ 今天時改讀當天已存的完整收盤檔產頁。"""
    source = inspect.getsource(run)
    guard = source[source.index("_quote_trade_date(prices_df)"):]
    block = guard[:guard.index("if prices_are_new and not realtime")]
    assert 'saved_csv = Path(f"data/daily_prices/{trade_date.isoformat()}.csv")' in block
    assert "prices_df = pd.read_csv(saved_csv" in block
