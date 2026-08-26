import json
import os
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_scheduled import (
    is_trading_day, is_market_hours, ExecutionLock, run_main_py,
    load_summary, compute_signal_hash, load_notification_state, save_notification_state,
    should_notify_intraday, compose_intraday_message, compose_close_message, compose_failure_message,
)


def test_is_trading_day_true_for_weekday():
    assert is_trading_day(date(2026, 8, 26)) is True  # 週三


def test_is_trading_day_false_for_weekend():
    assert is_trading_day(date(2026, 8, 29)) is False  # 週六
    assert is_trading_day(date(2026, 8, 30)) is False  # 週日


def test_is_market_hours_true_within_window():
    assert is_market_hours(datetime(2026, 8, 26, 10, 30)) is True
    assert is_market_hours(datetime(2026, 8, 26, 9, 0)) is True
    assert is_market_hours(datetime(2026, 8, 26, 13, 30)) is True


def test_is_market_hours_false_outside_window():
    assert is_market_hours(datetime(2026, 8, 26, 8, 59)) is False
    assert is_market_hours(datetime(2026, 8, 26, 13, 31)) is False
    assert is_market_hours(datetime(2026, 8, 29, 10, 30)) is False  # 週六


def test_execution_lock_acquire_and_release(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is True
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_execution_lock_refuses_when_held_by_live_process(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock_path.write_text(str(os.getpid()))  # 用自己的PID模擬「還活著的持鎖程序」
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is False


def test_execution_lock_auto_releases_stale_lock_from_dead_process(tmp_path):
    lock_path = tmp_path / "scheduler.lock"
    lock_path.write_text("999999999")  # 一個幾乎不可能存在的PID
    lock = ExecutionLock(str(lock_path))
    assert lock.acquire() is True


def test_execution_lock_refuses_when_held_by_live_process_with_permission_error(tmp_path, monkeypatch):
    """PermissionError from os.kill means process exists but we can't signal it — should NOT steal lock."""
    lock_path = tmp_path / "scheduler.lock"
    held_pid = 12345  # arbitrary PID for the lock
    lock_path.write_text(str(held_pid))

    def fake_kill(pid, sig):
        if pid == held_pid:
            raise PermissionError("Operation not permitted")
        raise ProcessLookupError("No such process")

    monkeypatch.setattr("os.kill", fake_kill)
    lock = ExecutionLock(str(lock_path))
    # Should refuse to acquire because PermissionError means process IS alive
    assert lock.acquire() is False


def test_run_main_py_intraday_mode_includes_realtime_and_no_push_flags(monkeypatch, tmp_path):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    summary_path = str(tmp_path / "summary.json")
    result = run_main_py("intraday", summary_path)

    assert "--realtime" in captured["cmd"]
    assert "--no-push" in captured["cmd"]
    assert "--summary-json" in captured["cmd"]
    assert summary_path in captured["cmd"]
    assert result["returncode"] == 0


def test_run_main_py_close_mode_excludes_realtime_and_no_push_flags(monkeypatch, tmp_path):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **k):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    run_main_py("close", str(tmp_path / "summary.json"))

    assert "--realtime" not in captured["cmd"]
    assert "--no-push" not in captured["cmd"]


def test_load_summary_reads_json_file(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"status": "success", "mode": "close"}), encoding="utf-8")
    assert load_summary(str(p)) == {"status": "success", "mode": "close"}


def test_load_summary_returns_none_when_file_missing(tmp_path):
    assert load_summary(str(tmp_path / "missing.json")) is None


def test_compute_signal_hash_stable_for_same_content():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    assert compute_signal_hash(summary) == compute_signal_hash(dict(summary))


def test_compute_signal_hash_changes_when_alerts_change():
    a = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    b = {"margin_alerts": [{"stock_id": "2330"}, {"stock_id": "2317"}], "market_regime": "小漲"}
    assert compute_signal_hash(a) != compute_signal_hash(b)


def test_load_notification_state_returns_empty_dict_when_missing_or_corrupted(tmp_path):
    assert load_notification_state(str(tmp_path / "missing.json")) == {}
    corrupted = tmp_path / "bad.json"
    corrupted.write_text("{not valid json", encoding="utf-8")
    assert load_notification_state(str(corrupted)) == {}


def test_save_and_reload_notification_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_notification_state(str(p), {"last_signal_hash": "abc123"})
    assert load_notification_state(str(p)) == {"last_signal_hash": "abc123"}


def test_should_notify_intraday_true_when_hash_changed():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    prev_state = {"last_signal_hash": "different-hash"}
    assert should_notify_intraday(summary, prev_state) is True


def test_should_notify_intraday_false_when_hash_unchanged():
    summary = {"margin_alerts": [{"stock_id": "2330"}], "market_regime": "小漲"}
    prev_state = {"last_signal_hash": compute_signal_hash(summary)}
    assert should_notify_intraday(summary, prev_state) is False


def test_compose_intraday_message_lists_margin_alerts_only():
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [
            {"stock_id": "2330", "stock_name": "台積電", "margin_pct": 5.2, "price_pct": -3.1, "days": 10},
        ],
        "warnings": [],
    }
    msg = compose_intraday_message(summary)
    assert "融資警示" in msg
    assert "2330 台積電" in msg
    assert "+5.2%" in msg
    assert "-3.1%" in msg
    assert "背離" in msg
    assert "進貨分" not in msg and "score" not in msg  # 盤中不該出現任何評分內容


def test_compose_close_message_includes_flow_watch_with_disclosure():
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [],
        "flow_watch": [
            {"stock_id": "2317", "stock_name": "鴻海", "net_buy_lots": 3200, "vs_avg20_ratio": 3.2, "turnover": 890000000},
        ],
        "html_updated": True, "git_pushed": True,
    }
    msg = compose_close_message(summary, site_url="https://example.com/chips.html")
    assert "今日籌碼動向" in msg
    assert "純觀察" in msg or "非推薦" in msg  # 誠實揭露文字必須存在
    assert "2317 鴻海" in msg
    assert "3,200張" in msg or "3200張" in msg
    assert "3.2倍" in msg
    assert "https://example.com/chips.html" in msg


def test_compose_failure_message_includes_error_and_duration():
    msg = compose_failure_message("close", "TPEx API timeout", 130)
    assert "台股排程執行失敗" in msg
    assert "TPEx API timeout" in msg
    assert "2 分 10 秒" in msg or "130" in msg
