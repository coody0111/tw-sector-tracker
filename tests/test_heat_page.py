"""族群熱度整合進族群績效（2026-11-02）：index 最上方的熱度區、推薦發布時只換那一段、舊 heat.html 轉址。"""
import inspect

from export.heat_generator import generate, render
from export.heat_section import END, START, patch_index, render_section


def _sector(rank, name, prev=None, status="上攻中"):
    m = [{"rank": 1, "stock_id": "3147", "stock_name": "大<綜>", "close": 100.0, "ret21": 26.5, "net5_lots": 1200}]
    return {"sector": name, "rank": rank, "prev_rank": prev, "score": 98.3 - rank, "n": 11, "ret5": 5.8, "ret21": 15.1,
            "inst_ratio": 0.36, "inst_breadth": 72.7, "above_ma20": 81.8, "limit_up": 1, "foreign_chg": None,
            "big_chg": 0.18, "status": status, "leaders": m, "members": m}


def _heat():
    top = [_sector(1, "雲端/系統整合", 3), _sector(2, "電子製造服務", None), _sector(3, "通訊IC", 1, "拉回中")]
    return {"date": "2026-10-27", "compare_date": "2026-10-20", "sectors": top, "top": top,
            "heating": [top[1]], "cooling": [{"sector": "PCB", "prev_rank": 4, "rank": 12}]}


def test_section_has_table_movers_and_rank_change():
    html = render_section(_heat())
    for text in ("族群熱度 前 3", "10/27 收盤資料", "進榜", "掉出", "PCB", "#4 → #12", "跟 2026-10-20 比", 'id="heat"'):
        assert text in html, text
    assert '<span class="up">▲2</span>' in html and '<span class="down">▼2</span>' in html and "新進" in html
    assert "大&lt;綜&gt;" in html and 'aria-controls="hx-m-0"' in html
    assert html.startswith(START) and html.endswith(END)
    assert "剛轉熱" not in html and "hot-grid" not in html          # 前 3 名卡片跟表格重複，拿掉


def test_section_empty_state():
    assert "還沒有熱度資料" in render_section(None) and "還沒有熱度資料" in render_section({"top": []})


def test_patch_inserts_into_old_index_then_replaces(tmp_path):
    p = tmp_path / "index.html"
    p.write_text('<html><body><div class="page-shell"><section>市場</section></div></body></html>', encoding="utf-8")
    assert patch_index(_heat(), str(p))
    first = p.read_text(encoding="utf-8")
    assert first.count(START) == 1 and first.index("族群熱度 前 3") < first.index("市場") and ".hx-table" in first
    assert patch_index({**_heat(), "top": _heat()["top"][:1]}, str(p))
    again = p.read_text(encoding="utf-8")
    assert again.count(START) == 1 and "族群熱度 前 1" in again and "族群熱度 前 3" not in again


def test_patch_leaves_unknown_or_missing_file(tmp_path):
    assert patch_index(_heat(), str(tmp_path / "none.html")) is False
    p = tmp_path / "x.html"
    p.write_text("<html></html>", encoding="utf-8")
    assert patch_index(_heat(), str(p)) is False and p.read_text(encoding="utf-8") == "<html></html>"


def test_old_heat_url_redirects(tmp_path):
    assert 'url=index.html#heat' in render(_heat())
    out = tmp_path / "h.html"
    generate(_heat(), str(out))
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_main_and_index_wiring():
    import main
    from export import index_generator
    src = inspect.getsource(main._run_and_publish)
    assert 'patch_index_heat(payload["heat"])' in src and 'generate_heat_html(payload["heat"])' in src
    assert "heat=_latest_heat()" in inspect.getsource(main.run)
    gen = inspect.getsource(index_generator.generate)
    assert "render_heat_section(heat)" in gen and "HEAT_SECTION_CSS" in gen and 'href="heat.html"' not in gen


def test_section_css_colors_up_down_inside_hx():
    from export.heat_section import HEAT_SECTION_CSS
    for rule in (".hx .up{color:var(--up)}", ".hx .down{color:var(--down)}", ".hx .muted{color:var(--ink-3)}"):
        assert rule in HEAT_SECTION_CSS                        # index 沒有全域 .up/.down（bug-reports 2026-11-02）
