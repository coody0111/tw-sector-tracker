"""策略介面（規格 §7.0）：每條策略各自的進場條件與型態；出場規則見 recommend.exits。"""
from typing import Protocol

import pandas as pd

SIGNAL_COLUMNS = ["stock_id", "date", "strategy", "type", "routes", "n_routes"]


class Strategy(Protocol):
    name: str

    def scan(self, features: pd.DataFrame) -> pd.DataFrame:
        """輸入特徵面板，回傳符合的訊號（欄位見 SIGNAL_COLUMNS）。"""
        ...
