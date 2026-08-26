import json
import os
import subprocess
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_PROJECT_ROOT))
import scripts.run_scheduled as sr
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

    def fake_run(cmd, capture_output, text, timeout, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    summary_path = str(tmp_path / "summary.json")
    result = run_main_py("intraday", summary_path)

    assert "--realtime" in captured["cmd"]
    assert "--no-push" in captured["cmd"]
    assert "--summary-json" in captured["cmd"]
    assert summary_path in captured["cmd"]
    assert captured["cwd"] is not None  # main.py 用相對路徑，必須固定 cwd=專案根目錄
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


def test_compose_close_message_tolerates_flow_watch_entry_missing_fields():
    """summary 形狀跟預期不符（欄位改名/缺漏）時，訊息組裝不該用 [] 直接炸 KeyError——
    應該用 .get() 帶合理預設值，讓通知仍能送出（內容降級但不中斷）。"""
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [],
        "flow_watch": [
            {"stock_id": "2317"},  # 缺 stock_name/net_buy_lots/vs_avg20_ratio/turnover
        ],
        "html_updated": True, "git_pushed": True,
    }
    msg = compose_close_message(summary, site_url="https://example.com/chips.html")
    assert "2317" in msg
    assert "0張" in msg  # net_buy_lots 缺漏時的合理預設值
    assert "近期均量資料不足" in msg
    assert "成交值資料不足" in msg


def test_compose_intraday_message_tolerates_margin_alert_missing_fields():
    summary = {
        "market_regime_label": "小漲",
        "margin_alerts": [{"stock_id": "2330"}],  # 缺 stock_name/margin_pct/price_pct
        "warnings": [],
    }
    msg = compose_intraday_message(summary)
    assert "2330" in msg
    assert "背離" in msg


def test_compose_failure_message_includes_error_and_duration():
    msg = compose_failure_message("close", "TPEx API timeout", 130)
    assert "台股排程執行失敗" in msg
    assert "TPEx API timeout" in msg
    assert "2 分 10 秒" in msg or "130" in msg


# ── finding 1（critical）：真的用 subprocess 直接跑 `python scripts/run_scheduled.py`，
# 而不是像本檔案上方那樣自己先把專案根目錄塞進 sys.path 再 import——這樣才會真的踩到
# 「sys.path[0] 預設是 scripts/ 目錄，notifications 套件解析不到」這個問題，
# 之前 in-process 的測試方式測不出這個 bug（sys.path 已經被本檔案自己汙染過了）。

def test_direct_subprocess_invocation_invalid_mode_does_not_import_crash():
    """無效 mode 應該走 usage 錯誤分支（return 1 + 印 Usage），而不是在 import
    notifications.telegram 那一行就先炸 ModuleNotFoundError。"""
    result = subprocess.run(
        [sys.executable, "scripts/run_scheduled.py", "some-invalid-mode"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "ImportError" not in result.stderr
    assert result.returncode == 1
    assert "Usage:" in result.stdout


def test_direct_subprocess_invocation_test_notify_fails_with_config_error_not_import_error():
    """更嚴格的 smoke test：走到真的 import notifications.telegram 並呼叫
    send_telegram_message() 的 test-notify 路徑。刻意把 TELEGRAM_BOT_TOKEN/
    TELEGRAM_CHAT_ID 蓋成空字串（而非單純從環境刪掉——load_dotenv() 預設
    override=False，蓋成空字串才能保證不管 .env 檔案當下內容為何都測得穩定），
    確認失敗原因是「設定缺失」（TelegramConfigError），而不是 sys.path 沒修好
    造成的 ModuleNotFoundError/ImportError。"""
    env = dict(os.environ)
    env["TELEGRAM_BOT_TOKEN"] = ""
    env["TELEGRAM_CHAT_ID"] = ""
    result = subprocess.run(
        [sys.executable, "scripts/run_scheduled.py", "test-notify"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT), env=env,
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "ImportError" not in result.stderr
    assert result.returncode == 1
    assert "設定錯誤" in result.stdout


# ── main() 的整合測試：透過 monkeypatch 把 _SUMMARY_PATH/_STATE_PATH/_LOCK_PATH 換成
# tmp_path 底下的路徑，避免碰到真實的 logs/、data/ 檔案，同時對 run_main_py()/
# send_telegram_message()/is_trading_day() 等外部依賴打樁，讓 main() 本體邏輯可以在不
# 碰網路、不呼叫真的 main.py 的情況下被測到。

def _patch_paths(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.json"
    state_path = tmp_path / "notification_state.json"
    lock_path = tmp_path / "scheduler.lock"
    monkeypatch.setattr(sr, "_SUMMARY_PATH", summary_path)
    monkeypatch.setattr(sr, "_STATE_PATH", state_path)
    monkeypatch.setattr(sr, "_LOCK_PATH", lock_path)
    return summary_path, state_path, lock_path


def test_main_intraday_does_not_persist_state_when_telegram_send_fails(monkeypatch, tmp_path):
    """finding 4: Telegram 發送失敗（send_telegram_message 回傳 False）時，不能把這次的
    signal hash 寫進 notification_state.json——否則下一輪排程算出同一個 hash，
    should_notify_intraday() 會誤判成『已經通知過』，永久吃掉這個警示，直到訊號本身
    改變為止。"""
    summary_path, state_path, lock_path = _patch_paths(monkeypatch, tmp_path)
    summary = {
        "market_regime_label": "小漲", "market_regime": "小漲",
        "margin_alerts": [{"stock_id": "2330", "stock_name": "台積電",
                            "margin_pct": 5.2, "price_pct": -3.1, "days": 10}],
        "warnings": [],
    }

    def fake_run_main_py(mode, path, timeout=900):
        Path(path).write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(sr, "run_main_py", fake_run_main_py)
    monkeypatch.setattr(sr, "send_telegram_message", lambda text: False)  # 模擬發送失敗
    monkeypatch.setattr(sr, "is_market_hours", lambda now: True)
    monkeypatch.setattr(sys, "argv", ["run_scheduled.py", "intraday"])

    exit_code = sr.main()

    assert exit_code == 0  # main.py 本身成功執行，只是通知沒送出去，不算 main() 失敗
    assert not state_path.exists()
    # 下一輪同一份 summary 仍應判斷「要通知」——state 沒被錯誤地標記成已通知
    prev_state = sr.load_notification_state(str(state_path))
    assert sr.should_notify_intraday(summary, prev_state) is True


def test_main_intraday_persists_state_when_telegram_send_succeeds(monkeypatch, tmp_path):
    """對照組：發送成功時才應該寫入 notification_state.json，確保 finding 4 的修復
    只擋『失敗不寫』，沒有連帶把『成功也不寫』的正常路徑弄壞。"""
    summary_path, state_path, lock_path = _patch_paths(monkeypatch, tmp_path)
    summary = {
        "market_regime_label": "小漲", "market_regime": "小漲",
        "margin_alerts": [{"stock_id": "2330"}], "warnings": [],
    }

    def fake_run_main_py(mode, path, timeout=900):
        Path(path).write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(sr, "run_main_py", fake_run_main_py)
    monkeypatch.setattr(sr, "send_telegram_message", lambda text: True)
    monkeypatch.setattr(sr, "is_market_hours", lambda now: True)
    monkeypatch.setattr(sys, "argv", ["run_scheduled.py", "intraday"])

    exit_code = sr.main()

    assert exit_code == 0
    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["last_signal_hash"] == sr.compute_signal_hash(summary)


def test_main_close_detects_stale_summary_as_missing_and_notifies_failure(monkeypatch, tmp_path):
    """finding 5 + 7-2: main.py 回 exit 0 但沒有寫出新的 summary（模擬 Task 3 之後的
    non-fatal 寫檔失敗）時，若 logs/latest_summary.json 還殘留舊檔（例如前一天的），
    run_scheduled.py 不能把舊資料當新鮮結果去通知——執行前必須先刪舊檔，讓「讀不到
    summary」正確地被偵測到；且這個分支要送一則失敗通知，不能讓使用者以為
    『沒收到訊息＝一切正常』。"""
    summary_path, state_path, lock_path = _patch_paths(monkeypatch, tmp_path)
    stale_summary = {"trade_date": "2020-01-01", "market_regime_label": "舊資料"}
    summary_path.write_text(json.dumps(stale_summary, ensure_ascii=False), encoding="utf-8")

    def fake_run_main_py(mode, path, timeout=900):
        # 模擬 main.py 執行成功但摘要寫入失敗：exit 0、不寫任何檔案
        return {"returncode": 0, "stdout": "", "stderr": ""}

    sent = []
    monkeypatch.setattr(sr, "run_main_py", fake_run_main_py)
    monkeypatch.setattr(sr, "send_telegram_message", lambda text: sent.append(text) or True)
    monkeypatch.setattr(sr, "is_trading_day", lambda d: True)
    monkeypatch.setattr(sys, "argv", ["run_scheduled.py", "close"])

    exit_code = sr.main()

    assert exit_code == 1
    assert not summary_path.exists()  # 舊檔已被本次執行前的 unlink 清掉，且沒有新檔補上
    assert len(sent) == 1
    assert "讀不到執行摘要" in sent[0]


def test_main_sends_failure_notification_on_subprocess_timeout(monkeypatch, tmp_path):
    """finding 7-1: run_main_py() 逾時（main.py 卡超過 15 分鐘拋出的
    subprocess.TimeoutExpired）不該讓例外原封不動炸出 main()、也不該完全沒有通知——
    要送一則失敗通知，並讓 main() 回傳 1（執行鎖仍能透過外層 finally 正常釋放）。"""
    summary_path, state_path, lock_path = _patch_paths(monkeypatch, tmp_path)

    def fake_run_main_py(mode, path, timeout=900):
        raise subprocess.TimeoutExpired(cmd=[sys.executable, "main.py"], timeout=900)

    sent = []
    monkeypatch.setattr(sr, "run_main_py", fake_run_main_py)
    monkeypatch.setattr(sr, "send_telegram_message", lambda text: sent.append(text) or True)
    monkeypatch.setattr(sr, "is_trading_day", lambda d: True)
    monkeypatch.setattr(sys, "argv", ["run_scheduled.py", "close"])

    exit_code = sr.main()

    assert exit_code == 1
    assert len(sent) == 1
    assert "逾時" in sent[0]
    assert not lock_path.exists()  # finally 區塊仍正常釋放鎖
