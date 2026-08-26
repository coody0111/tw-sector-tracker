"""
排程總控制器。負責：判斷交易日/盤中時間窗、取得執行鎖、呼叫 main.py、
讀取執行摘要、決定要不要通知、寫 scheduler.log。
見 docs/scheduler.md 完整規格。

Usage:
    python scripts/run_scheduled.py intraday
    python scripts/run_scheduled.py close
    python scripts/run_scheduled.py test-notify
"""
import logging
import os
import subprocess
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK_PATH = _PROJECT_ROOT / "logs" / "scheduler.lock"
_SUMMARY_PATH = _PROJECT_ROOT / "logs" / "latest_summary.json"
_LOG_PATH = _PROJECT_ROOT / "logs" / "scheduler.log"

logging.basicConfig(
    filename=str(_LOG_PATH), level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_MARKET_OPEN = dt_time(9, 0)
_MARKET_CLOSE = dt_time(13, 30)


def is_trading_day(d: date) -> bool:
    """週一至週五為交易日。不含國定假日行事曆（YAGNI，docs/scheduler.md 沒有要求；
    國定假日誤跑的風險：main.py 抓不到當天資料會自然回退到最近交易日，不會產生錯誤資料，
    只是浪費一次排程，接受這個風險，不在第一版處理）。"""
    return d.weekday() < 5


def is_market_hours(now: datetime) -> bool:
    """週一至週五 09:00-13:30（含端點）。"""
    if not is_trading_day(now.date()):
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


class ExecutionLock:
    """檔案鎖：`logs/scheduler.lock` 存持鎖程序的 PID。程序異常結束後鎖必須能自動釋放——
    用 `os.kill(pid, 0)` 檢查該 PID 是否還活著，不活著就視為過期鎖，直接接管
    （見 docs/scheduler.md §8.1）。"""

    def __init__(self, lock_path: str = None):
        self.lock_path = Path(lock_path) if lock_path else _LOCK_PATH

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists, we just can't signal it — still alive
        except OSError:
            return False
        except ValueError:
            return False
        return True

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                held_pid = int(self.lock_path.read_text().strip())
            except (ValueError, OSError):
                held_pid = None
            if held_pid and self._pid_alive(held_pid):
                logger.warning("執行鎖被 PID %d 持有，本次直接結束", held_pid)
                return False
            logger.info("偵測到過期鎖（PID %s 已不存在），自動接管", held_pid)
        self.lock_path.write_text(str(os.getpid()))
        return True

    def release(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def run_main_py(mode: str, summary_path: str, timeout: int = 900) -> dict:
    """呼叫 `python main.py`。intraday 模式帶 --realtime --no-push，close 模式不帶。
    兩種模式都帶 --summary-json。回傳 {returncode, stdout, stderr}。"""
    cmd = [sys.executable, str(_PROJECT_ROOT / "main.py")]
    if mode == "intraday":
        cmd += ["--realtime", "--no-push"]
    cmd += ["--summary-json", summary_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("intraday", "close", "test-notify"):
        print("Usage: python scripts/run_scheduled.py {intraday|close|test-notify}")
        sys.exit(1)
    # test-notify 模式跟鎖定/main.py 呼叫的接線在 Task 5 完成
    print(f"骨架階段：{sys.argv[1]} 模式的完整流程會在 Task 5 接上")
