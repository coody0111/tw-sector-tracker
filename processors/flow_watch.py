"""
今日籌碼動向 — 純觀察查詢，不做任何評分/排名邏輯以外的加權。
只回傳「今天發生了什麼」的事實（買超金額/與近期均量相比的異常倍數/成交值），
不宣稱任何預測力，跟籌碼頁🟡觀察用分頁、docs/scheduler.md §7.6 的定位一致。
2026-08-26 跟 Cody 用 grilling 確認：這個檔案刻意獨立於 processors/performance.py
之外，避免未來被誤接進任何評分/排名邏輯裡（那正是這個 session 花很多力氣在修正的問題）。
"""
import duckdb
import pandas as pd


def get_flow_watch(
    universe_df: pd.DataFrame | None,
    db_path: str = "data/screener.db",
    trade_date: str | None = None,
    top_n: int = 10,
    avg_window: int = 20,
) -> list[dict]:
    """
    今日籌碼動向：依 trade_date 當日 institutional.total_net（三大法人合計買超）由大到小
    排序取前 top_n（只看買超 > 0，不含賣超），每檔附上：
    - net_buy_lots：今日買超張數（total_net 股數 / 1000）
    - vs_avg20_ratio：今日 total_net 相對「過去 avg_window 個交易日 |total_net| 平均值」
      的倍數，四捨五入到小數 2 位；沒有足夠歷史資料時為 None（不做除以零）
    - turnover：今日成交值（close × volume，四捨五入到整數），查不到價格資料時為 None

    trade_date 為 None 時使用 institutional 表最新日期。回傳 [] 代表當天沒有買超資料。
    """
    con = duckdb.connect(db_path, read_only=True)
    if trade_date is None:
        row = con.execute("SELECT MAX(date) FROM institutional").fetchone()
        trade_date = str(row[0])[:10] if row and row[0] else None
    if not trade_date:
        con.close()
        return []

    today_df = con.execute(
        "SELECT stock_id, total_net FROM institutional "
        "WHERE date = ? AND total_net > 0 ORDER BY total_net DESC LIMIT ?",
        [trade_date, top_n],
    ).df()
    if today_df.empty:
        con.close()
        return []

    stock_ids = today_df["stock_id"].astype(str).tolist()
    placeholders = ",".join("?" for _ in stock_ids)

    hist_df = con.execute(
        f"""
        SELECT stock_id, AVG(ABS(total_net)) AS avg_abs_net
        FROM (
            SELECT stock_id, date, total_net
            FROM institutional
            WHERE stock_id IN ({placeholders}) AND date < ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) <= ?
        )
        GROUP BY stock_id
        """,
        [*stock_ids, trade_date, avg_window],
    ).df()

    price_df = con.execute(
        f"SELECT stock_id, close, volume FROM daily_prices WHERE date = ? AND stock_id IN ({placeholders})",
        [trade_date, *stock_ids],
    ).df()
    con.close()

    avg_map = dict(zip(hist_df["stock_id"].astype(str), hist_df["avg_abs_net"]))
    price_map = {
        str(row.stock_id): (row.close, row.volume) for row in price_df.itertuples()
    }
    name_map = {}
    if universe_df is not None and not universe_df.empty:
        name_map = universe_df.set_index(universe_df["stock_id"].astype(str))[
            ["stock_name", "meta_sector"]
        ].to_dict("index")

    results = []
    for row in today_df.itertuples():
        sid = str(row.stock_id)
        avg_abs = avg_map.get(sid)
        ratio = round(row.total_net / avg_abs, 2) if avg_abs and avg_abs > 0 else None
        close, volume = price_map.get(sid, (None, None))
        turnover = round(close * volume) if close is not None and volume is not None else None
        info = name_map.get(sid, {})
        results.append({
            "stock_id": sid,
            "stock_name": info.get("stock_name", ""),
            "meta_sector": info.get("meta_sector", ""),
            "net_buy_lots": round(row.total_net / 1000),
            "vs_avg20_ratio": ratio,
            "turnover": turnover,
        })
    return results
