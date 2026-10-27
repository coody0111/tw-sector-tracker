import inspect

from export.heat_generator import generate, render


def _sector(rank, name, prev=None, status="上攻中"):
    m = [{"rank": 1, "stock_id": "3147", "stock_name": "大<綜>", "close": 100.0, "ret21": 26.5, "net5_lots": 1200}]
    return {"sector": name, "rank": rank, "prev_rank": prev, "score": 98.3 - rank, "n": 11, "ret5": 5.8, "ret21": 15.1,
            "inst_ratio": 0.36, "inst_breadth": 72.7, "above_ma20": 81.8, "limit_up": 1, "foreign_chg": None,
            "big_chg": 0.18, "status": status, "leaders": m, "members": m}


def _heat():
    top = [_sector(1, "軟體/雲端", 3), _sector(2, "電子製造服務", None), _sector(3, "通訊IC", 1, "拉回中")]
    return {"date": "2026-10-27", "compare_date": "2026-10-20", "sectors": top, "top": top,
            "heating": [top[1]], "cooling": [{"sector": "PCB", "prev_rank": 4, "rank": 12}]}


def test_heat_page_sections_and_rank_change():
    html = render(_heat())
    for text in ("族群熱度", "熱度排行 前 3", "剛轉熱", "退燒中", "PCB", "#4 → #12", "跟 2026-10-20 比"):
        assert text in html, text
    assert '<span class="up">▲2</span>' in html and '<span class="down">▼2</span>' in html and "新進" in html
    assert "大&lt;綜&gt;" in html and 'aria-controls="heat-m-0"' in html
    assert 'href="heat.html" aria-current="page"' in html


def test_heat_page_empty_and_generate(tmp_path):
    assert "資料不足" in render({"date": "2026-10-27", "top": []})
    out = tmp_path / "h.html"
    generate(_heat(), str(out))
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_main_publishes_heat_page_and_index_uses_heat():
    import main
    assert "generate_heat_html(payload[\"heat\"])" in inspect.getsource(main._run_and_publish)
    assert '"docs/heat.html"' in inspect.getsource(main._push_html)
    assert "heat=_latest_heat()" in inspect.getsource(main.run)
