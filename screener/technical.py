"""
技術指標計算 - 純 pandas 實作，不依賴外部技術指標庫。
"""
import pandas as pd
import numpy as np


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — 值越高趨勢越強，< 25 代表區間盤。"""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    dm_plus = ((high - high.shift()) > (low.shift() - low)).astype(float) * (high - high.shift()).clip(lower=0)
    dm_minus = ((low.shift() - low) > (high - high.shift())).astype(float) * (low.shift() - low).clip(lower=0)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    di_plus = 100 * dm_plus.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    di_minus = 100 * dm_minus.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean()


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    mid = sma(series, period)
    band = series.rolling(period).std()
    return mid + std * band, mid, mid - std * band  # upper, mid, lower


def calculate_all(df: pd.DataFrame) -> dict:
    """
    輸入含 open/high/low/close/volume 的 DataFrame（按日期升序），
    回傳最新一天的所有指標。
    需要至少 30 筆資料（約 6 週）。
    """
    if len(df) < 20:
        return {}

    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close

    sma20 = sma(close, 20)
    sma50 = sma(close, 50)
    rsi14 = rsi(close, 14)
    adx14 = adx(high, low, close, 14)
    bb_upper, bb_mid, bb_lower = bollinger(close, 20)

    price = float(close.iloc[-1])
    low_20d = float(low.rolling(20).min().iloc[-1])
    high_20d = float(high.rolling(20).max().iloc[-1])
    range_pct = (high_20d - low_20d) / low_20d * 100 if low_20d > 0 else 0

    return {
        "price":      price,
        "sma20":      _last(sma20),
        "sma50":      _last(sma50),
        "rsi":        _last(rsi14),
        "adx":        _last(adx14),
        "bb_upper":   _last(bb_upper),
        "bb_mid":     _last(bb_mid),
        "bb_lower":   _last(bb_lower),
        "low_20d":    low_20d,
        "high_20d":   high_20d,
        "range_pct":  round(range_pct, 2),
    }


def _last(s: pd.Series):
    valid = s.dropna()
    return round(float(valid.iloc[-1]), 4) if not valid.empty else None
