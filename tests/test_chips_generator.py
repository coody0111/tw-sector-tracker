from datetime import date

from export.chips_generator import _build_section2, _build_section4, _build_section6, _build_section8, _calc_trend_svg, _composite_sort, _coverage_flag, _esc, _evidence_card, _evidence_banner, _holder_card_html, _holder_column_html, _insider_holdings_table, _inst_streak_table, _margin_alert_table, _meta_link, _percentile_ranks, _shareholder_table, _stock_rank_table, generate


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


def test_stock_rank_table_shows_foreign_pct_column():
    """外資持股%（存量，TWSE MI_QFIIS/TPEx tpex_3insti_qfii）跟既有買賣超（流量）是不同
    資料源、不同欄位，兩者並存顯示。"""
    stocks = [{
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
        "foreign_net": 1000, "trust_net": 500, "foreign_pct": 69.59,
    }]
    html = _stock_rank_table(stocks, header="外資買超")
    assert "外資持股%" in html
    assert "69.6%" in html


def test_stock_rank_table_foreign_pct_missing_shows_dash():
    """沒有外資持股%資料的股票（TPEx 排行表沒上榜/新股）顯示「─」，不能報錯。"""
    stocks = [{
        "stock_id": "9999", "stock_name": "無資料股", "meta_sector": "測試",
        "foreign_net": 100, "trust_net": 50, "foreign_pct": None,
    }]
    html = _stock_rank_table(stocks, header="外資買超")
    assert "─" in html


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


def test_generate_includes_responsive_filters_sorting_and_accessible_tabs(tmp_path):
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "role=\"tablist\"" in html
    assert "aria-selected=\"false\"" in html
    assert "id='stock-search'" in html
    assert "table-shell" in html
    assert "sort-button" in html
    assert "查看全部" in html
    assert "class=\"section-nav\"" in html
    assert "aria-current=\"page\"" in html
    assert "TWSE、TPEx" in html and "TDCC" in html and "公開資訊觀測站" in html


def test_generate_uses_actual_chips_date_weekday(tmp_path):
    """頁首星期要跟資料日一致，不能在週日重跑時把週五資料標成週日。"""
    output_path = tmp_path / "chips.html"
    generate(
        date(2026, 7, 5),
        {"測試族群": {"foreign_net_today": 100}},
        {"chips_date": "2026-07-03"},
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")
    assert "2026-07-03（週五）" in html


def test_generate_includes_evidence_tier_css_classes(tmp_path):
    """證據分級的 CSS class 要出現在 <style> 裡，四級徽章+證據卡+兩種banner。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    for cls in (".evid", ".evid-verified", ".evid-observe", ".evid-unproven", ".evid-weak",
                ".evid-card", ".caution-banner", ".weak-banner"):
        assert cls in html, f"{cls} 應該出現在 <style> 裡"


def test_generate_tab_nav_orders_by_evidence_strength_with_badges(tmp_path):
    """特殊型態組內第一個該是融資警示(已驗證)，法人同步觀察不再是第一個 tab-group 的第一個
    按鈕；每個按鈕都要帶對應的證據徽章。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")

    # 特殊型態組：融資警示排最前面（已驗證優先）
    margin_idx = html.index('data-tab="tab-margin"')
    stealth_idx = html.index('data-tab="tab-stealth"')
    dipbuy_idx = html.index('data-tab="tab-dipbuy"')
    assert margin_idx < stealth_idx < dipbuy_idx

    # 每個 tab 按鈕都帶對應徽章（用 button id 附近的文字片段確認，不是全域計數，
    # 避免不同 tab 剛好同一種徽章互相混淆）。切片區間要照「新排列順序」抓下一個按鈕的
    # id 當結尾，順序是 margin→stealth→dipbuy→foreign→trust→signal→inst→holder→insider——
    # 抓錯順序會讓 start > stop，Python 切出空字串，斷言會誤判過（第一版寫錯過，這裡已修正）。
    margin_btn = html[html.index('id="tab-btn-margin"'):html.index('id="tab-btn-stealth"')]
    assert 'evid-verified' in margin_btn and '已驗證' in margin_btn

    dipbuy_btn = html[html.index('id="tab-btn-dipbuy"'):html.index('id="tab-btn-foreign"')]
    assert 'evid-weak' in dipbuy_btn and '證據偏弱' in dipbuy_btn

    signal_btn = html[html.index('id="tab-btn-signal"'):html.index('id="tab-btn-inst"')]
    assert 'evid-observe' in signal_btn and '觀察用' in signal_btn

    insider_btn = html[html.index('id="tab-btn-insider"'):]
    assert 'evid-unproven' in insider_btn and '待驗證' in insider_btn


def test_generate_default_tab_is_margin_not_signal(tmp_path):
    """預設分頁改成證據最強的融資警示，不再預設開在法人同步觀察。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "switchTab(_tabs.includes(_h)?_h:'tab-margin')" in html


def test_coverage_flag_empty_when_not_partial():
    assert _coverage_flag({"partial_coverage": False}) == ""
    assert _coverage_flag({}) == ""


def test_coverage_flag_renders_warning_when_partial():
    out = _coverage_flag({"partial_coverage": True})
    assert "資料不完整" in out
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


def test_shareholder_table_shows_400_and_1000_tier_columns():
    """大戶籌碼表要顯示兩層：400張以上（累計 lv12_15_pct，包含1000張以上那層）跟
    1000張以上（單獨 lv15_pct）。舊版「400張大戶」欄位曾誤用 lv12_shares（只算
    TDCC level 12 單一級距 400,001~600,000股窄band，不是累計≥400張），已拿掉。"""
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "400張以上大戶" in html
    assert "1000張以上大戶" in html
    assert "1,600" not in html, "lv12_shares 窄band 數字不該再出現（已拿掉這欄）"
    assert "2,900" in html   # lv15_shares / 1000 = 2,900 張
    assert "20.0" in html    # lv12_15_pct（400張以上大戶%，主指標）
    assert "11.6" in html    # lv15_pct（1000張以上大戶%）


def test_shareholder_table_handles_missing_lv15_data():
    """沒有 lv15 分層資料的股票（舊資料，尚未跑過新版 --update-shareholder）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_SH_ROW)
    row["lv15_shares"] = None
    row["lv15_pct"] = None
    row["lv15_chg"] = None
    html = _shareholder_table([row])
    assert "─" in html


def test_shareholder_table_includes_share_chg_column():
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "大戶張數變化" in html
    assert "250" in html  # 250,000 股 = 250 張


def test_insider_holdings_table_includes_insider_columns():
    """董監持股已從大戶籌碼表拆成獨立表格（_insider_holdings_table），兩者是不同資料源。"""
    html = _insider_holdings_table([_SAMPLE_SH_ROW])
    assert "公司派" in html
    assert "大股東" in html
    assert "13.3" in html  # 質押比例


def test_insider_holdings_table_handles_missing_insider_data():
    """沒有 insider_holdings 資料的股票（新股/還沒跑過 --update-insider-holdings）要顯示「─」，不能報錯。"""
    row = dict(_SAMPLE_SH_ROW)
    row["company_shares"] = None
    row["company_chg"] = None
    row["company_pledge_pct"] = None
    row["major_holder_shares"] = None
    row["major_holder_chg"] = None
    row["major_holder_pledge_pct"] = None
    html = _insider_holdings_table([row])
    assert "─" in html


def test_shareholder_table_does_not_include_insider_columns():
    """大戶籌碼表（TDCC 集保）不該再顯示公司派/大股東欄——已拆成獨立的董監持股表。"""
    html = _shareholder_table([_SAMPLE_SH_ROW])
    assert "公司派" not in html
    assert "大股東" not in html


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
         "both_streak": 3, "foreign_net": 1_000_000, "trust_net": 500_000, "total_net": 1_500_000,
         "volume": 1000, "institutional_flow_ratio_pct": 0.15, "price_cum_pct": 1.0},
        {"stock_id": "2886", "stock_name": "兆豐金", "meta_sector": "", "exchange": "TWSE",
         "close": 40.0, "change_pct": 0.5, "foreign_streak": 5, "trust_streak": 5,
         "both_streak": 5, "foreign_net": 2000, "trust_net": 800, "total_net": 2800},
    ]
    s6a_html, _, _ = _build_section6(inst_scan)

    assert "台積電" in s6a_html
    assert "兆豐金" not in s6a_html, "meta_sector 為空（不在追蹤的電子科技族群清單）應被排除"


def test_build_section6_joint_buy_rejects_tiny_or_illiquid_flows():
    base = {"stock_name": "測試股", "meta_sector": "半導體", "exchange": "TWSE",
            "close": 50.0, "change_pct": 1.0, "foreign_streak": 3, "trust_streak": 3,
            "both_streak": 3, "foreign_net": 1000, "trust_net": 500, "total_net": 1500,
            "price_cum_pct": 2.0}
    rows = [
        {**base, "stock_id": "1111", "volume": 1000, "institutional_flow_ratio_pct": 0.01},
        {**base, "stock_id": "2222", "volume": 100, "institutional_flow_ratio_pct": 0.5},
        {**base, "stock_id": "3333", "volume": 1000, "institutional_flow_ratio_pct": 0.2,
         "foreign_net": 1_500_000, "trust_net": 500_000, "total_net": 2_000_000},
    ]
    html, _, _ = _build_section6(rows)
    assert "1111" not in html
    assert "2222" not in html
    assert "3333" in html
    assert "買超占量" in html


def test_build_section8_insider_ranking_is_independent_from_tdcc_rows():
    tdcc = [{**_SAMPLE_SH_ROW, "stock_id": "1111", "stock_name": "集保股"}]
    insiders = [{**_SAMPLE_SH_ROW, "stock_id": "2222", "stock_name": "內部人股",
                 "company_chg": 2_000_000, "report_date": "2026-07-01"}]
    _, _, insider_html = _build_section8(tdcc, insiders)
    assert "內部人股" in insider_html
    assert "集保股" not in insider_html
    assert "與集保大戶榜獨立計算" in insider_html


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
    _, _, s6_trust_html = _build_section6(inst_scan)

    assert "百容" in s6_trust_html
    assert "無反應股" not in s6_trust_html, "投信買超但股價沒反應（0.5% < 5% 門檻）應被濾掉"
    assert "投信持續買進" in s6_trust_html and "10日漲幅" in s6_trust_html


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


def test_calc_trend_svg_returns_none_when_fewer_than_two_points():
    """少於2筆資料畫不出線，回傳None讓呼叫端顯示「資料不足」文字，不是硬畫一個點。"""
    assert _calc_trend_svg([]) is None
    assert _calc_trend_svg([{"date": "2026-07-17", "lv12_15_pct": 60.0}]) is None


def test_calc_trend_svg_scales_points_to_viewbox():
    """viewBox固定0 0 92 32，圖表繪製區x=22~92/y=2~18。5個點應該平均分布在x=22~92，
    y依min-max正規化（最大值在y=2附近，最小值在y=18附近）。"""
    trend = [
        {"date": "2026-06-19", "lv12_15_pct": 60.0},
        {"date": "2026-06-26", "lv12_15_pct": 61.0},
        {"date": "2026-07-03", "lv12_15_pct": 62.5},
        {"date": "2026-07-10", "lv12_15_pct": 63.0},
        {"date": "2026-07-17", "lv12_15_pct": 64.0},
    ]
    result = _calc_trend_svg(trend)

    assert result["y_max_label"] == "64.0"
    assert result["y_min_label"] == "60.0"
    assert result["x_labels"] == ["06/19", "06/26", "07/03", "07/10", "07/17"]
    # 5個點：x座標從22到92平均分布
    points = result["line_points"]
    assert points[0].startswith("22.0,")
    assert points[-1].startswith("92.0,")
    # 最新一筆(64.0，最大值)應該在y=2(圖表頂部)
    assert points[-1] == "92.0,2.0"
    # 最舊一筆(60.0，最小值)應該在y=18(圖表底部)
    assert points[0] == "22.0,18.0"


def test_calc_trend_svg_handles_fewer_than_five_points():
    """只有2筆資料(新股/剛納入追蹤)時，2個點應該落在x=22跟x=92(圖表兩端)，不是
    擠在左邊或用固定5等分的間距（間距要照實際筆數動態算，不是寫死5）。"""
    trend = [
        {"date": "2026-07-10", "lv12_15_pct": 40.0},
        {"date": "2026-07-17", "lv12_15_pct": 41.5},
    ]
    result = _calc_trend_svg(trend)

    assert len(result["line_points"]) == 2
    assert result["line_points"][0].startswith("22.0,")
    assert result["line_points"][1].startswith("92.0,")
    assert result["x_labels"] == ["07/10", "07/17"]


def test_calc_trend_svg_handles_flat_series_without_division_by_zero():
    """所有值都相同時(min==max)，range=0會除零——必須有防呆，不能crash，這種情況所有點
    應該畫在垂直置中(y=10，圖表區y=2~18的中點)。"""
    trend = [
        {"date": "2026-07-10", "lv12_15_pct": 50.0},
        {"date": "2026-07-17", "lv12_15_pct": 50.0},
    ]
    result = _calc_trend_svg(trend)

    assert result["line_points"][0] == "22.0,10.0"
    assert result["line_points"][1] == "92.0,10.0"


def test_holder_card_html_renders_divergent_bar_matching_direction():
    """週變化為正時發散長條該用up方向(css class)，負時用down。"""
    row = {
        "stock_id": "5347", "stock_name": "世界先進", "meta_sector": "晶圓代工",
        "close": 128.5, "change_pct": 1.2,
        "lv12_15_pct": 68.4, "week_chg": 2.1, "streak": 6,
        "share_chg": 412000, "lv15_pct": 22.6,
        "trend": [
            {"date": "2026-06-19", "lv12_15_pct": 63.0},
            {"date": "2026-07-17", "lv12_15_pct": 68.4},
        ],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert "世界先進" in html
    assert "5347" in html
    assert 'class="hc-divbar"' in html
    assert '<span class="up"' in html
    assert "連增6週" in html
    assert "68.4" in html  # 絕對水位


def test_holder_card_html_negative_week_chg_uses_down_direction():
    row = {
        "stock_id": "8261", "stock_name": "富鼎", "meta_sector": "功率半導體",
        "close": 312.5, "change_pct": -0.5,
        "lv12_15_pct": 59.3, "week_chg": -0.8, "streak": -2,
        "share_chg": -96000, "lv15_pct": 18.1,
        "trend": [
            {"date": "2026-07-10", "lv12_15_pct": 60.1},
            {"date": "2026-07-17", "lv12_15_pct": 59.3},
        ],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert '<span class="down"' in html
    assert "連減2週" in html


def test_holder_card_html_shows_insufficient_data_when_trend_missing():
    """trend筆數<2(新股/剛納入追蹤)時，卡片要顯示「資料不足」文字，不能crash、
    不能留空白區塊裝作沒事。"""
    row = {
        "stock_id": "1101", "stock_name": "測試股", "meta_sector": "水泥",
        "close": 40.0, "change_pct": 0.5,
        "lv12_15_pct": 41.5, "week_chg": 1.5, "streak": 1,
        "share_chg": 1000, "lv15_pct": 5.0,
        "trend": [{"date": "2026-07-17", "lv12_15_pct": 41.5}],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert "資料不足" in html


def test_holder_card_html_escapes_malicious_stock_name():
    row = {
        "stock_id": "9999", "stock_name": "<script>alert(1)</script>", "meta_sector": "測試",
        "close": 10.0, "change_pct": 0.0,
        "lv12_15_pct": 50.0, "week_chg": 0.0, "streak": 0,
        "share_chg": 0, "lv15_pct": 0.0,
        "trend": [],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=1.0)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_holder_column_html_scales_divergent_bar_to_column_max():
    """發散長條寬度依「這一欄實際出現的最大週變化幅度」動態縮放，不是固定量尺——
    這一欄最大變化的那檔應該長條寬度撐滿(接近50%的一半寬)，其他檔案按比例縮小。"""
    rows = [
        {"stock_id": "A", "stock_name": "甲", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 60.0, "week_chg": 4.0, "streak": 3,
         "share_chg": 0, "lv15_pct": 0.0, "trend": []},
        {"stock_id": "B", "stock_name": "乙", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 55.0, "week_chg": 2.0, "streak": 2,
         "share_chg": 0, "lv15_pct": 0.0, "trend": []},
    ]
    html = _holder_column_html(rows, direction="inc")

    assert "width:50.0%" in html  # 甲(4.0)是最大值，長條撐滿50%(發散長條半邊寬度上限)
    assert "width:25.0%" in html  # 乙(2.0)是甲的一半，長條寬度也是一半


def test_holder_column_html_empty_list_shows_no_data_message():
    html = _holder_column_html([], direction="dec")
    assert "無資料" in html


def test_holder_card_html_handles_none_close_and_none_lv12_15_pct():
    """main.py確實會產生close/lv12_15_pct都是None的row（缺行情資料/缺TDCC快照），
    這兩個欄位用.get(key, default)的dict-default trick在key存在但value是None時
    不會fallback，會直接把None格式化進字串或f-string crash。"""
    row = {
        "stock_id": "9998", "stock_name": "缺資料股", "meta_sector": "測試",
        "close": None, "change_pct": None,
        "lv12_15_pct": None, "week_chg": 0.5, "streak": 1,
        "share_chg": None, "lv15_pct": None,
        "trend": [],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=1.0)  # should not raise
    assert "─" in html
    assert "None" not in html


def test_build_section8_uses_card_rendering_not_old_table():
    """Section 8改用卡片渲染後，舊的13欄表格結構(<table class='ct'>那種)不該再出現在
    大戶持倉區塊，改成.holder-grid卡片。"""
    shareholder_data = [
        {"stock_id": "5347", "stock_name": "世界先進", "meta_sector": "晶圓代工",
         "close": 128.5, "change_pct": 1.2, "lv12_15_pct": 68.4, "week_chg": 2.1,
         "streak": 6, "share_chg": 412000, "lv15_pct": 22.6, "date": "2026-07-17",
         "trend": [{"date": "2026-07-10", "lv12_15_pct": 66.3},
                   {"date": "2026-07-17", "lv12_15_pct": 68.4}]},
    ]
    s8_html, s8_note, _ = _build_section8(shareholder_data, [])

    assert "holder-grid" in s8_html
    assert "holder-card" in s8_html
    assert "大戶連增倉" in s8_html


def test_build_section8_splits_increasing_and_decreasing_columns():
    """streak>0進連增倉欄、streak<0進連減倉欄，這個既有分組邏輯不能因為改卡片渲染
    就跑掉。"""
    shareholder_data = [
        {"stock_id": "A", "stock_name": "增股", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 60.0, "week_chg": 1.0, "streak": 2,
         "share_chg": 0, "lv15_pct": 0.0, "date": "2026-07-17", "trend": []},
        {"stock_id": "B", "stock_name": "減股", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 40.0, "week_chg": -1.0, "streak": -2,
         "share_chg": 0, "lv15_pct": 0.0, "date": "2026-07-17", "trend": []},
    ]
    s8_html, _, _ = _build_section8(shareholder_data, [])

    inc_pos = s8_html.index("增股")
    dec_pos = s8_html.index("減股")
    inc_title_pos = s8_html.index("大戶連增倉")
    dec_title_pos = s8_html.index("大戶連減倉")
    assert inc_title_pos < inc_pos < dec_title_pos < dec_pos


def test_generate_groups_sidebar_tabs_into_three_clusters(tmp_path):
    """9個tab-btn分成3組(法人動向/特殊型態/持股結構)，既有tab-panel的id/data-tab/
    aria-controls不能因為分組而改變(switchTab() JS邏輯依賴這些屬性)。"""
    output_path = tmp_path / "chips.html"
    generate(
        trade_date=date(2026, 7, 29),
        meta_chips={"外資連買": {}}, stock_chips={"chips_date": "2026-07-29"},
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    assert "法人動向" in html
    assert "特殊型態" in html
    assert "持股結構" in html
    # 既有9個tab按鈕的id/data-tab屬性必須都還在，分組不能動到這些(JS依賴)
    for tab_id in ["signal", "dipbuy", "stealth", "inst", "foreign", "trust", "margin", "holder", "insider"]:
        assert f'id="tab-btn-{tab_id}"' in html
        assert f'data-tab="tab-{tab_id}"' in html
        assert f'aria-controls="tab-{tab_id}"' in html

    label_pattern_group = html.index("特殊型態")
    label_signal_group = html.index("法人動向")
    label_structure_group = html.index("持股結構")
    assert label_pattern_group < label_signal_group < label_structure_group

    pos_margin = html.index('id="tab-btn-margin"')
    pos_stealth = html.index('id="tab-btn-stealth"')
    pos_dipbuy = html.index('id="tab-btn-dipbuy"')
    pos_foreign = html.index('id="tab-btn-foreign"')
    pos_trust = html.index('id="tab-btn-trust"')
    pos_signal = html.index('id="tab-btn-signal"')
    pos_inst = html.index('id="tab-btn-inst"')
    pos_holder = html.index('id="tab-btn-holder"')
    pos_insider = html.index('id="tab-btn-insider"')

    # 特殊型態 group（已驗證優先）的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_pattern_group < pos_margin < pos_stealth < pos_dipbuy < label_signal_group
    # 法人動向 group的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_signal_group < pos_foreign < pos_trust < pos_signal < label_structure_group
    # 持股結構 group的按鈕都要落在自己的標籤之後（組內順序不變）
    assert label_structure_group < pos_inst < pos_holder < pos_insider


def test_generate_no_longer_shows_candidate_observation_hero(tmp_path):
    """候選觀察/大戶持倉本週焦點的開頁hero已移除——joint_buy跟tdcc_accumulation
    回測都沒有展現edge，不該再佔全頁最顯眼的hero版位（見2026-08-25 spec）。
    法人同步觀察的完整榜單仍在tab-signal面板，不受影響。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert 'class="hero"' not in html
    assert "候選觀察" not in html
    assert "大戶持倉本週焦點" not in html


def test_evidence_card_renders_badge_and_stats():
    html = _evidence_card("evid-verified", "已驗證", "訊號日 63．筆數 1154", "短期參考價值較高")
    assert 'class="evid evid-verified"' in html
    assert "已驗證" in html
    assert "訊號日 63" in html
    assert "短期參考價值較高" in html


def test_evidence_banner_caution_and_weak_variants():
    caution = _evidence_banner("caution", "樣本不足，尚未驗證", "資料只有3個月頻快照")
    assert 'class="caution-banner"' in caution
    assert "樣本不足，尚未驗證" in caution

    weak = _evidence_banner("weak", "回測顯示這個假設目前沒有得到支持", "D+14平均落後大盤0.53%")
    assert 'class="weak-banner"' in weak
    assert "回測顯示這個假設目前沒有得到支持" in weak


def test_generate_shows_evidence_card_in_every_backtested_tab(tmp_path):
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")

    tab_signal = html[html.index('id="tab-signal"'):html.index('id="tab-dipbuy"')]
    assert 'evid-observe' in tab_signal and "訊號日 61" in tab_signal

    tab_dipbuy = html[html.index('id="tab-dipbuy"'):html.index('id="tab-stealth"')]
    assert 'weak-banner' in tab_dipbuy and "回測顯示這個假設目前沒有得到支持" in tab_dipbuy

    tab_stealth = html[html.index('id="tab-stealth"'):html.index('id="tab-inst"')]
    assert 'evid-observe' in tab_stealth and "訊號日 63" in tab_stealth

    tab_inst = html[html.index('id="tab-inst"'):html.index('id="tab-foreign"')]
    assert 'evid-observe' in tab_inst

    tab_foreign = html[html.index('id="tab-foreign"'):html.index('id="tab-trust"')]
    assert 'evid-observe' in tab_foreign and "訊號日 61" in tab_foreign

    tab_trust = html[html.index('id="tab-trust"'):html.index('id="tab-margin"')]
    assert 'evid-observe' in tab_trust and "訊號日 57" in tab_trust

    tab_margin = html[html.index('id="tab-margin"'):html.index('id="tab-holder"')]
    assert 'evid-verified' in tab_margin and "訊號日 63" in tab_margin

    tab_holder = html[html.index('id="tab-holder"'):html.index('id="tab-insider"')]
    assert 'evid-observe' in tab_holder and "訊號日 29" in tab_holder

    tab_insider = html[html.index('id="tab-insider"'):]
    assert 'caution-banner' in tab_insider and "樣本不足，尚未驗證" in tab_insider


