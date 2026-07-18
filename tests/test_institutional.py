# tests/test_institutional.py
import duckdb
import pytest

from screener.institutional import scan_institutional, _calc_cum_pct, rank_continuation_candidates


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


def test_calc_cum_pct_compounds_not_sums():
    """複利累積漲幅，不是單純加總（長區間會有明顯差異）。"""
    # +10% 三天：1.1^3 - 1 = 33.1%，不是 30%
    assert _calc_cum_pct([10.0, 10.0, 10.0]) == 33.1
    assert _calc_cum_pct([]) == 0.0
    assert _calc_cum_pct([None, 5.0, None]) == 5.0  # None 值跳過，不當 0 相乘


def test_scan_institutional_price_cum_pct_reflects_window(tmp_path):
    """price_cum_pct 應該是該股 price_window 天內的複利累積漲幅，即使中間有下跌日
    （百容案例：兩週大漲但中間有拉回，不能用『連續上漲天數』抓，要用累積漲幅）。"""
    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    _make_inst_table(con)
    _seed_days(con, "2483", [("2026-07-06", 1000), ("2026-07-07", 1000), ("2026-07-09", 1000)])
    # 股價：+8%, -2%, +6% → 複利 1.08*0.98*1.06 - 1 = 12.1904% ≈ 12.19（中間有一天下跌，不是連漲）
    con.execute("""INSERT INTO daily_prices VALUES
        ('2483', '2026-07-06', 70.0, 8.0),
        ('2483', '2026-07-07', 68.6, -2.0),
        ('2483', '2026-07-09', 72.7, 6.0)""")
    con.close()

    res = scan_institutional("2026-07-09", db_path=db_path, lookback=40, price_window=3)
    row = next(r for r in res if r["stock_id"] == "2483")
    assert row["price_cum_pct"] == 12.19


def test_scan_institutional_min_price_cum_pct_filters_flat_stocks(tmp_path):
    """外資連買但股價沒反應的股票（可能是被動式資金流入雜訊），min_price_cum_pct 應該濾掉；
    連買且股價確實走強的應該保留——這是回應 Cody『外資連買要搭配股價連續漲勢』的需求。"""
    db_path = str(tmp_path / "t.db")
    con = duckdb.connect(db_path)
    _make_inst_table(con)
    # 兩檔都符合 foreign_streak >= 3
    _seed_days(con, "1111", [("2026-07-06", 1000), ("2026-07-07", 1000), ("2026-07-09", 1000)])
    _seed_days(con, "2483", [("2026-07-06", 1000), ("2026-07-07", 1000), ("2026-07-09", 1000)])
    con.execute("""INSERT INTO daily_prices VALUES
        ('1111', '2026-07-06', 100.0, 0.1),
        ('1111', '2026-07-07', 100.1, 0.1),
        ('1111', '2026-07-09', 100.2, 0.1),
        ('2483', '2026-07-06', 70.0, 8.0),
        ('2483', '2026-07-07', 75.0, 7.0),
        ('2483', '2026-07-09', 80.0, 6.7)""")
    con.close()

    res = scan_institutional(
        "2026-07-09", db_path=db_path, lookback=40, price_window=3,
        foreign_streak=3, min_price_cum_pct=5.0,
    )
    ids = {r["stock_id"] for r in res}
    assert "2483" in ids, "外資連買 + 股價實際走強，應保留"
    assert "1111" not in ids, "外資連買但股價幾乎沒動，應被濾掉（疑似被動式資金流入雜訊）"


# ── rank_continuation_candidates 的 weight_mode 消融測試 ──────────────────
# 背景：debug-tasks.md 桌電待驗發現 foreign/trust_continuation 的排名公式（連買天數
# 排名+10日漲幅排名各占一半）讓「法人連買」跟「價格動能」兩個因子綁在一起，測不出籌碼
# 本身的貢獻——D+1 進場又是在「已經漲完」的隔天才追，很可能是中位數超額全部是負的主因。
# weight_mode 讓回測能把兩個因子拆開測，不改動 blended 預設值（chips_generator.py 沿用
# 既有呼叫方式不受影響）。
_ABLATION_CANDIDATES = [
    {"stock_id": "A", "foreign_streak": 10, "price_cum_pct": 1.0},
    {"stock_id": "B", "foreign_streak": 8, "price_cum_pct": 20.0},
    {"stock_id": "C", "foreign_streak": 1, "price_cum_pct": 10.0},
]


def test_rank_continuation_candidates_default_blends_streak_and_price():
    """不傳 weight_mode（或明確傳 'blended'）維持既有 50/50 混合排名，不能因為新增
    weight_mode 參數就悄悄改掉 chips_generator.py 現有呼叫方式的行為。"""
    ranked = rank_continuation_candidates(_ABLATION_CANDIDATES, "foreign_streak")
    assert [r["stock_id"] for r in ranked] == ["B", "A", "C"]


def test_rank_continuation_candidates_streak_only_ignores_price():
    """weight_mode='streak_only' 應該純粹依連買天數排序，不受價格排名影響——
    B/C 的價格排名遠高於 A，但 streak_only 下 A 該排第一。"""
    ranked = rank_continuation_candidates(_ABLATION_CANDIDATES, "foreign_streak", weight_mode="streak_only")
    assert [r["stock_id"] for r in ranked] == ["A", "B", "C"]


def test_rank_continuation_candidates_price_only_ignores_streak():
    """weight_mode='price_only' 應該純粹依價格累積漲幅排序，不受連買天數影響——
    A 的連買天數最高，但 price_only 下 A 該排最後。"""
    ranked = rank_continuation_candidates(_ABLATION_CANDIDATES, "foreign_streak", weight_mode="price_only")
    assert [r["stock_id"] for r in ranked] == ["B", "C", "A"]


def test_rank_continuation_candidates_rejects_invalid_weight_mode():
    with pytest.raises(ValueError):
        rank_continuation_candidates(_ABLATION_CANDIDATES, "foreign_streak", weight_mode="not_a_real_mode")
