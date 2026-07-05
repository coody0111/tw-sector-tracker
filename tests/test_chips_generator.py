from datetime import date

from export.chips_generator import _esc, _meta_link, _stock_rank_table, generate


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
