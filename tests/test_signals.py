import duckdb
import pandas as pd
from screener.signals import (
    scan_volume_turnover,
    scan_momentum_health,
    scan_consecutive_limit_up,
    scan_bullish_alignment_new_high,
)


def _seed_db(db_path, price_rows, inst_rows=None):
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, close DOUBLE,
            change_pct DOUBLE, volume BIGINT
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?)",
        price_rows,
    )
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT,
            trust_net BIGINT, total_net BIGINT
        )
    """)
    if inst_rows:
        con.executemany("INSERT INTO institutional VALUES (?, ?, ?, ?, ?)", inst_rows)
    con.close()


def test_skips_stock_with_insufficient_history(tmp_path):
    """只有錨點日 + 今天兩筆資料時，量倍數統計上沒有意義，不該產生訊號。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("1101", "2025-06-02", 100.0, 0.0, 1000),   # 錨點日，跟今天差很多天
        ("1101", "2026-07-01", 110.0, 5.0, 50000),  # 前日漲停（change_pct 用不到，看今天跟昨天關係）
    ]
    _seed_db(db_path, rows)

    results = scan_volume_turnover("2026-07-01", db_path=str(db_path))

    assert results == []


def test_detects_signal_with_sufficient_history(tmp_path):
    """有足夠歷史資料（>=20 筆）時，符合三條件應該正常產生訊號。"""
    db_path = tmp_path / "test.db"
    rows = []
    # 25 個交易日的平緩歷史，量都在 1000 左右
    dates = [f"2026-05-{d:02d}" for d in range(1, 26)]
    for d in dates:
        rows.append(("2330", d, 100.0, 0.5, 1000))
    # 前一天漲停
    rows.append(("2330", "2026-06-30", 110.0, 9.9, 1200))
    # 今天：收跌、不鎖跌停、爆量
    rows.append(("2330", "2026-07-01", 108.0, -1.8, 50000))
    _seed_db(db_path, rows)

    results = scan_volume_turnover("2026-07-01", db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["vol_window_days"] >= 20


def test_scan_momentum_health_classifies_ma_alignment(tmp_path):
    """65 筆穩定上升的收盤價，應判斷為多頭排列，且不觸發出場三原則、有進場確認。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for d in dates:
        close += 0.5
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, 0.5, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["ma_alignment"] == "多頭排列"
    assert results[0]["exit_3_rule_triggered"] is False
    assert results[0]["entry_confirmed"] is True


def test_scan_momentum_health_ma_alignment_ignores_ma20(tmp_path):
    """MA20 暫時卡在 MA10 之上（若誤把 MA20 也塞進判斷式，這裡會被誤判「糾結」），但
    close>MA5>MA10>MA60 三線本身成立，應正確判斷「多頭排列」（統整 spec §1.1 收斂修正的回歸測試）。
    手算：MA60=109.22, MA20=127.65, MA10=125.3, MA5=125.6, close=128
    （MA10 125.3 < MA20 127.65——若程式碼還在用四線判斷會判「糾結」，這裡要驗證不是）。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=70, freq="D")
    rows = []
    closes = (
        [100.0] * 50            # index0-49：長期打底，撐住 MA60 基期
        + [130.0] * 10           # index50-59：只落在 MA60/MA20 窗口內，不在 MA10 窗口內
        + [125.0] * 9            # index60-68：落在 MA60/MA20/MA10 窗口內
        + [128.0]                # index69（今天）
    )
    for d, c in zip(dates, closes):
        rows.append(("2330", d.strftime("%Y-%m-%d"), c, 0.1, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["ma10"] < results[0]["ma20"], "確認測試場景本身真的建構出 MA10<MA20 的情境"
    assert results[0]["ma_alignment"] == "多頭排列", \
        "close>MA5>MA10>MA60 三線成立即應判多頭排列，不該因為 MA20 的相對位置被誤判成糾結"


def test_scan_momentum_health_triggers_exit_3_rule(tmp_path):
    """站穩均線一段時間後，最後一天跌破5MA+5MA下彎+重挫長黑，三條件同時成立才觸發。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for i, d in enumerate(dates):
        if i < 64:
            close += 0.5
            pct = 0.5
        else:
            close = close * (1 - 0.05)
            pct = -5.0
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["exit_3_rule_triggered"] is True


def test_scan_momentum_health_skips_insufficient_history(tmp_path):
    """歷史資料 < 65 筆時，直接跳過不產生結果。"""
    db_path = tmp_path / "test.db"
    rows = [("2330", f"2026-01-{d:02d}", 100.0 + d, 0.1, 1000) for d in range(1, 30)]
    _seed_db(db_path, rows)

    results = scan_momentum_health("2026-01-29", db_path=str(db_path))

    assert results == []


def test_scan_momentum_health_exit_3_rule_needs_all_three_conditions(tmp_path):
    """跌破MA5 + MA5下彎兩個條件都滿足，但跌幅沒到 -4% 門檻時，不該觸發出場三原則。
    這個測試專門隔離驗證「重挫長黑」這個條件本身，避免像之前 scan_volume_turnover
    的測試一樣，被其他條件先擋下、沒有真正測到目標條件。
    （手算驗證：-1.5% 不夠讓 MA5 真的下彎——5日窗口往前推一天掉出去的那筆比今天跌完
    還低，MA5 反而還會微升；改用 -2.5% 才確實讓 MA5_today(130.74) < MA5_yday(131.0)。）
    """
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 100.0
    for i, d in enumerate(dates):
        if i < 64:
            close += 0.5
            pct = 0.5
        else:
            close = close * (1 - 0.025)  # 跌 -2.5%，跌破MA5+MA5下彎都成立，但沒到 -4% 門檻
            pct = -2.5
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert len(results) == 1
    # 跌破MA5、MA5下彎這兩個條件確實成立，用來確認不是因為前兩個條件沒觸發才導致 False
    assert results[0]["close"] < results[0]["ma5"]
    assert results[0]["ma5_slope_down"] is True
    # 但第三條件（重挫長黑 <= -4%）沒有滿足，所以整體不該觸發
    assert results[0]["exit_3_rule_triggered"] is False


def test_scan_momentum_health_computes_relative_strength(tmp_path):
    """個股 5 日漲 8%、族群平均漲 3%（族群另一檔跌 2%）時，rs_score 應為 5.0。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試強股,sectorA\n"
        "1102,測試弱股,sectorA\n",
        encoding="utf-8",
    )

    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    for sid, last_day_pct in [("1101", 8.0), ("1102", -2.0)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.0 if i < 64 else last_day_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"),
        db_path=str(db_path),
        universe_path=str(universe_path),
    )

    strong = next(r for r in results if r["stock_id"] == "1101")
    weak = next(r for r in results if r["stock_id"] == "1102")
    assert strong["rs_score"] == 5.0
    assert strong["rs_rank_pct"] == 1.0
    assert weak["rs_rank_pct"] < strong["rs_rank_pct"]


def test_scan_momentum_health_rs_score_ignores_future_data(tmp_path):
    """rs_score 不該被 trade_date 之後才發生的資料污染（no-lookahead）。用跟
    test_scan_momentum_health_computes_relative_strength 完全同一組歷史資料（65天，
    trade_date=第65天，1101 最後一天+8%、1102 最後一天-2%，rs_score 應為 5.0），
    但額外在 trade_date 之後追加 4 天「未來」的族群齊漲（兩檔都+7.5%/天），
    傳的 trade_date 仍是原本第65天不變——rs_score 應該還是 5.0，不能因為 DB 裡
    多了未來資料就被算成別的數字。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試強股,sectorA\n"
        "1102,測試弱股,sectorA\n",
        encoding="utf-8",
    )

    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    future_dates = pd.date_range("2026-01-01", periods=4, freq="D") + pd.Timedelta(days=65)
    rows = []
    for sid, last_day_pct in [("1101", 8.0), ("1102", -2.0)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.0 if i < 64 else last_day_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
        # trade_date 之後：兩檔齊漲同樣幅度，如果 look-ahead 洩漏進來會把 rs_score 帶偏
        for d in future_dates:
            close = close * (1 + 7.5 / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, 7.5, 1000))
    _seed_db(db_path, rows)

    trade_date = dates[-1].strftime("%Y-%m-%d")
    results = scan_momentum_health(trade_date, db_path=str(db_path), universe_path=str(universe_path))

    strong = next(r for r in results if r["stock_id"] == "1101")
    weak = next(r for r in results if r["stock_id"] == "1102")
    assert strong["rs_score"] == 5.0
    assert weak["rs_score"] == -5.0


def test_scan_momentum_health_computes_market_relative_strength(tmp_path):
    """rs_market_score = 個股5日報酬 − universe 等權平均5日報酬。1101 最後5天每天+2%
    （cum5≈10.41%），1102 最後5天每天0%（cum5=0%），market（兩檔等權平均，每天
    (2.0+0.0)/2=1.0%，cum5≈5.10%）。1101 的 rs_market_score = 10.41 − 5.10 = 5.31。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試股A,sectorA\n"
        "1102,測試股B,sectorB\n",
        encoding="utf-8",
    )

    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    for sid, last5_pct in [("1101", 2.0), ("1102", 0.0)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.0 if i < 60 else last5_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"),
        db_path=str(db_path),
        universe_path=str(universe_path),
    )

    strong = next(r for r in results if r["stock_id"] == "1101")
    assert strong["rs_market_score"] == 5.31


def test_scan_momentum_health_tier_exit_signal_overrides_alignment(tmp_path):
    """空頭排列 + 出場三原則觸發 → 超弱，即使沒有額外 rs_score 資料也一樣判定。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    close = 200.0
    for i, d in enumerate(dates):
        if i < 64:
            close -= 0.5
            pct = -0.25
        else:
            close = close * (1 - 0.06)
            pct = -6.0
        rows.append(("2330", d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))

    assert results[0]["ma_alignment"] == "空頭排列"
    assert results[0]["exit_3_rule_triggered"] is True
    assert results[0]["strength_tier"] == "超弱"


def test_scan_momentum_health_tier_bullish_but_weak_rs_is_weak(tmp_path):
    """多頭排列，但族群內相對強弱排名落後（<50%），應歸類為弱，不是強。
    族群內放 3 檔（1101/1102/1103）而非 2 檔——只有 2 檔時 pandas pct rank 最差也只會是
    1/2=0.5，剛好卡在「強」的門檻（rank>=0.5）上，不會產生真正 <0.5 的情境。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "1101,測試強股,sectorA\n"
        "1102,測試弱股,sectorA\n"
        "1103,測試中段股,sectorA\n",
        encoding="utf-8",
    )
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    rows = []
    # 三檔都緩步上漲維持多頭排列，但最後一天漲幅差很多，1102 明顯墊底
    for sid, last_day_pct in [("1101", 8.0), ("1102", 0.1), ("1103", 3.0)]:
        close = 100.0
        for i, d in enumerate(dates):
            pct = 0.3 if i < 64 else last_day_pct
            close = close * (1 + pct / 100)
            rows.append((sid, d.strftime("%Y-%m-%d"), close, pct, 1000))
    _seed_db(db_path, rows)

    results = scan_momentum_health(
        dates[-1].strftime("%Y-%m-%d"),
        db_path=str(db_path),
        universe_path=str(universe_path),
    )

    weak = next(r for r in results if r["stock_id"] == "1102")
    assert weak["ma_alignment"] == "多頭排列"
    assert weak["rs_rank_pct"] < 0.5
    assert weak["strength_tier"] == "弱"


def test_scan_consecutive_limit_up_counts_streak(tmp_path):
    """連續 3 天漲停（含今天）應算出 limit_up_streak == 3。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2330", "2026-07-10", 100.0, 1.0, 5000),
        ("2330", "2026-07-11", 101.0, 1.0, 5000),
        ("2330", "2026-07-12", 111.1, 9.8, 4000),
        ("2330", "2026-07-13", 122.2, 10.0, 3000),
        ("2330", "2026-07-14", 134.4, 9.9, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert len(results) == 1
    assert results[0]["stock_id"] == "2330"
    assert results[0]["limit_up_streak"] == 3


def test_scan_consecutive_limit_up_accepts_custom_universe_path(tmp_path):
    """跟姊妹函式 scan_momentum_health/scan_bullish_alignment_new_high 一致，應該能注入
    自訂 universe_path（不吃預設的 data/stock_universe.csv），才能在隔離環境測試
    stock_name/meta_sector 有沒有正確帶出來。"""
    db_path = tmp_path / "test.db"
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "stock_id,stock_name,meta_sector\n"
        "2330,測試龍頭股,sectorA\n",
        encoding="utf-8",
    )
    rows = [
        ("2330", "2026-07-13", 122.2, 10.0, 3000),
        ("2330", "2026-07-14", 134.4, 9.9, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path), universe_path=str(universe_path))

    assert len(results) == 1
    assert results[0]["stock_name"] == "測試龍頭股"
    assert results[0]["meta_sector"] == "sectorA"


def test_scan_consecutive_limit_up_excludes_stock_without_todays_limit(tmp_path):
    """今天沒漲停的股票不該出現在結果裡（不是 limit_up_streak==0 混在結果裡）。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2330", "2026-07-13", 100.0, 9.8, 3000),
        ("2330", "2026-07-14", 110.0, 10.0, 2000),   # 今天漲停 → 應出現
        ("2317", "2026-07-13", 50.0, 1.0, 3000),
        ("2317", "2026-07-14", 50.5, 1.0, 3000),      # 今天沒漲停 → 不該出現
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    ids = [r["stock_id"] for r in results]
    assert "2330" in ids
    assert "2317" not in ids


def test_scan_consecutive_limit_up_sorts_by_streak_descending(tmp_path):
    """連板數高的排前面。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("AAAA", "2026-07-12", 100.0, 9.8, 3000),
        ("AAAA", "2026-07-13", 110.0, 10.0, 2000),
        ("AAAA", "2026-07-14", 121.0, 10.0, 1000),   # streak=3
        ("BBBB", "2026-07-14", 50.0, 10.0, 3000),     # streak=1
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert [r["stock_id"] for r in results] == ["AAAA", "BBBB"]


def test_scan_consecutive_limit_up_flags_volume_declining_streak(tmp_path):
    """連板期間成交量逐日遞減（惜售、鎖更死）→ volume_declining_streak True；
    中間有一天量增 → False。"""
    db_path = tmp_path / "test.db"
    rows = [
        # AAAA: 量逐日遞減（3000 → 2000 → 1000）
        ("AAAA", "2026-07-12", 100.0, 9.8, 3000),
        ("AAAA", "2026-07-13", 110.0, 10.0, 2000),
        ("AAAA", "2026-07-14", 121.0, 10.0, 1000),
        # BBBB: 第三天量反增（1000 → 1000 → 5000）
        ("BBBB", "2026-07-12", 50.0, 9.8, 1000),
        ("BBBB", "2026-07-13", 55.0, 10.0, 1000),
        ("BBBB", "2026-07-14", 60.5, 10.0, 5000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    a = next(r for r in results if r["stock_id"] == "AAAA")
    b = next(r for r in results if r["stock_id"] == "BBBB")
    assert a["volume_declining_streak"] is True
    assert b["volume_declining_streak"] is False


def test_scan_consecutive_limit_up_single_day_streak_has_none_volume_trend(tmp_path):
    """只有 1 天漲停，無法判斷「逐日遞減」趨勢，應為 None（不是 False）。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("CCCC", "2026-07-13", 50.0, 1.0, 3000),
        ("CCCC", "2026-07-14", 55.0, 10.0, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert results[0]["limit_up_streak"] == 1
    assert results[0]["volume_declining_streak"] is None


def test_scan_bullish_alignment_new_high_filters_correctly(tmp_path):
    """三種情境同時測試，避免像 detect_breakout_confirm 早期版本那樣只驗證單一條件：
    (1) 多頭排列 + 創新高 → 命中
    (2) 多頭排列，但今日收盤不是窗口內最高（前面有更高的收盤）→ 排除
    (3) 創新高（單日急拉），但不是多頭排列（下跌趨勢中 MA10 < MA60）→ 排除
    """
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=60, freq="D")

    rows = []

    # 1101：60 天穩定上升（close = 100+i），今日收盤是窗口內最高，且多頭排列
    close_1101 = [100 + i for i in range(60)]
    for d, c in zip(dates, close_1101):
        rows.append(("1101", d.strftime("%Y-%m-%d"), float(c), 0.5, 1000))

    # 1102：前 58 天同樣上升到 157（i=57），最後兩天回檔到 155/156——
    # 今日(156)仍然是多頭排列（MA5/MA10/MA60 都還在下方），但不是窗口最高（157 更高）
    close_1102 = [100 + i for i in range(58)] + [155, 156]
    for d, c in zip(dates, close_1102):
        rows.append(("1102", d.strftime("%Y-%m-%d"), float(c), 0.1, 1000))

    # 1103：59 天緩跌（200 → 約101），今日單日急拉到 250——
    # 250 是窗口內最高（創新高成立），但 MA10 仍低於 MA60（下跌趨勢均線還沒排列成多頭）
    close_1103 = [round(200 - i * 1.7, 2) for i in range(59)] + [250.0]
    for d, c in zip(dates, close_1103):
        rows.append(("1103", d.strftime("%Y-%m-%d"), float(c), 5.0, 1000))

    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high(dates[-1].strftime("%Y-%m-%d"), db_path=str(db_path))
    ids = [r["stock_id"] for r in results]

    assert "1101" in ids, "多頭排列 + 創新高都成立，應命中"
    assert "1102" not in ids, "多頭排列成立，但今日非窗口內最高收盤，不該命中"
    assert "1103" not in ids, "今日創新高，但均線不是多頭排列（下跌趨勢中的單日急拉），不該命中"

    hit = next(r for r in results if r["stock_id"] == "1101")
    assert hit["ma5"] == 157.0
    assert hit["ma10"] == 154.5
    assert hit["ma60"] == 129.5
    assert hit["lookback_days"] == 60


def test_scan_bullish_alignment_new_high_skips_insufficient_history(tmp_path):
    """歷史資料 < max(60, lookback_days) 筆時，直接跳過不產生結果，不 crash。"""
    db_path = tmp_path / "test.db"
    rows = [("1101", f"2026-01-{d:02d}", 100.0 + d, 0.1, 1000) for d in range(1, 30)]
    _seed_db(db_path, rows)

    results = scan_bullish_alignment_new_high("2026-01-29", db_path=str(db_path))

    assert results == []


def test_scan_bullish_alignment_new_high_lookback_days_changes_boundary(tmp_path):
    """lookback_days 決定「創新高」的比較窗口：120 天前有過一次高點(300)，
    60 天窗口看不到那次高點 → 判定創新高；120 天窗口看得到 → 判定非創新高。
    同一組資料、同一天，只改 lookback_days，結果應該不同。"""
    db_path = tmp_path / "test.db"
    dates = pd.date_range("2026-01-01", periods=120, freq="D")

    ancient = [110.0] * 60
    ancient[30] = 300.0  # 120 天前的舊高點，只有 lookback=120 才看得到
    recent = [round(150 + i * (205 - 150) / 59, 2) for i in range(60)]  # 近60天穩定上升到205
    closes = ancient + recent
    rows = [("1101", d.strftime("%Y-%m-%d"), c, 0.1, 1000) for d, c in zip(dates, closes)]
    _seed_db(db_path, rows)

    today_str = dates[-1].strftime("%Y-%m-%d")
    results_60 = scan_bullish_alignment_new_high(today_str, lookback_days=60, db_path=str(db_path))
    results_120 = scan_bullish_alignment_new_high(today_str, lookback_days=120, db_path=str(db_path))

    assert "1101" in [r["stock_id"] for r in results_60], "60天窗口看不到120天前的300高點，應判定創新高"
    assert "1101" not in [r["stock_id"] for r in results_120], "120天窗口看得到那次300高點，不該判定創新高"
