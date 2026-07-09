# tests/test_institutional.py
import duckdb

from screener.institutional import scan_institutional


def _make_inst_table(con):
    con.execute("""CREATE TABLE institutional (
        stock_id VARCHAR, date DATE, foreign_net BIGINT, trust_net BIGINT,
        dealer_net BIGINT, total_net BIGINT, PRIMARY KEY(stock_id, date))""")
    # scan_institutional 還會查 daily_prices（行情）、name/meta/exchange map（讀 universe csv），
    # 這些查不到不會 crash（回空/預設值），不影響本測試要驗的「哪些股票入選」。
    con.execute("""CREATE TABLE daily_prices (stock_id VARCHAR, date DATE, close DOUBLE, change_pct DOUBLE)""")


def _seed_days(con, sid, dates_vals):
    """dates_vals: list of (date, foreign_net) — trust/dealer/total 用同值簡化。"""
    for d, fn in dates_vals:
        con.execute("INSERT INTO institutional VALUES (?, ?, ?, ?, ?, ?)",
                    [sid, d, fn, fn, 0, fn * 2])


def test_scan_institutional_includes_both_exchanges_when_dates_desync(tmp_path):
    """真實情境（2026-07-08）：TPEx 三大法人已發布 07-08、TWSE 還停在 07-07。
    scan_institutional 用整表 MAX(date)=07-08 當錨點時，會把最新只到 07-07 的 TWSE 股
    全部漏掉（今天實測 917 檔全是 TPEx、0 檔 TWSE）。修正後兩邊都要入選。"""
    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    _make_inst_table(con)
    # TWSE 股 2330：最新只到 07-07（每天外資買超，連買）
    _seed_days(con, "2330", [("2026-07-03", 1000), ("2026-07-04", 1000),
                             ("2026-07-07", 1000)])
    # TPEx 股 6488：最新到 07-08
    _seed_days(con, "6488", [("2026-07-03", 500), ("2026-07-04", 500),
                             ("2026-07-07", 500), ("2026-07-08", 500)])
    con.close()

    res = scan_institutional("2026-07-08", db_path=db_path, lookback=40)
    ids = {r["stock_id"] for r in res}
    assert "6488" in ids, "TPEx 股（最新 07-08）應入選"
    assert "2330" in ids, "TWSE 股（最新 07-07）不該因整表錨在 07-08 就被漏掉"


def test_scan_institutional_excludes_stale_stock(tmp_path):
    """停牌/下市股（最新資料是好幾天前，不在最近兩個交易日內）不該用陳舊資料入選。"""
    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    _make_inst_table(con)
    _seed_days(con, "6488", [("2026-07-07", 500), ("2026-07-08", 500)])  # 最新 07-08
    _seed_days(con, "0000", [("2026-06-20", 900), ("2026-06-21", 900)])  # 最新停在 6 月，很舊
    con.close()

    res = scan_institutional("2026-07-08", db_path=db_path, lookback=40)
    ids = {r["stock_id"] for r in res}
    assert "6488" in ids
    assert "0000" not in ids, "最新資料太舊的股票不該用陳舊資料入選"


def test_scan_institutional_does_not_drop_high_number_stocks(tmp_path):
    """回歸（#1）：舊版用全域 `LIMIT lookback*2000` + `ORDER BY stock_id`，低號股會把配額
    吃滿、高號股整批被截掉。用 lookback=1（LIMIT 上限 = 2000）配 >2000 檔股票、每檔多天歷史，
    重現「配額被低號股 × 多天歷史吃光、高號股消失」。per-stock QUALIFY 修正後高號股不該被漏。"""
    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    _make_inst_table(con)
    # 3000 檔股票，每檔 3 天歷史 = 9000 列。舊版 lookback=1 → LIMIT 2000，ORDER BY stock_id
    # 會被最低號的 ~667 檔（每檔 3 列）吃光，最高號股（99xx）完全消失。
    rows = []
    for i in range(3000):
        sid = f"{1000 + i}"  # 1000..3999，字典序遞增
        for d in ("2026-07-06", "2026-07-07", "2026-07-08"):
            rows.append((sid, d, 500, 500, 0, 1000))
    con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.close()

    res = scan_institutional("2026-07-08", db_path=db_path, lookback=1)
    ids = {r["stock_id"] for r in res}
    # 最高號那檔（3999）必須在——舊版 LIMIT 2000 會把它截掉
    assert "3999" in ids, "最高號股票不該因全域 LIMIT 被截掉（#1 漏股回歸）"
    assert len(ids) == 3000, f"3000 檔應全部入選，實際 {len(ids)}（舊版只會有約 667 檔）"
