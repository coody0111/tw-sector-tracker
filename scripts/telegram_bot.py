"""Telegram 查股常駐程式（2026-11-02 Cody）：登入 Windows 時由排程 TW-Sector-TelegramBot 啟動，
用 getUpdates 長輪詢收訊息，只回 TELEGRAM_CHAT_ID 這個聊天室，其他人一律不理。
回覆內容見 notifications/stock_lookup.py。只讀資料，不跑更新、不動 git。
log 不寫 Token、不寫訊息內文（docs/scheduler.md §9）。
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from notifications.stock_lookup import handle  # noqa: E402
from notifications.telegram import send_telegram_message  # noqa: E402  （順便載入 .env）

logger = logging.getLogger("telegram_bot")

OFFSET_PATH = ROOT / "data" / "telegram_offset.txt"   # 已處理到哪一則；重啟後不重複回覆
POLL_SECONDS = 50
RETRY_SECONDS = 5


def read_offset(path: Path = OFFSET_PATH) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_offset(offset: int, path: Path = OFFSET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


def reply_for(update: dict, chat_id: str) -> str | None:
    """一筆 update → 要回的文字；不是 Cody 的聊天室、或不是文字訊息就回 None（不理）。"""
    msg = update.get("message") or {}
    if str((msg.get("chat") or {}).get("id")) != str(chat_id) or not msg.get("text"):
        return None
    try:
        return handle(msg["text"])
    except Exception as exc:
        logger.error("查詢失敗：%s", type(exc).__name__)
        return "查詢失敗，請稍後再試。"


def poll_once(token: str, chat_id: str, offset: int, send=send_telegram_message, get=requests.get) -> int:
    """抓一批訊息、逐筆回覆，回傳新的 offset。每處理一筆就存 offset，當掉重啟也不會重回。"""
    resp = get(f"https://api.telegram.org/bot{token}/getUpdates",
               params={"offset": offset, "timeout": POLL_SECONDS}, timeout=POLL_SECONDS + 10)
    if resp.status_code != 200:
        logger.error("getUpdates 失敗：HTTP %d", resp.status_code)
        time.sleep(RETRY_SECONDS)
        return offset
    for update in resp.json().get("result") or []:
        offset = update["update_id"] + 1
        text = reply_for(update, chat_id)
        if text is None:
            logger.info("略過一則訊息（非指定聊天室或非文字）")
        else:
            send(text, chat_id=chat_id)
            logger.info("已回覆一則查詢")
        save_offset(offset)
    return offset


def main() -> None:
    os.chdir(ROOT)                             # 相對路徑（data/、docs/）都以專案根目錄為準
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=str(ROOT / "logs" / "telegram_bot.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，查股程式不啟動")
        sys.exit(1)
    logger.info("查股程式啟動")
    offset = read_offset()
    while True:
        try:
            offset = poll_once(token, chat_id, offset)
        except Exception as exc:                 # 斷線、睡眠醒來逾時等：等一下再接著收
            logger.warning("輪詢中斷：%s，%d 秒後重試", type(exc).__name__, RETRY_SECONDS)
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
