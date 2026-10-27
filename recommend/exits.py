"""出場規則（規格 §11）：停損 6%、自最高收盤回落 20%、最長 60 個交易日；收盤判斷、隔天開盤進場。"""
import pandas as pd

FEE = 0.001425 * 0.28   # 手續費 2.8 折，買賣各一次
TAX = 0.003             # 賣出證交稅
STOP = 0.06
TRAIL = 0.20
MAX_HOLD = 60


def path_columns(features) -> list:
    """模擬交易要帶的欄位：原始開收（顯示用）＋有的話還原開收（判斷用）。"""
    return ["stock_id", "date", "open", "close", "one_word"] + [c for c in ("aopen", "aclose") if c in features.columns]


def simulate_trade(path: pd.DataFrame, signal_pos: int) -> dict | None:
    """path：單一股票依日期排序的 date/open/close/one_word（有 aopen/aclose 就用還原價判斷與算報酬）；
    signal_pos：訊號日在 path 的位置。隔天一字漲停買不到 → None。資料走完還沒觸發出場 → exit_reason「持有中」。
    entry_price／exit_price 回傳原始價（給成績單顯示）；停損、回落、報酬用還原價（除權息下跳不算跌，2026-10-27）。"""
    e = signal_pos + 1
    if e >= len(path) or bool(path["one_word"].iloc[e]):
        return None
    opens = path["aopen"] if "aopen" in path.columns else path["open"]
    entry = float(opens.iloc[e])
    if not entry > 0:
        return None
    closes = (path["aclose"] if "aclose" in path.columns else path["close"]).to_numpy(dtype=float)
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
    ret = closes[k] * (1 - FEE - TAX) / (entry * (1 + FEE)) - 1
    return {
        "entry_date": path["date"].iloc[e], "entry_price": float(path["open"].iloc[e]),
        "exit_date": path["date"].iloc[k], "exit_price": float(path["close"].iloc[k]), "exit_reason": reason,
        "hold_days": k - e + 1, "ret": ret, "r_multiple": ret / STOP, "mfe": peak / entry - 1,
    }
