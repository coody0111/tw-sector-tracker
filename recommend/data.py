"""從 DuckDB 載入「股票×日期」面板（唯讀）。"""
import duckdb
import numpy as np
import pandas as pd

DB_PATH = "data/screener.db"
UNIVERSE_PATH = "data/stock_universe.csv"
EVENTS_PATH = "data/corporate_events.csv"   # scrapers/twse_events.py：上市三張表＋上櫃除權息表


def event_factors(events: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    """每筆除權息／減資／變更面額事件的還原因子＝參考價 ÷ 事件前收盤（規格 §11 報酬用還原價）。
    前收缺（TWT84U 補的那幾筆）用行情裡事件日前一筆收盤。回傳 stock_id, date, factor。"""
    ev = events[["stock_id", "date", "pre_close", "ref"]].copy()
    ev["date"] = pd.to_datetime(ev["date"]).astype("datetime64[ns]")
    need = ev["pre_close"].isna()
    if need.any():
        prices = px[["stock_id", "date", "close"]].astype({"date": "datetime64[ns]"}).sort_values("date")
        prev = pd.merge_asof(ev[need].reset_index().sort_values("date"), prices, on="date", by="stock_id",
                             direction="backward", allow_exact_matches=False)     # 事件日「之前」最後一筆收盤
        ev.loc[prev["index"], "pre_close"] = prev["close"].to_numpy()
    ev["factor"] = ev["ref"] / ev["pre_close"]
    ev = ev[np.isfinite(ev["factor"]) & (ev["factor"] > 0)]
    return ev.drop_duplicates(["stock_id", "date"], keep="last")[["stock_id", "date", "factor"]]


def adj_multiplier(px: pd.DataFrame, factors: pd.DataFrame) -> pd.Series:
    """還原乘數：某天價格 × 這天之後所有事件因子的連乘＝以最新價位為基準的還原價（事件當天不乘自己）。"""
    out = np.ones(len(px))
    pos = px.groupby("stock_id").indices
    for sid, e in factors.sort_values("date").groupby("stock_id"):
        if sid not in pos:
            continue
        idx = pos[sid]
        suffix = np.append(np.cumprod(e["factor"].to_numpy()[::-1])[::-1], 1.0)
        k = np.searchsorted(e["date"].to_numpy("datetime64[ns]"), px["date"].to_numpy("datetime64[ns]")[idx], side="right")
        out[idx] = suffix[k]
    return pd.Series(out, index=px.index)


def load_panel(db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH, start: str | None = None,
               events_path: str | None = None) -> pd.DataFrame:
    """行情＋法人＋外資持股＋集保（asof，含資料日當天）＋股票池。
    big_date 是對到的那份集保資料日；total_shares 在集保資料之前用該股最早一筆往回補（規格 §3）。"""
    where = "WHERE date >= ?" if start else ""
    args = [start] if start else []
    try:
        con = duckdb.connect(db_path, read_only=True)
    except duckdb.ConnectionException:
        # 同一個程序已有讀寫連線時不能再開唯讀（DuckDB 限制），改用一般連線；這裡只做 SELECT
        con = duckdb.connect(db_path)
    try:
        px = con.execute(f"SELECT stock_id, date, open, high, low, close, volume, change FROM daily_prices {where}", args).df()
        inst = con.execute(f"SELECT stock_id, date, foreign_net, trust_net FROM institutional {where}", args).df()
        fh = con.execute(f"SELECT stock_id, date, foreign_pct FROM foreign_holdings {where}", args).df()
        sh = con.execute("SELECT stock_id, date, lv12_15_pct AS big_pct, total_shares FROM shareholder "
                         "WHERE total_shares > 0").df()
    finally:
        con.close()
    for t in (px, inst, fh, sh):
        t["date"] = pd.to_datetime(t["date"])
    px = px.reset_index(drop=True)
    try:
        events = pd.read_csv(events_path or EVENTS_PATH, dtype={"stock_id": str})
        px["adj"] = adj_multiplier(px, event_factors(events, px))
    except FileNotFoundError:
        px["adj"] = 1.0                                   # 沒有事件表：還原價＝原始價
    sh["big_date"] = sh["date"]
    df = px.merge(inst, on=["stock_id", "date"], how="left").merge(fh, on=["stock_id", "date"], how="left")
    df = pd.merge_asof(df.sort_values("date"), sh.sort_values("date"), on="date", by="stock_id",
                       direction="backward", allow_exact_matches=True)
    first = sh.sort_values("date").groupby("stock_id")["total_shares"].first()
    df["total_shares"] = df["total_shares"].fillna(df["stock_id"].map(first))
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "stock_name", "meta_sector"]]
    df = df.merge(uni, on="stock_id", how="inner")
    return df.sort_values(["stock_id", "date"]).reset_index(drop=True)
