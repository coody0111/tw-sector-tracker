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
    取即時最佳價格。
    當 z="-"（漲停/跌停鎖死，無最近成交）時，掃描五檔買賣價找第一個有效值。
    price = 0 表示尚未開盤或停牌，回 None 略過。
    """
    def _parse(s: str) -> float | None:
        try:
            v = float(s.replace(",", ""))
            return v if v > 0 else None
        except (ValueError, AttributeError):
            return None

    def _first_valid_in_levels(price_str: str) -> float | None:
        if not price_str or price_str in ("-", "---"):
            return None
        for p in price_str.split("_"):
            v = _parse(p)
            if v:
                return v
        return None

    # 最近成交價（正常盤中）
    z = item.get("z", "-")
    if z and z != "-":
        v = _parse(z)
        if v:
            return v

    # z="-" 表示鎖漲/跌停：掃描買方五檔（漲停時買方有掛單）
    v = _first_valid_in_levels(item.get("b", ""))
    if v:
        return v

    # 再掃描賣方五檔（跌停時賣方有掛單）
    v = _first_valid_in_levels(item.get("a", ""))
    if v:
        return v

    # fallback: 今日最高（漲停時 h = 漲停價）
    v = _parse(item.get("h", "-") or "-")
    if v:
        return v

    # 最後 fallback: 今開
    return _parse(item.get("o", "-") or "-")


def _field(item: dict, key: str) -> float | None:
    """取 msgArray 裡的數值欄位，"-"／空／無法解析一律 None。"""
    v = item.get(key, "-")
    try:
        return float(v.replace(",", "")) if v and v != "-" else None
    except (ValueError, AttributeError):
        return None


def _clamp_to_day_range(price: float, high: float | None, low: float | None) -> float:
    """把收盤價夾回當日成交區間 [low, high]。

    `_best_price()` 在 z="-"（無最近成交）時會退而取買賣五檔的**掛單價**。對「漲停
    鎖死」那是正確的（買方掛單價就是漲停價），但對「當天幾乎沒成交」的冷門股就會
    拿掛單價當收盤價，跟同一列的 OHLC 不同源、對不起來：

        8101  2026-08-31  open=high=low=12.4  close=11.55  volume=1

    那唯一 1 張成交在 12.4，close 卻取了買方掛單 11.55，change_pct 因此失真。
    只要當天有成交（h/l 才會有值），依定義收盤價必落在 [low, high] 內，所以夾回去
    是安全的修正；完全沒成交時 h/l 是 None，維持原本的掛單價 fallback 不動。
    （2026-08-31 稽核：全庫 76 筆 close 落在區間外，皆為 volume ≤ 14 的冷門股。）
    """
    if high is None or low is None or high < low:
        return price
    return min(max(price, low), high)


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
            if price is None or price <= 0:
                continue

            # 先夾回當日成交區間，change/change_pct 才會跟 OHLC 一致
            day_open, day_high, day_low = (_field(item, k) for k in ("o", "h", "l"))
            price = _clamp_to_day_range(price, day_high, day_low)

            y_str = item.get("y", "-")
            prev = float(y_str.replace(",", "")) if y_str and y_str != "-" else None
            if prev is None or prev == 0:
                continue

            change = round(price - prev, 2)
            change_pct = round(change / prev * 100, 2)
            vol_str = item.get("v", "0")
            vol = int(float(vol_str.replace(",", ""))) if vol_str and vol_str != "-" else 0

            rows.append({
                "stock_id":   sid,
                "stock_name": item.get("n", ""),
                "close":      price,
                "change":     change,
                "change_pct": change_pct,
                "volume":     vol,
                "open":       day_open,
                "high":       day_high,
                "low":        day_low,
                "time":       item.get("t", ""),
            })

        if bi < total_batches:
            time.sleep(0.3)

    df = pd.DataFrame(rows)
    logger.info("即時行情：取得 %d 支", len(df))
    return df
