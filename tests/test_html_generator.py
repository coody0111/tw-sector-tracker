from datetime import date

import pandas as pd
import export.html_generator as hg
from export.html_generator import _esc, _stock_card_html, _meta_card, generate, _stock_table


def test_stock_table_shows_5d_7d_10d_14d_columns():
    """index 族群個股表用 get_rolling_returns 的近5/7/10/14日欄（收盤價比值），
    取代舊的單一複利週漲跌；缺值顯示「─」；資料列 td 數 == 表頭 th 數。"""
    hg._ROLLING_RETURNS = {"2330": {5: 3.21, 7: -1.50, 10: 8.00, 14: None}}
    try:
        sectors = pd.DataFrame([{"sector_name": "半導體", "stock_id": "2330", "stock_name": "台積電"}])
        prices = pd.DataFrame([{"stock_id": "2330", "close": 950.0, "change_pct": 1.5, "volume": 10000}])
        html = _stock_table("半導體", sectors, prices, as_row=False)
        assert "近5日" in html and "近7日" in html and "近10日" in html and "近14日" in html
        assert "週漲跌%" not in html            # 舊複利欄已被取代
        assert "+3.21%" in html and "-1.50%" in html and "+8.00%" in html
        assert "─" in html                      # 近14日缺值
        import re
        n_th = len(re.findall(r"<th ", html))
        row = re.search(r'<tr class="st-row".*?</tr>', html, re.DOTALL).group(0)
        assert n_th == row.count("<td"), "表頭 th 數應等於資料列 td 數"
    finally:
        hg._ROLLING_RETURNS = {}


def test_esc_escapes_html_special_characters():
    assert _esc('<script>alert(1)</script>') == '&lt;script&gt;alert(1)&lt;/script&gt;'
    assert _esc('A&B "quoted"') == 'A&amp;B &quot;quoted&quot;'
    assert _esc(None) == ""
    assert _esc("") == ""


def test_stock_card_html_escapes_malicious_stock_name():
    """股票名稱來自 TWSE/TPEx API 回應；若被竄改成含 HTML 標籤，
    產生的卡片 HTML 不應該讓標籤原樣穿透（會造成發布到 GitHub Pages 的
    index.html 被注入）。"""
    malicious_name = '<script>alert(1)</script>'
    empty_df = pd.DataFrame(columns=["close", "change_pct", "volume"]).set_index(
        pd.Index([], name="stock_id")
    )
    html = _stock_card_html("9999", malicious_name, empty_df, empty_df)

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_meta_card_escapes_malicious_meta_name():
    """族群名稱同樣來自外部資料組合而成，卡片文字節點與 data-* 屬性都要跳脫。"""
    malicious_meta = '"><script>alert(1)</script>'
    row = {
        "meta_name": malicious_meta,
        "avg_change_pct": 1.0,
        "up_count": 1,
        "down_count": 0,
        "sub_names": [],
    }
    card, _panel = _meta_card(row, rank=1, card_id="t0", sectors_df=None,
                               prices_df=None, chips_df=None, universe_df=None,
                               cum_ranks={}, meta_signals={}, meta_chips={})

    assert '<script>alert(1)</script>' not in card
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in card


def test_generate_escapes_script_breakout_in_embedded_json_index(tmp_path):
    """STOCK_INDEX/META_INDEX 是直接內嵌進 <script> 標籤的 JSON（不是走 innerHTML），
    如果股票名稱剛好含有 "</script>"，未經處理的 json.dumps() 不會跳脫它，
    會提前結束這個 script 區塊、讓後面的內容被當成新的 HTML 解析。"""
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "9999", "stock_name": '</script><script>alert(1)</script>',
         "meta_sector": "測試族群"},
    ])
    meta_perf = [{
        "meta_name": "測試族群", "sub_names": ["測試族群"],
        "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0,
        "stock_ids": ["9999"],
    }]

    generate(
        trade_date=date(2026, 7, 5),
        perf_df=pd.DataFrame(),
        meta_perf=meta_perf,
        universe_df=universe_df,
        output_path=str(output_path),
    )

    html = output_path.read_text(encoding="utf-8")
    assert '</script><script>alert(1)</script>' not in html
    assert '<\\/script><script>alert(1)<\\/script>' in html
