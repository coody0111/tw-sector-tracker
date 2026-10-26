from datetime import date

import pandas as pd

from export.ui_theme import NAV_PAGES, SHARED_CSS, render_topbar


def test_topbar_matches_index_layout():
    """2026-10-26 Cody：各分頁頁首照族群績效（index.html）：TW SECTOR TRACKER 小字＋頁名、日期靠右、導覽。"""
    html = render_topbar("個股推薦", "recommend.html", "資料日 <b>2026-10-22</b>")
    assert '<span class="ui-kicker">TW SECTOR TRACKER</span><h1 class="ui-title">個股推薦</h1>' in html
    assert html.index('class="ui-date"') < html.index('class="ui-nav"')
    for href, label in NAV_PAGES:
        assert f'href="{href}"' in html and label in html
    assert ".ui-date{margin-left:auto" in SHARED_CSS and "--ui-serif" in SHARED_CSS


def test_watchlist_uses_shared_topbar_with_all_pages(tmp_path):
    from export.watchlist_generator import generate
    out = tmp_path / "w.html"
    generate(date(2026, 10, 22), pd.DataFrame([{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "晶圓"}]),
             pd.DataFrame(), output_path=str(out))
    html = out.read_text(encoding="utf-8")
    assert 'class="ui-topbar"' in html and 'href="watchlist.html" aria-current="page"' in html
    assert 'href="recommend.html"' in html and "族群總覽" not in html
