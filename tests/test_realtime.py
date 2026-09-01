# tests/test_realtime.py
"""即時行情（mis.twse.com.tw）解析測試。

回歸來源（2026-08-31 全庫稽核）：76 筆 close 落在同一列的 [low, high] 之外，
全部是 volume ≤ 14 的冷門股。成因是 `_best_price()` 在 z="-"（無最近成交）時
退而取買賣五檔的**掛單價**——對漲停鎖死正確，對「當天幾乎沒成交」則會拿掛單價
當收盤價，跟 OHLC 不同源，change_pct 因此失真。
"""
from unittest.mock import MagicMock, patch

from scrapers.realtime import (
    _best_price,
    _clamp_to_day_range,
    _field,
    fetch_realtime_prices,
)


def test_clamp_pulls_price_back_into_day_range():
    """本回歸的主角：8101 當天唯一 1 張成交在 12.4，掛單價 11.55 不該當成收盤價。"""
    assert _clamp_to_day_range(11.55, high=12.4, low=12.4) == 12.4
    assert _clamp_to_day_range(13.0, high=12.4, low=12.0) == 12.4   # 高於當日最高
    assert _clamp_to_day_range(11.0, high=12.4, low=12.0) == 12.0   # 低於當日最低


def test_clamp_leaves_normal_price_untouched():
    """價格本來就在區間內時不能被動到。"""
    assert _clamp_to_day_range(12.2, high=12.4, low=12.0) == 12.2
    assert _clamp_to_day_range(12.4, high=12.4, low=12.0) == 12.4   # 邊界
    assert _clamp_to_day_range(12.0, high=12.4, low=12.0) == 12.0


def test_clamp_noop_when_no_trades_that_day():
    """完全沒成交時 h/l 是 None，維持原本的掛單價 fallback，不能亂夾。"""
    assert _clamp_to_day_range(11.55, high=None, low=None) == 11.55
    assert _clamp_to_day_range(11.55, high=12.4, low=None) == 11.55
    assert _clamp_to_day_range(11.55, high=None, low=12.0) == 11.55


def test_clamp_ignores_inverted_range():
    """high < low 代表來源資料本身異常，不要據此改動價格。"""
    assert _clamp_to_day_range(11.55, high=10.0, low=12.0) == 11.55


def test_field_parses_and_rejects_placeholders():
    item = {"o": "1,234.5", "h": "-", "l": "", "z": "abc"}
    assert _field(item, "o") == 1234.5
    assert _field(item, "h") is None
    assert _field(item, "l") is None
    assert _field(item, "z") is None
    assert _field(item, "missing") is None


def _patch_session(msg_array):
    """patch 掉 requests.Session()——realtime.py 用的是 session.get，
    不是 requests.get；patch 錯目標會讓測試真的打 mis.twse.com.tw。"""
    resp = MagicMock()
    resp.json.return_value = {"msgArray": msg_array}
    session = MagicMock()
    session.get.return_value = resp
    return patch("scrapers.realtime.requests.Session", return_value=session)


def test_fetch_realtime_prices_clamps_close_and_keeps_change_consistent():
    """端到端：無成交價（z="-"）＋ 買方掛單低於當日區間時，
    寫出的 close 要是 12.4（當日成交價），change_pct 要跟著一起修正。"""
    item = {
        "c": "8101", "n": "測試股",
        "z": "-",                      # 無最近成交 → 會走五檔 fallback
        "b": "11.55_11.50_11.45",      # 買方掛單（低於當日成交區間）
        "o": "12.4", "h": "12.4", "l": "12.4",
        "y": "12.0",                   # 昨收
        "v": "1", "t": "13:30:00",
    }
    with _patch_session([item]), patch("scrapers.realtime.time.sleep"):
        df = fetch_realtime_prices(["8101"])

    assert len(df) == 1
    row = df.iloc[0]
    assert row["close"] == 12.4, "收盤價應夾回當日成交區間，不是買方掛單 11.55"
    assert row["low"] <= row["close"] <= row["high"], "close 必須落在 [low, high] 內"
    # change 要用夾回後的價格算：12.4 - 12.0 = 0.4
    assert row["change"] == 0.4
    assert row["change_pct"] == 3.33


def test_fetch_realtime_prices_keeps_limit_up_lock_behaviour():
    """漲停鎖死（z="-"、買方掛在漲停價）仍要取得漲停價——這是 _best_price
    五檔 fallback 存在的理由，不能被這次的夾取修掉。"""
    item = {
        "c": "2330", "n": "台積電",
        "z": "-",
        "b": "1100.0_1099.0",          # 買方掛在漲停價
        "o": "1050.0", "h": "1100.0", "l": "1045.0",
        "y": "1000.0",
        "v": "50000", "t": "13:30:00",
    }
    with _patch_session([item]), patch("scrapers.realtime.time.sleep"):
        df = fetch_realtime_prices(["2330"])

    row = df.iloc[0]
    assert row["close"] == 1100.0, "漲停價仍應取得，夾取不該影響這條路徑"
    assert row["change_pct"] == 10.0


def test_best_price_prefers_last_trade():
    """有最近成交價時直接用它，不走五檔。"""
    assert _best_price({"z": "12.35", "b": "11.55_11.50"}) == 12.35


def test_best_price_skips_zero_and_falls_back():
    """price=0 表示尚未開盤/停牌，要繼續往下 fallback。"""
    assert _best_price({"z": "0", "b": "11.55_11.50"}) == 11.55
    assert _best_price({"z": "-", "b": "-", "a": "-", "h": "12.4"}) == 12.4
    assert _best_price({"z": "-", "b": "-", "a": "-", "h": "-", "o": "12.0"}) == 12.0
    assert _best_price({"z": "-", "b": "-", "a": "-", "h": "-", "o": "-"}) is None
