"""規格 §3 的特徵定義。回測、頁面、推薦共用；輸入面板（recommend.data.load_panel）回傳新 DataFrame。"""
import numpy as np
import pandas as pd

from recommend.ticks import limit_up_price

MIN_TURNOVER20 = 1e8   # 元；§3 排除低流動性：前 20 日平均成交值 ≥ 1 億（13.14：原 300 張依股價差很多；
                       # 1 億以下的訊號整體虧損，門檻 1～3 億 PF 都 1.96～2.01，2026-10-27 改）
NEW_LISTING_DAYS = 5   # 新上市前 5 個交易日無漲跌幅限制，不判定漲停


def add_price_features(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["stock_id", "date"]).reset_index(drop=True).copy()
    g = df.groupby("stock_id", sort=False)
    # 參考價＝收盤 − 官方漲跌（官方漲跌以參考價為基準）。
    # 漲停一律用原始價判斷（官方漲跌在 2026-10-26 已改成以事件參考價為基準，scrapers/official_prices.py）。
    ref = df["close"] - df["change"].fillna(0)
    limit = ref.map(lambda r: limit_up_price(r) if r > 0 else np.inf)
    seq = g.cumcount()
    df["limit_up"] = (df["close"] >= limit - 1e-6) & (seq >= NEW_LISTING_DAYS)
    flat = (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
    df["one_word"] = df["limit_up"] & flat

    # 量比分母：前 20 個「有成交」日的平均（停牌日不算），不含當日。
    # 先在有成交的列上算 20 日均（含該列），再對每一列取「前一列為止最後一個有成交日」的值。
    traded = df["volume"].where(df["volume"] > 0)
    r20 = traded.groupby(df["stock_id"]).transform(lambda s: s.dropna().rolling(20).mean().reindex(s.index))
    base = r20.groupby(df["stock_id"]).transform(lambda s: s.ffill().shift(1))
    df["vr"] = df["volume"] / base

    # 價格路徑用還原價（規格 §11；2026-10-27）：除權息那天的下跳不能算成跌破、區間或報酬。
    # adj 由 recommend.data.load_panel 依事件表算；沒有（測試資料）就是原始價。顯示價格仍用原始價。
    adj = df["adj"] if "adj" in df.columns else 1.0
    df["aclose"] = df["close"] * adj
    df["aopen"] = df["open"] * adj
    ga = df.groupby("stock_id", sort=False)["aclose"]
    prev_close = ga.shift(1)
    df["hi90"] = ga.transform(lambda s: s.shift(1).rolling(90).max())
    hi20 = ga.transform(lambda s: s.shift(1).rolling(20).max())
    lo20 = ga.transform(lambda s: s.shift(1).rolling(20).min())
    df["rng20"] = hi20 / lo20 - 1
    df["ret20_prev"] = prev_close / ga.shift(21) - 1
    turnover = df["volume"] * 1000 * df["close"]            # 張 × 1000 股 × 收盤
    df["liq"] = turnover.groupby(df["stock_id"]).transform(lambda s: s.shift(1).rolling(20).mean()) >= MIN_TURNOVER20
    return df


def add_chip_features(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["stock_id", "date"]).reset_index(drop=True).copy()
    g = df.groupby("stock_id", sort=False)
    both = df["foreign_net"].fillna(0) + df["trust_net"].fillna(0)
    df["inst5"] = both.groupby(df["stock_id"]).transform(lambda s: s.rolling(5).sum()) / df["total_shares"] * 100
    df["fpct5"] = g["foreign_pct"].transform(lambda s: s - s.shift(5))
    df["trust_days10"] = g["trust_net"].transform(lambda s: (s > 0).astype(float).rolling(10).sum())
    # 集保週變化：以集保資料日分週，每週一個值，跟前一週相減後對回每個交易日（第一週為 NaN）
    weekly = (df.dropna(subset=["big_date"]).groupby(["stock_id", "big_date"])["big_pct"].first()
              .groupby(level="stock_id").diff().rename("big1w").reset_index())
    df = df.merge(weekly, on=["stock_id", "big_date"], how="left")
    for col in ("inst5", "fpct5", "big1w"):
        df[f"{col}_pr"] = df.groupby("date")[col].rank(pct=True)
    return df


def adjusted(df: pd.DataFrame, col: str = "close") -> pd.Series:
    """還原價欄（aclose／aopen）；還沒算 add_price_features 的資料（測試用）就回原始價。"""
    a = "a" + col
    return df[a] if a in df.columns else df[col]
