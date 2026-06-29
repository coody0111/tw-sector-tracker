"""
券商分點買賣超 scraper — 每日盤後更新
用於「隔日沖分點」分析：識別 D+0 大買、D+1 大賣的分點主力。

TODO: TWSE 分點 API endpoint 已從舊版 /exchangeReport/BSALE2 移除。
      請在瀏覽器開 F12 → Network → 前往 TWSE 分點查詢頁面觸發資料載入 → 找 XHR 請求 URL。
      確認後填入 _TWSE_BROKER_URL。
"""
import logging
import time
from datetime import date
from typing import Optional

import duckdb
import requests

logger = logging.getLogger(__name__)

# ── 待填入的 endpoint ──────────────────────────────────────────────────────────
# 步驟：
# 1. 瀏覽器開 https://www.twse.com.tw/zh/trading/exchange/BSALE2.html
# 2. F12 → Network → 輸入股票代號查詢
# 3. 找到 XHR 請求，複製 URL 填入此處
_TWSE_BROKER_URL: Optional[str] = None  # e.g. "https://www.twse.com.tw/rwd/zh/..."
# ─────────────────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.twse.com.tw/",
}
_DB_PATH = "data/screener.db"


def fetch_broker_data(stock_id: str, date_str: str) -> list[dict]:
    """
    抓單支股票在指定日期的各分點買賣超。
    date_str: 'YYYYMMDD'
    回傳 list of {broker_id, broker_name, buy_shares, sell_shares, net_shares}
    """
    if _TWSE_BROKER_URL is None:
        raise NotImplementedError(
            "分點 API endpoint 尚未設定。請照 broker_branch.py 頂端說明找到 URL 後填入 _TWSE_BROKER_URL。"
        )

    import warnings
    warnings.filterwarnings("ignore")

    params = {"date": date_str, "stockNo": stock_id, "response": "json"}
    try:
        r = requests.get(_TWSE_BROKER_URL, params=params, headers=_HEADERS, timeout=10, verify=False)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.debug("分點 %s %s 失敗: %s", stock_id, date_str, e)
        return []

    if data.get("stat") != "OK":
        return []

    rows = []
    fields = data.get("fields", [])
    for item in data.get("data", []):
        try:
            rows.append({
                "broker_id":   str(item[0]).strip(),
                "broker_name": str(item[1]).strip(),
                "buy_shares":  int(str(item[2]).replace(",", "") or 0),
                "sell_shares": int(str(item[3]).replace(",", "") or 0),
                "net_shares":  int(str(item[4]).replace(",", "") or 0),
            })
        except (IndexError, ValueError):
            continue
    return rows


def fetch_broker_batch(
    stock_ids: list[str],
    trade_date: date,
    delay: float = 0.5,
) -> dict[str, list[dict]]:
    """
    批次抓多支股票的分點資料。
    回傳 {stock_id: [broker_rows]}
    """
    date_str = trade_date.strftime("%Y%m%d")
    result = {}
    for i, sid in enumerate(stock_ids, 1):
        rows = fetch_broker_data(sid, date_str)
        if rows:
            result[sid] = rows
        if i % 20 == 0 or i == len(stock_ids):
            logger.info("分點 [%d/%d] 有資料 %d 支", i, len(stock_ids), len(result))
        time.sleep(delay)
    return result


def save_to_db(trade_date: date, broker_map: dict[str, list[dict]]) -> int:
    """upsert 分點資料到 DuckDB broker_branch 表，回傳寫入筆數。"""
    if not broker_map:
        return 0

    date_str = trade_date.isoformat()
    rows = []
    for stock_id, branches in broker_map.items():
        for b in branches:
            rows.append({
                "stock_id":    stock_id,
                "date":        date_str,
                "broker_id":   b["broker_id"],
                "broker_name": b["broker_name"],
                "buy_shares":  b["buy_shares"],
                "sell_shares": b["sell_shares"],
                "net_shares":  b["net_shares"],
            })

    import pandas as pd
    df = pd.DataFrame(rows)
    con = duckdb.connect(_DB_PATH)
    con.execute("DELETE FROM broker_branch WHERE date = ?", [date_str])
    con.execute("INSERT INTO broker_branch SELECT * FROM df")
    n = len(df)
    con.close()
    return n


def get_daytrader_suspects(
    con: duckdb.DuckDBPyConnection,
    min_occurrences: int = 3,
    lookback_days: int = 30,
) -> dict[str, set[str]]:
    """
    找出「隔日沖主力分點」：在過去 N 天內，D+0 大買後 D+1 大賣 ≥ min_occurrences 次。
    回傳 {broker_id: set(stock_ids)} 的高風險組合。
    """
    df = con.execute(f"""
        WITH t AS (
            SELECT
                b1.stock_id,
                b1.broker_id,
                b1.broker_name,
                b1.date     AS buy_date,
                b2.date     AS sell_date,
                b1.net_shares AS buy_net,
                b2.net_shares AS sell_net
            FROM broker_branch b1
            JOIN broker_branch b2
              ON b1.stock_id = b2.stock_id
             AND b1.broker_id = b2.broker_id
             AND b2.date = b1.date + INTERVAL '1' DAY
            WHERE b1.net_shares > 500000   -- 買超 > 500張
              AND b2.net_shares < -300000  -- 隔日賣超 > 300張
              AND b1.date >= CURRENT_DATE - INTERVAL '{lookback_days}' DAY
        )
        SELECT broker_id, broker_name, stock_id, COUNT(*) AS cnt
        FROM t
        GROUP BY broker_id, broker_name, stock_id
        HAVING cnt >= {min_occurrences}
        ORDER BY cnt DESC
    """).df()

    suspects: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        suspects.setdefault(row["broker_id"], set()).add(row["stock_id"])
    return suspects
