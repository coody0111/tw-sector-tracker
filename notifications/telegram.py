"""
Telegram Bot 訊息發送。
責任：呼叫 Telegram sendMessage、處理 timeout/HTTP 錯誤、分割超長訊息、
絕不把 Bot Token 或 API 回應內文輸出到 log（見 docs/scheduler.md §9 安全規則）。
"""
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# load_dotenv() 沒指定路徑時只會從「目前工作目錄」往上找 .env，手動在終端機測試時
# 如果沒有先 cd 進專案根目錄（例如忘記 cd、或從另一個視窗執行）就會完全找不到，
# 安靜地當作 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 未設定（2026-09-04 實測重現：同一段
# 程式在專案根目錄執行讀得到、在 C:\Users\Cody 執行完全讀不到）。改成明確指到專案根目錄
# 的 .env，不管從哪個目錄執行這支模組都抓得到——排程本身用 -WorkingDirectory 已經沒事，
# 這個修法主要是保護手動測試的情境。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_MESSAGE_LENGTH = 4000  # Telegram 官方上限 4096，留緩衝給分割
_TIMEOUT_SECONDS = 15


class TelegramConfigError(Exception):
    """TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定。"""


def _split_message(text: str, max_length: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    """依空行分段切割過長訊息，避免切在句子中間；單段仍過長時強制切斷。"""
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_length:
            if current:
                chunks.append(current)
            current = para[:max_length] if len(para) > max_length else para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(
    text: str, token: str | None = None, chat_id: str | None = None
) -> bool:
    """
    傳送訊息到 Telegram。token/chat_id 未傳入時讀環境變數
    TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID。兩者任一未設定時拋 TelegramConfigError
    （安全失敗，不嘗試發送）。回傳是否所有訊息片段都成功送達。
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise TelegramConfigError("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定")

    url = _API_BASE.format(token=token)
    all_ok = True
    for chunk in _split_message(text):
        try:
            resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.error("Telegram 發送失敗：HTTP %d", resp.status_code)
                all_ok = False
        except requests.exceptions.Timeout:
            logger.error("Telegram 發送逾時（%d秒）", _TIMEOUT_SECONDS)
            all_ok = False
        except requests.exceptions.RequestException as exc:
            logger.error("Telegram 發送發生錯誤：%s", type(exc).__name__)
            all_ok = False
    return all_ok
