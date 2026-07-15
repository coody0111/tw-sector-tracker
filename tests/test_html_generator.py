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


def test_stock_card_html_shows_volume_ratio_and_modal_history_data():
    prices = pd.DataFrame([{
        "stock_id": "2330", "close": 950.0, "change_pct": 1.5, "volume": 30000,
    }]).set_index("stock_id")
    chips = pd.DataFrame(columns=["foreign_net", "trust_net", "margin_balance", "margin_change"])
    chips.index.name = "stock_id"
    history = {"2330": {
        "pcts": [1.0, -0.5, 1.5],
        "volumes": [10000, 20000, 30000],
        "dates": ["07/13", "07/14", "07/15"],
        "avg_volume": 15000,
        "vol_ratio": 2.0,
    }}

    html = _stock_card_html("2330", "台積電", prices, chips, history)

    assert "今日 30,000 張" in html
    assert "量比 2.00x" in html
    assert 'role="button" tabindex="0"' in html
    assert "event.key==='Enter'" in html
    assert "data-volume-history='[10000, 20000, 30000]'" in html
    assert "data-volume-dates='[\"07/13\", \"07/14\", \"07/15\"]'" in html


def test_stock_table_adds_sortable_volume_ratio_column():
    sectors = pd.DataFrame([{"sector_name": "半導體", "stock_id": "2330", "stock_name": "台積電"}])
    prices = pd.DataFrame([{"stock_id": "2330", "close": 950.0, "change_pct": 1.5, "volume": 30000}])
    history = {"2330": {
        "pcts": [1.0, 1.5], "volumes": [10000, 30000], "dates": ["07/14", "07/15"],
        "avg_volume": 10000, "vol_ratio": 3.0,
    }}

    html = _stock_table("半導體", sectors, prices, stock_sparklines=history, as_row=False)

    assert 'data-key="volratio">量比' in html
    assert 'data-volratio="3.0"' in html
    assert "量比 3.00x" in html
    assert 'role="button" tabindex="0"' in html


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


# ── 大盤分級儀表板 _market_regime_section ──────────────────────────
from export.html_generator import _market_regime_section


def test_market_regime_section_renders_tier_and_concentration():
    html = _market_regime_section({
        "tier": "小漲", "taiex_change_pct": 0.6,
        "breadth_ratio": 0.48, "up_count": 480, "total": 1000,
        "is_concentrated": True,
        "concentration_direction": "權值股撐盤",
        "heavyweight_avg_pct": 2.1, "broad_avg_pct": -0.8,
        "divergence": 2.9, "heavyweight_count": 20,
    })
    assert "小漲" in html
    assert "權值股撐盤" in html
    assert "+0.60%" in html          # 加權指數漲跌
    assert "+2.10%" in html          # 權值股平均
    assert "-0.80%" in html          # 非權值股平均
    assert "廣度 48%" in html
    # 對應筆記操作提示（小漲 → 續抱強勢股）
    assert "續抱強勢股" in html


def test_market_regime_section_shows_tip_per_tier():
    """五級各自帶對應的筆記操作提示文字。"""
    tips = {
        "大漲": "漲時加碼", "小漲": "續抱強勢股", "持平": "不提前佈局",
        "小跌": "持股健檢", "大跌": "不接弱勢",
    }
    for tier, expect in tips.items():
        html = _market_regime_section({"tier": tier, "taiex_change_pct": 0.0})
        assert tier in html
        assert expect in html


def test_market_regime_section_hides_concentration_when_side_missing():
    """權值股或非權值股其中一邊缺資料時，不顯示資金集中度診斷（但方向標籤仍在）。"""
    html = _market_regime_section({
        "tier": "持平", "taiex_change_pct": 0.1,
        "heavyweight_avg_pct": None, "broad_avg_pct": None,
    })
    assert "持平" in html
    assert "權值股（前" not in html


def test_market_regime_section_handles_none_gracefully():
    """TAIEX 抓取失敗 → regime=None → 整塊不顯示，不讓整頁 crash。"""
    assert _market_regime_section(None) == ""
    assert _market_regime_section({}) == ""


def test_search_select_stock_selector_matches_st_row(tmp_path):
    """回歸：搜尋下拉點選個股（selectSearchStock）用的 selector 必須對應實際渲染的
    個股列 class。個股呈現改成 .st-row 表格列後，handler 若還找舊的 .stock-card
    會找不到元素 → 點選無反應 → 連不到個股資訊（modal）。"""
    import re
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
    ])
    meta_perf = [{
        "meta_name": "晶圓代工", "sub_names": ["晶圓代工"],
        "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0,
        "stock_ids": ["2330"],
    }]
    generate(
        trade_date=date(2026, 7, 9),
        perf_df=pd.DataFrame(),
        meta_perf=meta_perf,
        universe_df=universe_df,
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    body = re.search(r"function selectSearchStock\(sid\).*?\n    \}", html, re.DOTALL)
    assert body, "找不到 selectSearchStock 函式"
    assert ".st-row" in body.group(0), \
        "selectSearchStock 必須用能命中表格列(.st-row)的 selector，否則點搜尋結果無反應"
    # 且要真的把個股資訊帶出來（呼叫 openStockModal）
    assert "openStockModal" in body.group(0), \
        "selectSearchStock 應呼叫 openStockModal 顯示個股資訊"


def test_search_select_meta_selector_matches_mc_card(tmp_path):
    """回歸：搜尋下拉點選「族群」（selectSearchMeta）用的 selector 必須對應實際渲染的
    族群卡片。族群卡片是 .mc-card[data-meta-name]（meta_sector 層），但舊版 handler 卻去
    找 details.group-block[data-gname]（SECTOR_GROUPS 大分類層）——兩者不同層級，
    傳進來的 name 是 meta_sector 名稱，永遠命中不到 group-block → 點選族群無反應。
    正解與 openMetaByName 一致，鎖 data-meta-name。"""
    import re
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓代工"},
    ])
    meta_perf = [{
        "meta_name": "晶圓代工", "sub_names": ["晶圓代工"],
        "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0,
        "stock_ids": ["2330"],
    }]
    generate(
        trade_date=date(2026, 7, 15),
        perf_df=pd.DataFrame(),
        meta_perf=meta_perf,
        universe_df=universe_df,
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    body = re.search(r"function selectSearchMeta\(name\).*?\n    \}", html, re.DOTALL)
    assert body, "找不到 selectSearchMeta 函式"
    src = body.group(0)
    # 必須鎖能命中族群卡片的 data-meta-name（或委派給 openMetaByName），
    # 不能只靠命中不到的 group-block[data-gname]。
    assert ("data-meta-name" in src) or ("openMetaByName" in src), \
        "selectSearchMeta 必須用能命中族群卡片(.mc-card[data-meta-name])的 selector，否則點選族群無反應"
    assert "group-block" not in src, \
        "selectSearchMeta 不該再靠 group-block[data-gname]（大分類層，命中不到 meta_sector 名稱）"


def test_generate_renders_card_for_every_meta_sector_not_just_top_bottom_10(tmp_path):
    """回歸（2026-07-09 Cody 回報）：舊版只 render meta_sorted[:10] + 後10名，中間表現
    平平的族群完全沒有 .mc-card/data-meta-name，導致 chips.html 的「外資連買/連賣族群」
    連結、搜尋框指向這些族群時 openMetaByName 找不到卡片、靜默失敗（畫面停在空白
    index.html，看起來像「點了沒反應」）。25 個族群（> 10+10）應該全部有卡片。"""
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股", "meta_sector": f"族群{i}", "sub_sector": f"族群{i}"}
        for i in range(25)
    ])
    meta_perf = [{
        "meta_name": f"族群{i}", "sub_names": [f"族群{i}"],
        "avg_change_pct": float(i) - 12,  # 有正有負，混合分布，不是全部擠在極端值
        "up_count": 1, "down_count": 0, "flat_count": 0,
        "stock_ids": ["1000"],
    } for i in range(25)]

    generate(
        trade_date=date(2026, 7, 9),
        perf_df=pd.DataFrame(),
        meta_perf=meta_perf,
        universe_df=universe_df,
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    import re
    names_present = set(re.findall(r'data-meta-name="(族群\d+)"', html))
    expected = {f"族群{i}" for i in range(25)}
    missing = expected - names_present
    assert not missing, f"這些族群完全沒有卡片、連結會靜默失敗：{sorted(missing)}"
