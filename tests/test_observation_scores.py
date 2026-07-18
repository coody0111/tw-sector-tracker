import pandas as pd
from processors.observation_scores import _calc_price_based_factors
from processors.observation_scores import _calc_chips_factor


def _make_universe(rows):
    """rows: list of (stock_id, meta_sector)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector"])


def _make_price_rows(rows):
    """rows: list of (stock_id, date, change_pct, volume)"""
    return pd.DataFrame(rows, columns=["stock_id", "date", "change_pct", "volume"])


def test_calc_price_based_factors_rs_breadth_continuation():
    """3天資料，2個族群：sectorA（2檔，漲跌互抵，族群均值平盤）、sectorB（1檔，穩定上漲）。
    驗證相對強度（vs universe cum3）、族群廣度（今日上漲比例）、延續性（連漲天數）三個因子。"""
    universe = _make_universe([
        ("A1", "sectorA"), ("A2", "sectorA"), ("B1", "sectorB"),
    ])
    prices = _make_price_rows([
        ("A1", "2026-07-01", 1.0, 1000), ("A1", "2026-07-02", 1.0, 1000), ("A1", "2026-07-03", 1.0, 1000),
        ("A2", "2026-07-01", -1.0, 1000), ("A2", "2026-07-02", -1.0, 1000), ("A2", "2026-07-03", -1.0, 1000),
        ("B1", "2026-07-01", 2.0, 1000), ("B1", "2026-07-02", 2.0, 1000), ("B1", "2026-07-03", 2.0, 1000),
    ])

    result = _calc_price_based_factors(universe, prices)

    # universe cum3 = 每日等權均值(1.0-1.0+2.0)/3=0.667%，複利3天 ≈ +2.01%
    # sectorA cum3 = 每日均值(1.0-1.0)/2=0%，複利3天 = 0%；rs_raw = 0 - 2.01 = -2.01
    # sectorB cum3 = 每日均值2.0%，複利3天 ≈ +6.12%；rs_raw = 6.12 - 2.01 = 4.11
    assert result["sectorA"]["rs_raw"] == -2.01
    assert result["sectorB"]["rs_raw"] == 4.11

    # 今日(07-03)：sectorA上漲1檔(A1)/共2檔=0.5；sectorB上漲1檔(B1)/共1檔=1.0
    assert result["sectorA"]["breadth_raw"] == 0.5
    assert result["sectorB"]["breadth_raw"] == 1.0

    # sectorA今日均值0%（不漲不跌）→ streak=0；sectorB連漲3天（均值每天都是+2.0%）→ streak=3
    assert result["sectorA"]["continuation_raw"] == 0
    assert result["sectorB"]["continuation_raw"] == 3


def test_calc_price_based_factors_volume_raw_needs_six_days():
    """量能參與需要「今日」+「今日之前5個valid交易日」共6天；不足時回None，足夠時算出集合量比。"""
    universe = _make_universe([("C1", "sectorC")])
    # 5天量都是1000（今日之前），第6天(今日)量衝到2500
    rows = [("C1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(25, 30)]
    rows.append(("C1", "2026-06-30", 0.5, 2500))
    prices = _make_price_rows(rows)

    result = _calc_price_based_factors(universe, prices)

    assert result["sectorC"]["volume_raw"] == 2.5  # 2500 / (5*1000/5) = 2500/1000

    # 只給5天（不足6天）驗證回None
    universe2 = _make_universe([("D1", "sectorD")])
    prices2 = _make_price_rows([("D1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(26, 31)])
    result2 = _calc_price_based_factors(universe2, prices2)
    assert result2["sectorD"]["volume_raw"] is None


def test_calc_price_based_factors_handles_nan_without_crash():
    """個股當日change_pct/volume是NULL（例如停牌）時，該股當天被排除在計算之外，不crash、
    不悄悄產生錯誤數字（呼應v2資料層Plan1連續抓到4次的NaN/pd.NA洩漏問題）。"""
    universe = _make_universe([("E1", "sectorE"), ("E2", "sectorE")])
    prices = _make_price_rows([
        ("E1", "2026-07-01", 1.0, 1000), ("E1", "2026-07-02", 1.0, 1000), ("E1", "2026-07-03", None, 1000),
        ("E2", "2026-07-01", 1.0, 1000), ("E2", "2026-07-02", 1.0, 1000), ("E2", "2026-07-03", 1.0, None),
    ])

    result = _calc_price_based_factors(universe, prices)

    # 今日(07-03)：E1的change_pct是NULL被排除，只剩E2(1.0>0)有效 → up=1, total=1 → breadth_raw=1.0
    assert result["sectorE"]["breadth_raw"] == 1.0
    # 沒有crash（測試能跑到這裡就是最基本的驗證）；只有這個族群、universe跟族群均值完全相同，
    # 兩者cum3相同 → rs_raw應該是0.0（今日均值只採計E2一檔，跟universe同一份資料算出來一致）
    assert result["sectorE"]["rs_raw"] == 0.0


def _make_chips_universe(rows):
    """rows: list of (stock_id, meta_sector, exchange)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector", "exchange"])


def _make_inst_rows(rows):
    """rows: list of (stock_id, date, foreign_net)"""
    return pd.DataFrame(rows, columns=["stock_id", "date", "foreign_net"])


def _make_margin_rows(rows):
    """rows: list of (stock_id, date)"""
    return pd.DataFrame(rows, columns=["stock_id", "date"])


def test_calc_chips_factor_no_partial_coverage_when_all_exchanges_present():
    """族群橫跨TWSE+TPEx，今天institutional跟margin兩邊都有兩個交易所的資料 → 不標記partial_coverage。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        ("6488", "2026-07-03", 500),
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("6488", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["partial_coverage"] is False
    assert result["測試族群"]["chips_raw"] == 1.0  # 1101、6488都foreign_net>0 → 2/2買超檔數比例


def test_calc_chips_factor_flags_partial_coverage_when_exchange_missing():
    """族群橫跨TWSE+TPEx，但今天institutional只有TWSE資料（模擬TPEx抓取失敗）→ 標記partial_coverage。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TPEx"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        # 6488(TPEx) 今日沒有institutional資料
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("6488", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["partial_coverage"] is True
    # chips_raw仍算得出來（只是涵蓋不全）：total_stocks只算「今日institutional實際有資料的交易所」
    # 涵蓋的檔數（只有TWSE=1檔），buy_count=1（1101） → 1/1=1.0
    assert result["測試族群"]["chips_raw"] == 1.0


def test_calc_chips_factor_excludes_nan_foreign_net_from_buy_count():
    """個股foreign_net是NULL時（缺值），該股被排除在買超檔數分子之外，不crash。
    分母(total_stocks)是「該族群在有資料的交易所裡的全部檔數」，不是逐股完整度檢查，
    這跟既有calc_meta_chips_signals()的既有行為一致，不是這次新增的bug。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("2330", "測試族群", "TWSE"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-03", 1000),
        ("2330", "2026-07-03", None),  # NULL，模擬缺值
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-03"),
        ("2330", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["chips_raw"] == 0.5  # buy_count=1(僅1101) / total_stocks=2(TWSE全部檔數)


def test_calc_chips_factor_only_uses_latest_date_when_multiple_dates_present():
    """防呆：即使呼叫端不小心傳了超過一天的institutional/margin資料進來，也只該用最新一天，
    不能讓chips_raw悄悄超過1.0（每個因子理論上限），破壞Task3組裝時假設的0~1範圍。"""
    universe = _make_chips_universe([
        ("1101", "測試族群", "TWSE"),
        ("6488", "測試族群", "TWSE"),
    ])
    inst_df = _make_inst_rows([
        ("1101", "2026-07-02", 1000),
        ("6488", "2026-07-02", 500),
        ("1101", "2026-07-03", 1000),
        ("6488", "2026-07-03", 500),
    ])
    margin_df = _make_margin_rows([
        ("1101", "2026-07-02"), ("6488", "2026-07-02"),
        ("1101", "2026-07-03"), ("6488", "2026-07-03"),
    ])

    result = _calc_chips_factor(universe, inst_df, margin_df)

    assert result["測試族群"]["chips_raw"] == 1.0  # 不該是2.0


import duckdb
from processors.observation_scores import calc_meta_observation_scores


def _seed_observation_db(db_path, price_rows, inst_rows=None, margin_rows=None):
    """price_rows: list of (stock_id, date, change_pct, volume)
    inst_rows: list of (stock_id, date, foreign_net)
    margin_rows: list of (stock_id, date)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE, volume BIGINT
        )
    """)
    con.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?)", price_rows)
    con.execute("""
        CREATE TABLE institutional (
            stock_id VARCHAR, date DATE, foreign_net BIGINT
        )
    """)
    if inst_rows:
        con.executemany("INSERT INTO institutional VALUES (?, ?, ?)", inst_rows)
    con.execute("""
        CREATE TABLE margin (
            stock_id VARCHAR, date DATE
        )
    """)
    if margin_rows:
        con.executemany("INSERT INTO margin VALUES (?, ?)", margin_rows)
    con.close()


def _make_full_universe(rows):
    """rows: list of (stock_id, meta_sector, exchange)"""
    return pd.DataFrame(rows, columns=["stock_id", "meta_sector", "exchange"])


def test_calc_meta_observation_scores_end_to_end_all_factors_available():
    """完整6天資料（滿足量能參與需要的天數）+ 齊全籌碼資料，2個族群，5因子全部可算，
    驗證score_coverage=1.0（無缺項）、observation_score落在合理範圍、原始值都有填。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    universe = _make_full_universe([
        ("A1", "sectorA", "TWSE"), ("A2", "sectorA", "TWSE"),
        ("B1", "sectorB", "TWSE"),
    ])

    price_rows = []
    for d in range(25, 30):  # 5天暖身資料
        price_rows.append(("A1", f"2026-06-{d:02d}", 1.0, 1000))
        price_rows.append(("A2", f"2026-06-{d:02d}", -1.0, 1000))
        price_rows.append(("B1", f"2026-06-{d:02d}", 2.0, 1000))
    # 今日(06-30)
    price_rows.append(("A1", "2026-06-30", 1.0, 1000))
    price_rows.append(("A2", "2026-06-30", -1.0, 1000))
    price_rows.append(("B1", "2026-06-30", 2.0, 2500))  # B1今日爆量

    inst_rows = [
        ("A1", "2026-06-30", 1000), ("A2", "2026-06-30", -500), ("B1", "2026-06-30", 800),
    ]
    margin_rows = [("A1", "2026-06-30"), ("A2", "2026-06-30"), ("B1", "2026-06-30")]

    _seed_observation_db(db_path, price_rows, inst_rows, margin_rows)

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert result["sectorA"]["score_coverage"] == 1.0
    assert result["sectorB"]["score_coverage"] == 1.0
    assert result["sectorA"]["observation_score"] is not None
    assert result["sectorB"]["observation_score"] is not None
    # sectorB全面優於sectorA（漲幅更高、量能爆量、外資買超檔數比例更高），分數應該更高
    assert result["sectorB"]["observation_score"] > result["sectorA"]["observation_score"]
    # 原始值都要有填，供UI顯示
    for meta in ("sectorA", "sectorB"):
        assert result[meta]["rs_raw"] is not None
        assert result[meta]["breadth_raw"] is not None
        assert result[meta]["continuation_raw"] is not None


def test_calc_meta_observation_scores_reweights_when_chips_partial_coverage():
    """族群橫跨TWSE+TPEx但今日籌碼資料只有TWSE到齊 → chips因子視為不可用，
    score_coverage應該是1.0-0.10=0.90（不是1.0，也不是誤把chips_raw當0分計入）。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    universe = _make_full_universe([
        ("C1", "sectorC", "TWSE"), ("C2", "sectorC", "TPEx"),
    ])
    price_rows = []
    for d in range(25, 31):
        price_rows.append(("C1", f"2026-06-{d:02d}", 0.5, 1000))
        price_rows.append(("C2", f"2026-06-{d:02d}", 0.5, 1000))
    inst_rows = [("C1", "2026-06-30", 500)]  # C2(TPEx)今日缺institutional資料
    margin_rows = [("C1", "2026-06-30"), ("C2", "2026-06-30")]

    _seed_observation_db(db_path, price_rows, inst_rows, margin_rows)

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert result["sectorC"]["score_coverage"] == 0.90
    assert result["sectorC"]["observation_score"] is not None  # 其餘4因子仍可算


def test_calc_meta_observation_scores_all_factors_unavailable_returns_none_score():
    """族群完全沒有任何天期資料（例如全新上市族群），5因子全不可用時仍要回傳這個族群
    （不能從結果消失），observation_score=None、score_coverage=0。"""
    import tempfile, pathlib
    db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

    # universe裡登記了sectorD，但daily_prices/institutional/margin完全沒有D1的任何資料
    universe = _make_full_universe([
        ("D1", "sectorD", "TWSE"),
        ("E1", "sectorE", "TWSE"),  # sectorE有正常資料，用來讓價格類查詢不會整批提早return {}
    ])
    price_rows = [("E1", f"2026-06-{d:02d}", 0.5, 1000) for d in range(25, 31)]
    _seed_observation_db(db_path, price_rows, inst_rows=[("E1", "2026-06-30", 500)],
                          margin_rows=[("E1", "2026-06-30")])

    result = calc_meta_observation_scores(universe, db_path=str(db_path))

    assert "sectorD" in result
    assert result["sectorD"]["observation_score"] is None
    assert result["sectorD"]["score_coverage"] == 0
