"""
產生 docs/patterns.html — 量價形態掃描頁
"""
from datetime import date
from pathlib import Path

_BULLISH = {"雙底", "三角突破", "60日突破"}
_BEARISH = {"雙頂", "三角跌破"}
_NEUTRAL = {"箱型整理"}

_PATTERN_LABEL = {
    "雙底":   ("🟢", "#86efac"),
    "三角突破": ("🔺", "#86efac"),
    "60日突破": ("⚡", "#fbbf24"),
    "雙頂":   ("🔴", "#fca5a5"),
    "三角跌破": ("🔻", "#fca5a5"),
    "箱型整理": ("📦", "#94a3b8"),
}


def _pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    color = "#f87171" if v > 0 else ("#4ade80" if v < 0 else "#64748b")  # 台股：紅漲綠跌
    return f"<span style='color:{color}'>{sign}{v:.2f}%</span>"


def _score_badge(s: int) -> str:
    if s >= 4:
        color, bg = "#f87171", "rgba(127,29,29,.25)"
    elif s > 0:
        color, bg = "#fb923c", "rgba(120,53,15,.2)"
    elif s <= -4:
        color, bg = "#4ade80", "rgba(6,78,59,.25)"
    elif s < 0:
        color, bg = "#60a5fa", "rgba(30,58,138,.2)"
    else:
        color, bg = "#64748b", "rgba(30,41,59,.4)"
    return (f"<span style='background:{bg};color:{color};border:1px solid {color}33;"
            f"border-radius:4px;padding:1px 8px;font-size:.72rem;font-weight:700'>{s:+d}</span>")


def _pattern_badges(patterns: list[str]) -> str:
    parts = []
    for p in patterns:
        icon, color = _PATTERN_LABEL.get(p, ("", "#94a3b8"))
        parts.append(f"<span style='color:{color};border:1px solid {color}55;"
                     f"border-radius:4px;padding:1px 6px;font-size:.68rem'>{icon}{p}</span>")
    return " ".join(parts)


def _inst_label(f: int, t: int) -> str:
    parts = []
    if f > 0:
        parts.append(f"<span style='color:#f87171;font-size:.68rem'>外資+{f}日</span>")
    elif f < 0:
        parts.append(f"<span style='color:#4ade80;font-size:.68rem'>外資{f}日</span>")
    if t > 0:
        parts.append(f"<span style='color:#fbbf24;font-size:.68rem'>投信+{t}日</span>")
    elif t < 0:
        parts.append(f"<span style='color:#60a5fa;font-size:.68rem'>投信{t}日</span>")
    return " ".join(parts) or "<span style='color:#475569;font-size:.68rem'>─</span>"


def _stock_row(r: dict) -> str:
    return (
        f"<tr>"
        f"<td style='color:#e2e8f0;font-weight:700'>{r['stock_id']}</td>"
        f"<td style='color:#cbd5e1'>{r['stock_name']}</td>"
        f"<td style='color:#64748b;font-size:.75rem'>{r['meta_sector']}</td>"
        f"<td>{_pct(r['change_pct'])}</td>"
        f"<td style='color:#94a3b8'>{r['vol_ratio']:.1f}x</td>"
        f"<td>{_score_badge(r['score'])}</td>"
        f"<td>{_pattern_badges(r['patterns'])}</td>"
        f"<td>{_inst_label(r['inst_streak_foreign'], r['inst_streak_trust'])}</td>"
        f"</tr>"
    )


def _table_header() -> str:
    cols = ["代號", "名稱", "族群", "漲跌", "量比", "Score", "形態", "法人"]
    ths = "".join(f"<th style='color:#64748b;font-weight:500;padding:6px 10px;text-align:left;"
                  f"border-bottom:1px solid #1e293b'>{c}</th>" for c in cols)
    return f"<thead><tr>{ths}</tr></thead>"


def _section(title: str, rows: list[dict], subtitle: str = "") -> str:
    if not rows:
        return ""
    sub = f"<p style='color:#475569;font-size:.75rem;margin:2px 0 10px'>{subtitle}</p>" if subtitle else ""
    body = "".join(_stock_row(r) for r in rows)
    return (
        f"<section style='margin-bottom:32px'>"
        f"<h2 style='color:#94a3b8;font-size:.8rem;font-weight:600;letter-spacing:.1em;"
        f"text-transform:uppercase;margin:0 0 6px'>{title}</h2>"
        f"{sub}"
        f"<div style='overflow-x:auto'>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"{_table_header()}"
        f"<tbody style='font-size:.8rem'>{body}</tbody>"
        f"</table></div></section>"
    )


def generate(trade_date: date, results: list[dict], output_path: str) -> None:
    date_str = trade_date.strftime("%Y-%m-%d")

    # Classify
    bullish = [r for r in results if any(p in _BULLISH for p in r["patterns"])]
    bearish = [r for r in results if any(p in _BEARISH for p in r["patterns"])
               and not any(p in _BULLISH for p in r["patterns"])]
    neutral = [r for r in results if r["patterns"] == ["箱型整理"]]

    # Screener: bullish only, score >= 2, top 50
    screener = sorted([r for r in bullish if r["score"] >= 2],
                      key=lambda x: x["score"], reverse=True)[:50]

    # Pattern groups
    s60d  = [r for r in bullish if "60日突破"  in r["patterns"] and r["score"] >= 2]
    s_dbl = [r for r in bullish if "雙底"     in r["patterns"] and r["score"] >= 2]
    s_tri = [r for r in bullish if "三角突破"  in r["patterns"] and r["score"] >= 2]
    s_avoid = [r for r in bearish if r["score"] <= -2]
    s_box = sorted(neutral, key=lambda x: abs(x["score"]), reverse=True)

    body = "\n".join([
        _section("做多候選 Screener",    screener, f"命中任一看多形態 · score ≥ 2 · Top 50 · {date_str}"),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("形態分區 — 60日新高突破確認", s60d),
        _section("形態分區 — 雙底",             s_dbl),
        _section("形態分區 — 三角整理向上突破", s_tri),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("盤整觀察（箱型整理）", s_box, "尚未突破，等待方向"),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("避開清單",             s_avoid, "看空形態命中 · score ≤ -2"),
    ])

    nav = ("<nav style='margin-bottom:20px;font-size:.8rem;color:#475569'>"
           "<a href='index.html' style='color:#60a5fa;text-decoration:none'>← 族群</a> · "
           "<a href='chips.html' style='color:#60a5fa;text-decoration:none'>籌碼</a> · "
           "<span style='color:#e2e8f0'>形態</span></nav>")

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>形態掃描 {date_str}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0b0f18;color:#e2e8f0;font-family:system-ui,sans-serif;padding:12px 20px}}
a{{color:#60a5fa}}
tbody tr:hover{{background:#0f1624}}
tbody td{{padding:5px 10px;border-bottom:1px solid #1e293b}}
</style>
</head>
<body>
<h1 style="color:#94a3b8;font-size:1rem;font-weight:600;margin-bottom:4px">形態掃描</h1>
{nav}
{body}
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
