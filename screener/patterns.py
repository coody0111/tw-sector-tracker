"""
量價形態掃描器。
"""
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

_DB_PATH = "data/screener.db"
_UNIVERSE_PATH = "data/stock_universe.csv"

# Score 門檻常數
_VOL_UP   = 1.5
_VOL_DOWN = 0.7
_PRICE_UP   =  0.5   # %
_PRICE_DOWN = -0.5   # %

# 形態偵測常數
_DBL_PRICE_DIFF  = 0.03   # 雙底/頂兩端差距 < 3%
_DBL_BOUNCE      = 0.05   # 中間反彈/拉回 >= 5%
_DBL_VOL_CONFIRM = 1.2    # 突破頸線量確認
_TRI_VOL_CONFIRM = 1.3    # 三角突破量確認
_BRK_VOL_CONFIRM = 1.5    # 60日突破量確認
_BOX_RANGE       = 0.08   # 箱型整理最大振幅 8%


def _calc_streak(series: pd.Series) -> int:
    """計算末端連買(正)或連賣(負)天數。"""
    if series.empty:
        return 0
    values = series.tolist()
    if values[-1] > 0:
        streak = 0
        for v in reversed(values):
            if v > 0:
                streak += 1
            else:
                break
        return streak
    elif values[-1] < 0:
        streak = 0
        for v in reversed(values):
            if v < 0:
                streak += 1
            else:
                break
        return -streak
    return 0


def _calc_vol_price_score(close: pd.Series, volume: pd.Series) -> int:
    """量價得分：量增價漲+2、量增/減價跌-2、量減價漲-1。"""
    if len(close) < 21:
        return 0
    vol_ma20 = volume.iloc[-21:-1].mean()
    if vol_ma20 == 0:
        return 0
    vol_ratio = volume.iloc[-1] / vol_ma20
    change_pct = (close.iloc[-1] / close.iloc[-2] - 1) * 100

    vol_up   = vol_ratio > _VOL_UP
    vol_down = vol_ratio < _VOL_DOWN
    price_up   = change_pct > _PRICE_UP
    price_down = change_pct < _PRICE_DOWN

    if vol_up and price_up:
        return 2
    if (vol_up or vol_down) and price_down:
        return -2
    if vol_down and price_up:
        return -1   # 背離
    return 0


def _calc_chips_score(inst_df: pd.DataFrame) -> int:
    """法人連買/連賣得分（外資上限±5，投信上限±3）。"""
    if inst_df.empty:
        return 0
    score = 0
    if 'foreign_net' in inst_df.columns:
        streak = _calc_streak(inst_df['foreign_net'])
        score += max(-5, min(5, streak))
    if 'trust_net' in inst_df.columns:
        streak = _calc_streak(inst_df['trust_net'])
        score += max(-3, min(3, streak))
    return score
