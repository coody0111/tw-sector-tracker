import os
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_scheduled import is_trading_day, is_market_hours, ExecutionLock, run_main_py


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
