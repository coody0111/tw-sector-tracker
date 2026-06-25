"""
盤中即時行情（mis.twse.com.tw）

支援 TWSE 上市（tse_）與 TPEx 上市（otc_）股票，
每次呼叫約 3-5 秒可取得全部 1040 支的即時報價。

欄位說明（TWSE mis API）：
  z  — 最近成交價（活躍時段有值；無近期成交時回 "-"）
  y  — 昨收
  o  — 今開
  h  — 今高
  l  — 今低
  v  — 成交張數（千股）
  b  — 五檔買價（"_" 分隔）
  a  — 五檔賣價（"_" 分隔）
  t  — 最新時間
  ex — 掛牌市場 tse / otc
"""
import logging
import time
from typing import List

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_REALTIME_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
_INIT_URL = "https://mis.twse.com.tw/stock/index.jsp"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mis.twse.com.tw/stock/index.jsp",
}
_BATCH = 80  # 每次請求的股票數（×2 前綴 = 160 個 ex_ch）


def _best_price(item: dict) -> float | None:
    """
    取即時最佳價格：
      1. z（最近成交）有值且 > 0 → 用 z
      2. 否則取五檔買價第一檔（> 0）
      3. 否則取今開（> 0）
    price = 0 表示尚未開盤或停牌，回 None 略過。
    """
    def _parse(s: str) -> float | None:
        try:
            v = float(s.replace(",", ""))
            return v if v > 0 else None
        except (ValueError, AttributeError):
            return None

    z = item.get("z", "-")
    if z and z != "-":
        v = _parse(z)
        if v:
            return v

    b = item.get("b", "")
    if b and b != "-":
        first_bid = b.split("_")[0]
        if first_bid and first_bid != "-":
            v = _parse(first_bid)
            if v:
                return v

    o = item.get("o", "-")
    if o and o != "-":
        v = _parse(o)
        if v:
            return v

    return None


def fetch_realtime_prices(stock_ids: List[str]) -> pd.DataFrame:
    """
    批次查詢即時行情，回傳 DataFrame 欄位：
      stock_id, close, change, change_pct, volume, open, high, low, time
    """
    session = requests.Session()
    try:
        session.get(_INIT_URL, headers=_HEADERS, timeout=8)
    except Exception:
        pass  # 初始化失敗也繼續，部分情境不需要 session cookie

    rows = []
    total_batches = (len(stock_ids) + _BATCH - 1) // _BATCH

    for bi, i in enumerate(range(0, len(stock_ids), _BATCH), 1):
        batch = stock_ids[i:i + _BATCH]
        # 每支股票帶兩個前綴，讓 API 自行對應正確市場
        ex_ch = "|".join(f"tse_{sid}.tw|otc_{sid}.tw" for sid in batch)

        try:
            resp = session.get(
                _REALTIME_URL,
                params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
                headers=_HEADERS,
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("即時行情第 %d/%d 批失敗: %s", bi, total_batches, exc)
            continue

        seen = set()
        for item in data.get("msgArray", []):
            sid = item.get("c", "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)

            price = _best_price(item)
            if price is None:
                continue

            y_str = item.get("y", "-")
            prev = float(y_str.replace(",", "")) if y_str and y_str != "-" else None
            if prev is None or prev == 0:
                continue

            change = round(price - prev, 2)
            change_pct = round(change / prev * 100, 2)
            vol_str = item.get("v", "0")
            vol = int(float(vol_str.replace(",", ""))) if vol_str and vol_str != "-" else 0

            def _f(key):
                v = item.get(key, "-")
                try:
                    return float(v.replace(",", "")) if v and v != "-" else None
                except ValueError:
                    return None

            rows.append({
                "stock_id":   sid,
                "stock_name": item.get("n", ""),
                "close":      price,
                "change":     change,
                "change_pct": change_pct,
                "volume":     vol,
                "open":       _f("o"),
                "high":       _f("h"),
                "low":        _f("l"),
                "time":       item.get("t", ""),
            })

        if bi < total_batches:
            time.sleep(0.3)

    df = pd.DataFrame(rows)
    logger.info("即時行情：取得 %d 支", len(df))
    return df
