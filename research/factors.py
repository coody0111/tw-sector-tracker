"""因子庫：每個因子 = 函式(面板) -> date×stock 的因子值。

**Point-in-time 鐵律**：第 t 列的輸出只能用到第 t 列（含）以前的資料。
所有 rolling 都是回看窗；任何 shift 只能往「過去」取（shift(+n)），
絕不使用 shift(-n)（那是未來，只有 factor_data.forward_returns 可以用）。

符號約定：因子值越大 = 預期未來報酬越高。所以「低波動異象」實作為負的波動度。
"""

from __future__ import annotations

from typing import Callable

import pandas as pd


def _daily_returns(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    # fill_method=None：缺值就讓它是缺值，不要用前值補（補了等於偷造一筆沒發生的報酬）
    return panel["close"].pct_change(fill_method=None)


def momentum(panel: dict[str, pd.DataFrame], n: int) -> pd.DataFrame:
    """過去 n 個交易日報酬：close[t]/close[t-n] - 1。"""
    close = panel["close"]
    return close / close.shift(n) - 1.0


def reversal_5(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """短期反轉：過去 5 日報酬取負。"""
    return -momentum(panel, 5)


def low_volatility_20(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """低波動異象：過去 20 日日報酬標準差，取負（波動低 -> 分數高）。"""
    return -_daily_returns(panel).rolling(20, min_periods=20).std()


def volume_ratio_5over20(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """量比：近 5 日均量 / 過去 20 日均量。"""
    vol = panel["volume"]
    return vol.rolling(5, min_periods=5).mean() / vol.rolling(20, min_periods=20).mean()


def range_pos(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """日內區間位置：(close - low) / (high - low)，當日收盤強弱。"""
    high, low, close = panel["high"], panel["low"], panel["close"]
    span = high - low
    return (close - low).where(span > 0) / span.where(span > 0)


def _market_vol_regime(panel: dict[str, pd.DataFrame]) -> pd.Series:
    """市場波動機制：True = 高波動。

    市場報酬 = 當日橫截面平均報酬；取 20 日滾動標準差，
    與**expanding median**（只用 <= t 的歷史）比較 —— 用全期中位數會偷看未來。
    """
    mkt_ret = _daily_returns(panel).mean(axis=1)
    vol20 = mkt_ret.rolling(20, min_periods=20).std()
    med = vol20.expanding(min_periods=20).median()
    return vol20 > med


def regime_momentum(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Vol Regime Adaptive Momentum（純動量部分，不含過濾）。

    高波動機制 -> 用 5 日動量（訊號新鮮、反應快）
    低波動機制 -> 用 20 日動量（平滑雜訊、抓穩定漂移）
    """
    fast, slow = momentum(panel, 5), momentum(panel, 20)
    is_high = _market_vol_regime(panel)
    mask = pd.DataFrame(
        {c: is_high for c in fast.columns}, index=fast.index
    )[fast.columns]
    return fast.where(mask, slow)


FACTORS: dict[str, Callable[[dict[str, pd.DataFrame]], pd.DataFrame]] = {
    "momentum_5": lambda p: momentum(p, 5),
    "momentum_20": lambda p: momentum(p, 20),
    "momentum_60": lambda p: momentum(p, 60),
    "reversal_5": reversal_5,
    "low_volatility_20": low_volatility_20,
    "volume_ratio_5over20": volume_ratio_5over20,
    "range_pos": range_pos,
    "regime_momentum": regime_momentum,
}

# 每個因子需要哪些欄位。跑之前用 factor_data.usable_factors 檢查覆蓋率，
# 免得像 range_pos 那樣（high/low 在 2026-07 前全 NULL）整段算出一堆 NaN 還不自知。
REQUIRES: dict[str, tuple[str, ...]] = {
    "momentum_5": ("close",),
    "momentum_20": ("close",),
    "momentum_60": ("close",),
    "reversal_5": ("close",),
    "low_volatility_20": ("close",),
    "volume_ratio_5over20": ("volume",),
    "range_pos": ("high", "low", "close"),
    "regime_momentum": ("close",),
}


# --- 組合方式（見 quant-notes/factor/combination.md）---------------------------


def _xs_rank(df: pd.DataFrame) -> pd.DataFrame:
    """逐日橫截面百分位排名（0~1），對離群值穩健。"""
    return df.rank(axis=1, pct=True)


def blend_average(a: pd.DataFrame, b: pd.DataFrame, w: float = 0.5) -> pd.DataFrame:
    """平均組合：兩訊號地位平等，各自貢獻分數。"""
    ra, rb = _xs_rank(a), _xs_rank(b)
    return w * ra + (1 - w) * rb


def blend_filter(main: pd.DataFrame, cond: pd.DataFrame, keep_top: float = 0.5) -> pd.DataFrame:
    """過濾組合：cond 不提供方向，只提供否決權。

    排序完全由 main 決定；cond 橫截面排名未達 keep_top 的當日剔除（設為 NaN）。

    邊界：pct 排名落在 (0, 1]，所以取「嚴格大於 1-keep_top」才是剛好留下前 keep_top。
    """
    rank_main, rank_cond = _xs_rank(main), _xs_rank(cond)
    return rank_main.where(rank_cond > (1.0 - keep_top))
