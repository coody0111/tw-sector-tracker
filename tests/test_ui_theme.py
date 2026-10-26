from datetime import date, datetime

import pandas as pd

from export.ui_theme import NAV_PAGES, SHARED_CSS, render_topbar


def test_topbar_matches_index_layout():
    """2026-10-26 Cody：各分頁頁首照族群績效（index.html）：TW SECTOR TRACKER 小字＋頁名、日期靠右、導覽。"""
    html = render_topbar("個股推薦", "recommend.html", "2026-10-22", generated_at=datetime(2026, 10, 22, 15, 1))
    assert '<span class="ui-kicker">TW SECTOR TRACKER</span><h1 class="ui-title">個股推薦</h1>' in html
    assert html.index('class="ui-date"') < html.index('class="ui-nav"')
    # 右上跟 index.html 同格式：第一行狀態、第二行日期（週幾）時間
    assert '<div class="ui-date"><strong>收盤快照</strong><span>2026-10-22（週四）｜更新 10/22 15:01</span></div>' in html
    for href, label in NAV_PAGES:
        assert f'href="{href}"' in html and label in html
    assert "margin-left:auto" in SHARED_CSS.split(".ui-date{", 1)[1].split("}", 1)[0] and "--ui-serif" in SHARED_CSS   # 日期靠右


def test_watchlist_uses_shared_topbar_with_all_pages(tmp_path):
    from export.watchlist_generator import generate
    out = tmp_path / "w.html"
    generate(date(2026, 10, 22), pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓"}]),
             pd.DataFrame(), output_path=str(out))
    html = out.read_text(encoding="utf-8")
    assert 'class="ui-topbar"' in html and 'href="watchlist.html" aria-current="page"' in html
    assert 'href="recommend.html"' in html and ">族群總覽</a>" not in html   # 舊頁首的連結文字；空清單提示裡的「族群總覽」不算


def test_topbar_min_height_matches_index():
    """index.html 頁首＝上下 padding 10＋按鈕 32＝52（＋1px 底線）；共用頁首最低高度也要 52，不能比它高（2026-10-26 量到 57 vs 53）。"""
    assert "--ui-topbar-h:52px" in SHARED_CSS


def test_intraday_label_matches_index():
    html = render_topbar("籌碼分析", "chips.html", date(2026, 10, 27), "intraday", generated_at=datetime(2026, 10, 27, 10, 30))
    assert "<strong>盤中資料，尚未收盤確認</strong><span>2026-10-27（週二）｜更新 10/27 10:30</span>" in html


def test_all_pages_pass_data_mode_from_main():
    import inspect
    import main
    src = inspect.getsource(main.run)
    assert src.count('data_mode="intraday" if realtime else "close"') >= 4   # 籌碼、形態、逆轟、自選股


def test_index_header_uses_same_update_stamp():
    import inspect
    from export import index_generator
    src = inspect.getsource(index_generator)
    assert "｜更新 {updated_stamp}" in src
