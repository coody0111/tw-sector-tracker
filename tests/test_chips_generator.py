from datetime import date

from export.chips_generator import _coverage_flag, _esc, _meta_link, _shareholder_table, _stock_rank_table, generate


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
}


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


def test_shareholder_table_row_td_count_matches_header():
    """資料列的 <td> 數必須等於表頭 <th> 欄數——防止 _insider_cell/_price_cell 這類
    『回傳完整 <td> 卻又被外層 <td> 包一次』的雙重 <td> 結構 bug（substring 測試抓不到）。"""
    html = _shareholder_table([_SAMPLE_SH_ROW])
    n_th = html.count("<th>")
    body = html.split("</thead>")[1]   # 只數 tbody 的資料列
    n_td = body.count("<td")           # <td 前綴涵蓋 <td> 與 <td ...>
    assert n_td == n_th, f"資料列 <td> 數 {n_td} != 表頭 <th> 數 {n_th}（可能有雙重 <td>）"
