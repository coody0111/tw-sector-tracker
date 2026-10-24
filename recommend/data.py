"""從 DuckDB 載入「股票×日期」面板（唯讀）。"""
import duckdb
import pandas as pd

DB_PATH = "data/screener.db"
UNIVERSE_PATH = "data/stock_universe.csv"


def load_panel(db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH, start: str | None = None) -> pd.DataFrame:
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
    sh["big_date"] = sh["date"]
    df = px.merge(inst, on=["stock_id", "date"], how="left").merge(fh, on=["stock_id", "date"], how="left")
    df = pd.merge_asof(df.sort_values("date"), sh.sort_values("date"), on="date", by="stock_id",
                       direction="backward", allow_exact_matches=True)
    first = sh.sort_values("date").groupby("stock_id")["total_shares"].first()
    df["total_shares"] = df["total_shares"].fillna(df["stock_id"].map(first))
    uni = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")[["stock_id", "stock_name", "meta_sector"]]
    df = df.merge(uni, on="stock_id", how="inner")
    return df.sort_values(["stock_id", "date"]).reset_index(drop=True)
