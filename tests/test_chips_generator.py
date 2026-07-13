from datetime import date

from export.chips_generator import _build_section2, _build_section4, _build_section6, _composite_sort, _coverage_flag, _esc, _inst_streak_table, _margin_alert_table, _meta_link, _percentile_ranks, _shareholder_table, _stock_rank_table, generate


def test_esc_escapes_html_special_characters():
    assert _esc('<script>alert(1)</script>') == '&lt;script&gt;alert(1)&lt;/script&gt;'
    assert _esc(None) == ""
    assert _esc("") == ""


def test_meta_link_escapes_malicious_meta_name():
    """族群名稱來自外部資料，title 屬性跟連結文字都要跳脫，不能讓標籤穿透。"""
    malicious = '"><script>alert(1)</script>'
    out = _meta_link(malicious)

    assert '<script>alert(1)</script>' not in out
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in out


def test_stock_rank_table_escapes_malicious_stock_name():
    """股票名稱來自 TWSE/TPEx API 回應；chips.html 會發布到 GitHub Pages，
    不應該讓竄改過的回應內容注入成可執行的標籤。"""
    stocks = [{
        "stock_id": "9999",
        "stock_name": '<script>alert(1)</script>',
        "meta_sector": "測試族群",
        "foreign_net": 100,
        "trust_net": 50,
    }]
    html = _stock_rank_table(stocks, header="外資")

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_generate_returns_false_and_skips_write_when_no_chips_data(tmp_path):
    """meta_chips/stock_chips 兩者皆空時（例如當天資料源抓取失敗），
    generate() 不該寫檔，且要讓呼叫端能區分「真的產生成功」跟「靜默跳過」，
    不能讓 main.py 無條件記成功 log。"""
    output_path = tmp_path / "chips.html"

    result = generate(date(2026, 7, 5), {}, {}, output_path=str(output_path))

    assert result is False
    assert not output_path.exists()


def test_generate_returns_true_and_writes_when_data_present(tmp_path):
    output_path = tmp_path / "chips.html"
    meta_chips = {"測試族群": {"foreign_net_today": 100}}

    result = generate(date(2026, 7, 5), meta_chips, {}, output_path=str(output_path))

    assert result is True
    assert output_path.exists()


def test_coverage_flag_empty_when_not_partial():
    assert _coverage_flag({"partial_coverage": False}) == ""
    assert _coverage_flag({}) == ""


def test_coverage_flag_renders_warning_when_partial():
    out = _coverage_flag({"partial_coverage": True})
    assert "⚠" in out
    assert "部分交易所" in out


def test_generate_shows_coverage_warning_for_partial_meta_in_section1(tmp_path):
    """族群當天 partial_coverage=True（例如 TPEx 抓取失敗）時，Section 1
    連買/連賣表格裡該族群那一列要顯示警示 icon，讓使用者知道數字可能不完整。"""
    output_path = tmp_path / "chips.html"
    meta_chips = {
        "缺資料族群": {"foreign_streak": 3, "foreign_net_today": 100, "trust_net_today": 50,
                     "partial_coverage": True},
        "正常族群": {"foreign_streak": 2, "foreign_net_today": 200, "trust_net_today": 80,
                   "partial_coverage": False},
    }

    generate(date(2026, 7, 5), meta_chips, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")

    # "部分交易所" 只會出現在 _coverage_flag() 的 title 屬性裡（頁面其他地方的 "⚠"
    # 是導覽列/Section 7 固定文字，跟這個警示 icon 無關，所以不能用 "⚠" 計數，
    # 要用這個 _coverage_flag 專屬的字串，才能準確驗證「只有缺資料的族群被標記」。
    # 「缺資料族群」的 foreign_streak=3（正值）同時符合 Section 1（連買族群表）跟
    # Section 5（籌碼集中度表，無條件列出全部 meta_chips）的收錄條件，兩處都該
    # 各自顯示一次警示，所以預期是 2 次，不是 1 次。
    assert html.count("部分交易所") == 2


_SAMPLE_SH_ROW = {
    "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
    "close": 950.0, "change_pct": 1.5,
    "lv12_15_pct": 20.0, "lv12_15_shares": 5_250_000, "share_chg": 250_000,
    "week_chg": 1.0, "streak": 2,
    "company_shares": 1_500_000, "company_chg": 100_000, "company_pledge_pct": 13.33,
    "major_holder_shares": 3_000_000, "major_holder_chg": -50_000, "major_holder_pledge_pct": 0.0,
    "lv12_shares": 1_600_000, "lv12_pct": 6.4, "lv12_chg": 100_000,
    "lv15_shares": 2_900_000, "lv15_pct": 11.6, "lv15_chg": -100_000,
}


def test_shareholder_table_includes_lv12_and_lv15_columns():
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "400張大戶" in html
    assert "1000張大戶" in html
    assert "1,600" in html   # lv12_shares / 1000 = 1,600 張
    assert "2,900" in html   # lv15_shares / 1000 = 2,900 張
    assert "6.4" in html     # lv12_pct
    assert "11.6" in html    # lv15_pct


def test_shareholder_table_handles_missing_lv12_lv15_data():
    """沒有分層資料的股票（舊資料，尚未跑過新版 --update-shareholder）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_SH_ROW)
    row["lv12_shares"] = None
    row["lv12_pct"] = None
    row["lv12_chg"] = None
    row["lv15_shares"] = None
    row["lv15_pct"] = None
    row["lv15_chg"] = None
    html = _shareholder_table([row])
    assert "─" in html


def test_shareholder_table_includes_share_chg_column():
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "大戶張數變化" in html
    assert "250" in html  # 250,000 股 = 250 張


def test_shareholder_table_includes_insider_columns():
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "公司派" in html
    assert "大股東" in html
    assert "13.3" in html  # 質押比例


def test_shareholder_table_handles_missing_insider_data():
    """沒有 insider_holdings 資料的股票（新股/還沒跑過 --update-insider-holdings）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_SH_ROW)
    row["company_shares"] = None
    row["company_chg"] = None
    row["company_pledge_pct"] = None
    row["major_holder_shares"] = None
    row["major_holder_chg"] = None
    row["major_holder_pledge_pct"] = None
    html = _shareholder_table([row])
    assert "─" in html


def test_shareholder_table_shows_5d_7d_10d_14d_columns():
    """近5/7/10/14日累積漲跌幅欄要顯示表頭與數值（紅漲綠跌）。"""
    row = dict(_SAMPLE_SH_ROW)
    row["chg_5d"] = 3.21
    row["chg_7d"] = -1.50
    row["chg_10d"] = 8.00
    row["chg_14d"] = -12.34
    html = _shareholder_table([row])
    assert "近5日" in html and "近7日" in html and "近10日" in html and "近14日" in html
    assert "+3.21%" in html    # 正值紅
    assert "-1.50%" in html    # 負值綠
    assert "+8.00%" in html
    assert "-12.34%" in html


def test_shareholder_table_5d_7d_missing_shows_dash():
    """近5日/近7日缺值（資料不足/新股）顯示「─」，不是 0%，也不報錯。"""
    row = dict(_SAMPLE_SH_ROW)
    row["chg_5d"] = None
    row["chg_7d"] = None
    html = _shareholder_table([row])
    # 表頭有近5日/近7日，但那兩格是「─」而非某個百分比
    assert "近5日" in html
    assert "─" in html


def test_shareholder_table_row_td_count_matches_header():
    """資料列的 <td> 數必須等於表頭 <th> 欄數——防止 _insider_cell/_price_cell 這類
    『回傳完整 <td> 卻又被外層 <td> 包一次』的雙重 <td> 結構 bug（substring 測試抓不到）。"""
    html = _shareholder_table([_SAMPLE_SH_ROW])
    n_th = html.count("<th>")
    body = html.split("</thead>")[1]   # 只數 tbody 的資料列
    n_td = body.count("<td")           # <td 前綴涵蓋 <td> 與 <td ...>
    assert n_td == n_th, f"資料列 <td> 數 {n_td} != 表頭 <th> 數 {n_th}（可能有雙重 <td>）"


def test_inst_streak_table_shows_price_cum_pct():
    """外資/投信持續買進表格新增『10日漲幅』欄（回應 Cody：外資連買要搭配股價連續漲勢
    才有意義，2026-07-09 百容 2483 案例）。正值紅、負值綠，None（缺行情）顯示「─」。"""
    rows = [
        {"stock_id": "2483", "stock_name": "百容", "meta_sector": "載板",
         "close": 80.0, "change_pct": 6.58, "foreign_streak": 3,
         "foreign_net": 76200, "cum_foreign": 230950, "price_cum_pct": 57.39},
        {"stock_id": "9999", "stock_name": "無行情股", "meta_sector": "測試",
         "close": None, "change_pct": None, "foreign_streak": 3,
         "foreign_net": 100, "cum_foreign": 300, "price_cum_pct": None},
    ]
    html = _inst_streak_table(rows, "foreign_streak", "foreign_net", "cum_foreign", "外資")

    assert "10日漲幅" in html
    assert "+57.4%" in html
    assert "─" in html   # price_cum_pct=None 那列


def test_inst_streak_table_row_td_count_matches_header():
    """比照 shareholder_table 的雙重 <td> 回歸測試，這次新增的 10日漲幅欄也要照這個規則檢查。"""
    rows = [{"stock_id": "2483", "stock_name": "百容", "meta_sector": "載板",
             "close": 80.0, "change_pct": 6.58, "foreign_streak": 3,
             "foreign_net": 76200, "cum_foreign": 230950, "price_cum_pct": 57.39}]
    html = _inst_streak_table(rows, "foreign_streak", "foreign_net", "cum_foreign", "外資")
    n_th = html.count("<th>")
    body = html.split("</thead>")[1]
    n_td = body.count("<td")
    assert n_td == n_th, f"資料列 <td> 數 {n_td} != 表頭 <th> 數 {n_th}（可能有雙重 <td>）"


def test_percentile_ranks_handles_ties_and_single_value():
    """同值取平均名次；只有 1 個值時直接給 1.0（沒有比較對象，避免除以 0）。"""
    assert _percentile_ranks([10, 20, 30]) == [0.0, 0.5, 1.0]
    assert _percentile_ranks([5]) == [1.0]
    assert _percentile_ranks([]) == []
    # 兩個並列最小值，平均名次
    ranks = _percentile_ranks([10, 10, 30])
    assert ranks[0] == ranks[1] == 0.25   # 並列第0/1名，平均名次0.5，/(3-1)=0.25
    assert ranks[2] == 1.0


def test_composite_sort_rewards_strength_in_both_factors():
    """回應 Cody：外資連買10天但漲幅普通的股票，不該被完全擠出榜單——Composite Score
    （連買天數 + 漲幅各自轉百分位排名相加）應該讓「兩個因子都強」的股票穩居第一、
    「兩個因子都弱」的股票敬陪末座，不是誰的漲幅大就贏（純漲幅排序）、也不是誰連買
    最久就贏（純天數排序）。中間三檔（各自單一因子突出）用來確保不會被兩個極端排擠。"""
    candidates = [
        {"stock_id": "weakest", "foreign_streak": 3, "price_cum_pct": 6.0},    # 兩個因子都最弱
        {"stock_id": "strongest", "foreign_streak": 10, "price_cum_pct": 71.1},  # 兩個因子都最強
        {"stock_id": "price_only", "foreign_streak": 4, "price_cum_pct": 57.39},  # 漲幅強、連買普通
        {"stock_id": "streak_only", "foreign_streak": 9, "price_cum_pct": 9.22},  # 連買強、漲幅普通
        {"stock_id": "middling", "foreign_streak": 5, "price_cum_pct": 25.0},
    ]
    ids = [c["stock_id"] for c in _composite_sort(candidates, "foreign_streak")]

    assert ids[0] == "strongest", "兩個因子都最強的應該穩居第一"
    assert ids[-1] == "weakest", "兩個因子都最弱的應該敬陪末座"
    # 純漲幅排序會把 price_only 排第一；純天數排序會把 streak_only 排第一。
    # Composite Score 下兩者都不該是第一名（已經被 strongest 佔走）。
    assert ids[0] not in ("price_only", "streak_only")


def test_composite_sort_empty_list_does_not_crash():
    assert _composite_sort([], "foreign_streak") == []


def test_build_section6_strong_signal_excludes_stocks_outside_tracked_universe():
    """強力訊號只該顯示 App 追蹤的電子科技族群個股。stock_universe.csv 從未收錄金融/鋼鐵/
    傳產股（meta_sector 對這些股票是空字串），這些股票不該混進強力訊號榜（Cody 實際看到
    2886 兆豐金、2006 東和鋼鐵這類股票混在裡面，跟這個 App 的追蹤範圍不符）。"""
    inst_scan = [
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工", "exchange": "TWSE",
         "close": 950.0, "change_pct": 1.0, "foreign_streak": 3, "trust_streak": 3,
         "both_streak": 3, "foreign_net": 1000, "trust_net": 500, "total_net": 1500},
        {"stock_id": "2886", "stock_name": "兆豐金", "meta_sector": "", "exchange": "TWSE",
         "close": 40.0, "change_pct": 0.5, "foreign_streak": 5, "trust_streak": 5,
         "both_streak": 5, "foreign_net": 2000, "trust_net": 800, "total_net": 2800},
    ]
    s6a_html, _ = _build_section6(inst_scan)

    assert "台積電" in s6a_html
    assert "兆豐金" not in s6a_html, "meta_sector 為空（不在追蹤的電子科技族群清單）應被排除"


def test_build_section6_trust_table_filters_by_price_cum_pct_too():
    """投信榜比照外資榜（2026-07-09 Cody 要求一致）：trust_streak>=5 且 price_cum_pct>=5%
    才入選，股價沒反應的投信買超（可能只是被動式資金流入）要濾掉。"""
    inst_scan = [
        {"stock_id": "2483", "stock_name": "百容", "meta_sector": "載板", "exchange": "TWSE",
         "close": 80.0, "change_pct": 6.58, "trust_streak": 5, "foreign_streak": 0,
         "both_streak": 0, "trust_net": 1000, "cum_trust": 5000, "price_cum_pct": 20.0},
        {"stock_id": "9999", "stock_name": "無反應股", "meta_sector": "測試", "exchange": "TWSE",
         "close": 50.0, "change_pct": 0.1, "trust_streak": 5, "foreign_streak": 0,
         "both_streak": 0, "trust_net": 1000, "cum_trust": 999999, "price_cum_pct": 0.5},
    ]
    _, s6b_html = _build_section6(inst_scan)

    assert "百容" in s6b_html
    assert "無反應股" not in s6b_html, "投信買超但股價沒反應（0.5% < 5% 門檻）應被濾掉"
    assert "投信持續買進" in s6b_html and "10日漲幅" in s6b_html


def _margin_alert_row(sid, name, chg, data_date):
    return {"stock_id": sid, "stock_name": name, "meta_sector": "半導體",
            "margin_balance": 100000, "margin_change": chg,
            "alert_pct": round(chg / 1000, 1), "close": 100.0, "change_pct": 1.0,
            "data_date": data_date}


def test_margin_alert_table_flags_lagged_data_date():
    """新 🔴（融資跨交易日混用）：警示列混用不同交易日時，落後那一天的個股要被標出實際
    資料日期，不能全部被當成同一天呈現。"""
    alerts = [
        _margin_alert_row("6488", "環球晶", 9000, "2026-07-09"),  # 最新日
        _margin_alert_row("2330", "台積電", 8000, "2026-07-08"),  # 落後一天
    ]
    html = _margin_alert_table(alerts)
    assert "07/08" in html, "落後那列(2330 用 7/08)要標出實際資料日期"
    assert "07/09" not in html, "最新那列不標日期（避免噪音）"


def test_margin_alert_table_no_date_badge_when_all_same_date():
    """所有列同一天時不標任何資料日期徽章，保持乾淨。"""
    alerts = [_margin_alert_row("2330", "台積電", 8000, "2026-07-09")]
    html = _margin_alert_table(alerts)
    assert "📅" not in html


def test_margin_alert_table_handles_missing_data_date():
    """舊資料沒有 data_date 欄位時不標徽章、不報錯。"""
    row = _margin_alert_row("2330", "台積電", 8000, "2026-07-09")
    del row["data_date"]
    html = _margin_alert_table([row])
    assert "📅" not in html
    assert "2330" in html


def test_build_section4_shows_section_date_when_all_rows_lagged():
    """#5：融資警示整批一致落後 headline 一天時，區塊內同日 → 個股徽章不標（既有行為），
    但 section 標題要標出這個區塊自己的資料日期，不能讓「整批落後」完全無跡可尋。"""
    alerts = [
        _margin_alert_row("2330", "台積電", 8000, "2026-07-08"),
        _margin_alert_row("6488", "環球晶", 9000, "2026-07-08"),
    ]
    html = _build_section4({"margin_alerts": alerts})
    assert "資料日 07/08" in html
    assert "📅" not in html, "區塊內同日，個股徽章維持不標（既有行為不變）"


def test_build_section4_no_section_date_when_no_alerts():
    html = _build_section4({"margin_alerts": []})
    assert "資料日" not in html


def test_build_section2_shows_section_date_per_half_independently():
    """#5：外資大買/大賣是兩個獨立區塊，各自標自己的資料日期，不能共用同一個基準。"""
    buy_stocks = [{
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
        "close": 950.0, "change_pct": 1.0, "foreign_net": 1000, "trust_net": 500,
        "data_date": "2026-07-08",
    }]
    sell_stocks = [{
        "stock_id": "2317", "stock_name": "鴻海", "meta_sector": "電子",
        "close": 100.0, "change_pct": -1.0, "foreign_net": -1000, "trust_net": -500,
        "data_date": "2026-07-09",
    }]
    html = _build_section2({"foreign_top_buy": buy_stocks, "foreign_top_sell": sell_stocks})
    assert "資料日 07/08" in html
    assert "資料日 07/09" in html
