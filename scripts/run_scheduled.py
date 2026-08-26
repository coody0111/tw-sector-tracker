"""
排程總控制器。負責：判斷交易日/盤中時間窗、取得執行鎖、呼叫 main.py、
讀取執行摘要、決定要不要通知、寫 scheduler.log。
見 docs/scheduler.md 完整規格。

Usage:
    python scripts/run_scheduled.py intraday
    python scripts/run_scheduled.py close
    python scripts/run_scheduled.py test-notify
"""
import hashlib
import json
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


_STATE_PATH = _PROJECT_ROOT / "data" / "notification_state.json"


def load_summary(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.error("讀取 summary JSON 失敗：%s", path)
        return None


def compute_signal_hash(summary: dict) -> str:
    """只 hash 會影響通知內容的欄位（融資警示的股票清單 + 市場狀態），
    避免 duration_seconds/started_at 這類每次都不同的欄位讓 hash 永遠不一樣。"""
    alert_ids = sorted(a.get("stock_id", "") for a in summary.get("margin_alerts", []))
    payload = json.dumps(
        {"alert_ids": alert_ids, "market_regime": summary.get("market_regime")},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_notification_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("notification_state.json 損毀，視為空狀態重建：%s", path)
        return {}


def save_notification_state(path: str, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_notify_intraday(summary: dict, prev_state: dict) -> bool:
    return compute_signal_hash(summary) != prev_state.get("last_signal_hash")


def _fmt_lots(n: int) -> str:
    return f"{n:,}張"


def compose_intraday_message(summary: dict) -> str:
    """盤中通知：只帶已驗證的融資背離警示 + 系統健康，絕不帶任何觀察用/評分內容
    （見 docs/scheduler.md §7.1/§7.4）——就算呼叫端誤傳了含 flow_watch 的完整 summary，
    這裡也不讀該欄位，保證盤中訊息不會外流未經證實的訊號。"""
    now_str = datetime.now().strftime("%H:%M")
    lines = [f"台股盤中更新｜{now_str}", "", f"市場狀態：{summary.get('market_regime_label', '未知')}"]
    alerts = summary.get("margin_alerts", [])
    lines.append(f"融資警示（新增）：{len(alerts)} 檔" if alerts else "融資警示：無")
    for a in alerts[:10]:
        lines.append("")
        lines.append(f"{a.get('stock_id', '?')} {a.get('stock_name', '?')}")
        lines.append(
            f"融資{a.get('days', '?')}日{a.get('margin_pct', 0.0):+.1f}%、"
            f"股價{a.get('price_pct', 0.0):+.1f}%（背離）"
        )
    lines.append("")
    warnings = summary.get("warnings", [])
    lines.append(f"資料異常：{'、'.join(warnings) if warnings else '無'}")
    return "\n".join(lines)


def compose_close_message(summary: dict, site_url: str) -> str:
    """收盤摘要：融資警示（已驗證）+ 今日籌碼動向（純觀察，非推薦）。
    籌碼動向區塊必須帶誠實揭露文字，避免被誤讀成推薦訊號（見 docs/scheduler.md §7.6）。"""
    lines = [
        f"台股收盤摘要｜{summary.get('trade_date', '')}", "",
        f"市場狀態：{summary.get('market_regime_label', '未知')}",
    ]
    alerts = summary.get("margin_alerts", [])
    lines.append(f"融資警示：{len(alerts)} 檔" if alerts else "融資警示：無")
    for a in alerts[:10]:
        lines.append(
            f"  {a.get('stock_id', '?')} {a.get('stock_name', '?')} "
            f"融資{a.get('days', '?')}日{a.get('margin_pct', 0.0):+.1f}%"
        )

    flow = summary.get("flow_watch", [])
    if flow:
        lines.append("")
        lines.append("── 今日籌碼動向（純觀察，非推薦）──")
        for f in flow[:10]:
            ratio = f.get("vs_avg20_ratio")
            turnover = f.get("turnover")
            ratio_str = f"是近20日均量的{ratio}倍" if ratio is not None else "近期均量資料不足"
            turnover_str = f"成交值{turnover / 1e8:.1f}億" if turnover else "成交值資料不足"
            lines.append("")
            lines.append(f"{f.get('stock_id', '?')} {f.get('stock_name', '?')}")
            lines.append(f"買超 {_fmt_lots(f.get('net_buy_lots', 0))}｜{ratio_str}｜{turnover_str}")
        lines.append("")
        lines.append("（僅陳述今日買超事實，不代表預測後續漲跌）")

    lines.append("")
    lines.append(f"資料完整性：{'正常' if not summary.get('warnings') else '、'.join(summary['warnings'])}")
    if summary.get("git_pushed"):
        lines.append(f"網站已更新：{site_url}")
    else:
        lines.append("網站未推送")
    return "\n".join(lines)


def compose_failure_message(mode: str, error: str, duration_seconds: float) -> str:
    mode_label = "盤中監控" if mode == "intraday" else "收盤更新"
    minutes, seconds = divmod(round(duration_seconds), 60)
    return "\n".join([
        f"台股排程執行失敗｜{datetime.now().strftime('%H:%M')}", "",
        f"模式：{mode_label}", f"錯誤：{error}", f"執行時間：{minutes} 分 {seconds} 秒", "",
        "已保留 logs/scheduler.log", "網站未推送",
    ])


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("intraday", "close", "test-notify"):
        print("Usage: python scripts/run_scheduled.py {intraday|close|test-notify}")
        return 1
    mode = sys.argv[1]

    from notifications.telegram import send_telegram_message, TelegramConfigError

    if mode == "test-notify":
        try:
            ok = send_telegram_message("台股排程通知測試 — 收到這則代表 Bot Token/Chat ID 設定正確。")
        except TelegramConfigError as exc:
            logger.error("test-notify 失敗：%s", exc)
            print(f"設定錯誤：{exc}")
            return 1
        print("已送出測試訊息" if ok else "發送失敗，詳見 logs/scheduler.log")
        return 0 if ok else 1

    now = datetime.now()
    if mode == "intraday" and not is_market_hours(now):
        logger.info("非盤中時間，%s 模式跳過", mode)
        return 0
    if mode == "close" and not is_trading_day(now.date()):
        logger.info("非交易日，close 模式跳過")
        return 0

    lock = ExecutionLock()
    if not lock.acquire():
        logger.info("執行鎖持有中，本次跳過")
        return 0

    try:
        started = datetime.now()
        result = run_main_py(mode, str(_SUMMARY_PATH))
        if result["returncode"] != 0:
            duration = (datetime.now() - started).total_seconds()
            error_msg = (result["stderr"] or "未知錯誤").strip().splitlines()[-1] if result["stderr"] else "main.py 執行失敗"
            try:
                send_telegram_message(compose_failure_message(mode, error_msg, duration))
            except TelegramConfigError:
                logger.error("main.py 執行失敗，且 Telegram 設定缺失，無法通知：%s", error_msg)
            logger.error("main.py 執行失敗（returncode=%d）：%s", result["returncode"], result["stderr"])
            return 1

        summary = load_summary(str(_SUMMARY_PATH))
        if summary is None:
            logger.error("讀不到 summary JSON，跳過通知")
            return 1

        try:
            if mode == "intraday":
                prev_state = load_notification_state(str(_STATE_PATH))
                if should_notify_intraday(summary, prev_state):
                    try:
                        send_telegram_message(compose_intraday_message(summary))
                    except TelegramConfigError as exc:
                        logger.error("Telegram 設定缺失，無法通知：%s", exc)
                    save_notification_state(str(_STATE_PATH), {
                        "last_signal_hash": compute_signal_hash(summary),
                        "last_market_regime": summary.get("market_regime"),
                        "last_notified_at": datetime.now().isoformat(),
                    })
                else:
                    logger.info("盤中訊號與上次相同，不重複通知")
            else:  # close
                site_url = os.environ.get("SITE_URL", "https://coody0111.github.io/tw-sector-tracker/")
                try:
                    send_telegram_message(compose_close_message(summary, site_url))
                except TelegramConfigError as exc:
                    logger.error("Telegram 設定缺失，無法通知：%s", exc)
        except Exception as exc:
            # 訊息組裝或發送階段任何未預期錯誤（例如 summary 欄位形狀跟預期不符造成的
            # KeyError）都不能讓例外原封不動炸出 main()——main.py 明明成功執行完了，
            # 使用者卻收不到任何通知、也看不出排程其實有問題。比照 run_main_py 失敗時的
            # 處理方式：記錄詳細錯誤、盡力送一則失敗通知（Telegram 設定缺失就只記 log，
            # 不再往外拋），讓這個分支的失敗行為跟「main.py 執行失敗」分支一致。
            duration = (datetime.now() - started).total_seconds()
            logger.error("通知組裝或發送階段發生未預期錯誤：%s", exc)
            try:
                send_telegram_message(compose_failure_message(mode, str(exc), duration))
            except TelegramConfigError:
                logger.error("通知組裝/發送失敗，且 Telegram 設定缺失，無法送出失敗通知：%s", exc)
            return 1

        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
