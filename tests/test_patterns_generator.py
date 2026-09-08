# tests/test_patterns_generator.py
from datetime import date
from export.patterns_generator import _gap_badge, generate

_SAMPLE = [
    {
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
        "change_pct": 2.1, "vol_ratio": 2.3, "score": 6,
        "patterns": ["雙底", "60日突破"],
        "inst_streak_foreign": 3, "inst_streak_trust": 1,
    },
    {
        "stock_id": "3034", "stock_name": "聯詠", "meta_sector": "IC設計",
        "change_pct": -1.5, "vol_ratio": 1.1, "score": -4,
        "patterns": ["雙頂"],
        "inst_streak_foreign": -2, "inst_streak_trust": 0,
    },
    {
        "stock_id": "2454", "stock_name": "聯發科", "meta_sector": "IC設計",
        "change_pct": 0.3, "vol_ratio": 0.9, "score": 1,
        "patterns": ["箱型整理"],
        "inst_streak_foreign": 1, "inst_streak_trust": 0,
    },
]

def test_generate_creates_file(tmp_path):
    out = tmp_path / "patterns.html"
    generate(date(2026, 6, 27), _SAMPLE, str(out))
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "台積電" in html
    assert "2330" in html


def test_generate_sections_present(tmp_path):
    out = tmp_path / "patterns.html"
    generate(date(2026, 6, 27), _SAMPLE, str(out))
    html = out.read_text(encoding="utf-8")
    assert "做多候選" in html
    assert "避開清單" in html
    assert "箱型整理" in html or "盤整觀察" in html


def test_generate_screener_only_shows_bullish(tmp_path):
    out = tmp_path / "patterns.html"
    generate(date(2026, 6, 27), _SAMPLE, str(out))
    html = out.read_text(encoding="utf-8")
    # Screener tab div should contain 台積電 (bullish, score 6)
    screener_section = html.split('id="tab-screener"')[1].split('id="tab-patterns"')[0]
    assert "2330" in screener_section


def test_gap_badge_renders_percent_volume_and_fill_state():
    html = _gap_badge({
        "gap_direction": "up",
        "gap_pct": 3.25,
        "gap_volume_confirmed": True,
        "gap_intraday_fill": "盤中未回補",
    })
    assert "向上跳空 3.25%" in html
    assert "量能確認" in html
    assert "盤中未回補" in html
