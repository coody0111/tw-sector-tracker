"""出場規則（規格 §11）：停損 6%、自最高收盤回落 20%、最長 60 個交易日；收盤判斷、隔天開盤進場。"""
import pandas as pd

FEE = 0.001425 * 0.28   # 手續費 2.8 折，買賣各一次
TAX = 0.003             # 賣出證交稅
STOP = 0.06
TRAIL = 0.20
MAX_HOLD = 60


def simulate_trade(path: pd.DataFrame, signal_pos: int) -> dict | None:
    """path：單一股票依日期排序的 date/open/close/one_word；signal_pos：訊號日在 path 的位置。
    隔天一字漲停買不到 → None。資料走完還沒觸發出場 → exit_reason「持有中」。"""
    e = signal_pos + 1
    if e >= len(path) or bool(path["one_word"].iloc[e]):
        return None
    entry = float(path["open"].iloc[e])
    if not entry > 0:
        return None
    closes = path["close"].to_numpy(dtype=float)
    last = min(len(path), e + MAX_HOLD) - 1
    peak, reason, k = entry, "持有中", e
    for k in range(e, last + 1):
        c = closes[k]
        peak = max(peak, c)
        if c <= entry * (1 - STOP):
            reason = "停損"
            break
        if c <= peak * (1 - TRAIL):
            reason = "回落"
            break
    else:
        if last - e + 1 == MAX_HOLD:
            reason = "到期"
    exit_price = closes[k]
    ret = exit_price * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1
    return {
        "entry_date": path["date"].iloc[e], "entry_price": entry,
        "exit_date": path["date"].iloc[k], "exit_price": exit_price, "exit_reason": reason,
        "hold_days": k - e + 1, "ret": ret, "r_multiple": ret / STOP, "mfe": peak / entry - 1,
    }
