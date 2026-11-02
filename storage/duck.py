"""DuckDB 讀寫連線＋鎖重試（2026-11-02 Cody）。

DuckDB 同一時間只允許一個程序寫入；別的程序開著唯讀連線時（Telegram 查股每次約 0.1 秒），
寫入端 connect 會直接拋 IOException「Could not set lock」。排程的寫入一律走這裡：拿不到鎖就等一下再試。
同一程序內的其他錯誤（檔案壞掉、路徑錯）不重試，原樣拋出。"""
import logging
import time

import duckdb

logger = logging.getLogger(__name__)

ATTEMPTS = 20          # 0.5 秒 × 20 ≈ 10 秒：查股一次只佔 0.1 秒，綽綽有餘
WAIT_SECONDS = 0.5


def _is_lock_error(exc: Exception) -> bool:
    return "lock" in str(exc).lower()


def connect_rw(db_path: str, attempts: int = ATTEMPTS, wait: float = WAIT_SECONDS,
               sleep=time.sleep) -> duckdb.DuckDBPyConnection:
    """開讀寫連線；被別的程序鎖住時重試，最後一次仍失敗就拋出原本的例外。"""
    for i in range(attempts):
        try:
            return duckdb.connect(db_path)
        except duckdb.IOException as exc:
            if not _is_lock_error(exc) or i == attempts - 1:
                raise
            if i == 0:
                logger.info("DuckDB 被其他程序佔用（可能是 Telegram 查股），%.1f 秒後重試", wait)
            sleep(wait)
    raise RuntimeError("unreachable")
