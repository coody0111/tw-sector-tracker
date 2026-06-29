"""
產生 docs/patterns.html — 量價形態掃描頁
"""
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote as _q

_BULLISH = {"雙底", "三角突破", "60日突破", "VCP突破"}
_BEARISH = {"雙頂", "三角跌破"}
_NEUTRAL = {"箱型整理"}

_PATTERN_LABEL = {
    "雙底":    ("🟢", "#86efac"),
    "三角突破": ("🔺", "#86efac"),
    "60日突破": ("⚡", "#fbbf24"),
    "VCP突破":  ("🚀", "#a78bfa"),
    "雙頂":    ("🔴", "#fca5a5"),
    "三角跌破": ("🔻", "#fca5a5"),
    "箱型整理": ("📦", "#94a3b8"),
}

# 回測勝率（from backtest_patterns 結果）
_WIN_RATE = {
    "雙底": ("D+10", "43%", "-1.1%"),
    "雙頂": ("D+10", "60%", "+4.3%"),  # 做空方向
}


def _sparkline_svg(closes: list, width: int = 64, height: int = 22) -> str:
    """產生迷你折線圖 SVG。"""
    if not closes or len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    if hi == lo:
        return ""
    xs = [round(i / (len(closes) - 1) * width, 1) for i in range(len(closes))]
    ys = [round(height - (c - lo) / (hi - lo) * height, 1) for c in closes]
    pts = " ".join(f"{x},{y}" for x, y in zip(xs, ys))
    color = "#4ade80" if closes[-1] >= closes[0] else "#f87171"
    return (f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
            f"style='display:inline-block;vertical-align:middle'>"
            f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.5' "
            f"stroke-linejoin='round' stroke-linecap='round'/>"
            f"</svg>")


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


def _composite_badge(score: int | None) -> str:
    """0-100 綜合評分徽章，含填充色進度感。"""
    if score is None:
        return "<span style='color:#334155;font-size:.72rem'>─</span>"
    if score >= 75:
        color, bg = "#4ade80", "rgba(6,78,59,.35)"
    elif score >= 60:
        color, bg = "#86efac", "rgba(6,78,59,.2)"
    elif score >= 45:
        color, bg = "#fbbf24", "rgba(120,53,15,.2)"
    elif score >= 30:
        color, bg = "#fb923c", "rgba(120,53,15,.3)"
    else:
        color, bg = "#f87171", "rgba(127,29,29,.25)"
    return (f"<span style='background:{bg};color:{color};border:1px solid {color}55;"
            f"border-radius:6px;padding:2px 10px;font-size:.8rem;font-weight:800;"
            f"letter-spacing:.02em'>{score}</span>")


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


def _holder_cell(lv_pct: float | None, sh_streak: int) -> str:
    if lv_pct is None:
        return "<span style='color:#334155;font-size:.68rem'>─</span>"
    pct_color = "#f87171" if lv_pct >= 70 else ("#fbbf24" if lv_pct >= 50 else "#94a3b8")
    streak_str = ""
    if sh_streak > 0:
        streak_str = f"<span style='color:#f87171;font-size:.62rem'> ↑{sh_streak}w</span>"
    elif sh_streak < 0:
        streak_str = f"<span style='color:#4ade80;font-size:.62rem'> ↓{abs(sh_streak)}w</span>"
    return f"<span style='color:{pct_color};font-size:.75rem;font-weight:700'>{lv_pct:.0f}%{streak_str}</span>"


def _stock_row(r: dict) -> str:
    spark = _sparkline_svg(r.get("closes", []))
    comp = r.get("composite_score")
    lv_pct = r.get("lv12_15_pct")
    sh_streak = r.get("sh_streak", 0) or 0
    exch = r.get("exchange", "")
    exch_badge = (
        "<span style='color:#60a5fa;font-size:.6rem;border:1px solid #1e3a5f;border-radius:3px;padding:0 4px;margin-left:4px'>上市</span>" if exch == "TWSE"
        else "<span style='color:#a78bfa;font-size:.6rem;border:1px solid #3b1f6e;border-radius:3px;padding:0 4px;margin-left:4px'>上櫃</span>" if exch == "TPEx"
        else ""
    )
    price = r.get("close_price", "")
    price_str = f"{price:.2f}" if isinstance(price, (int, float)) else ""
    return (
        f"<tr data-exchange='{exch}' data-search='{r['stock_id']} {r['stock_name']} {r['meta_sector']}'>"
        f"<td style='color:#e2e8f0;font-weight:700'>{r['stock_id']}{exch_badge}</td>"
        f"<td style='color:#cbd5e1'>{r['stock_name']}</td>"
        f"<td style='color:#64748b;font-size:.75rem'>{r['meta_sector']}</td>"
        f"<td style='color:#e2e8f0'>{price_str}</td>"
        f"<td>{_pct(r['change_pct'])}</td>"
        f"<td style='color:#94a3b8'>{r['vol_ratio']:.1f}x</td>"
        f"<td>{_composite_badge(comp)}</td>"
        f"<td>{spark}</td>"
        f"<td>{_pattern_badges(r['patterns'])}</td>"
        f"<td>{_holder_cell(lv_pct, sh_streak)}</td>"
        f"<td>{_inst_label(r['inst_streak_foreign'], r['inst_streak_trust'])}</td>"
        f"</tr>"
    )


def _table_header() -> str:
    cols = ["代號", "名稱", "族群", "收盤", "漲跌", "量比", "評分", "走勢", "形態", "大戶", "法人"]
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


def _meta_hits_section(results: list[dict]) -> str:
    """族群型態熱區：badge 點擊展開該族群命中個股列表。"""
    # {meta: [(stock_id, stock_name, [patterns]}, ...]}
    meta_stocks: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        meta = r.get("meta_sector", "")
        if not meta:
            continue
        bullish = [p for p in r["patterns"] if p in _BULLISH]
        if bullish:
            meta_stocks[meta].append(r)

    if not meta_stocks:
        return ""

    ranked = sorted(meta_stocks.items(), key=lambda x: len(x[1]), reverse=True)

    def _color(n: int) -> str:
        if n >= 5: return "#f87171"
        if n >= 3: return "#fb923c"
        if n >= 2: return "#fbbf24"
        return "#94a3b8"

    badges = []
    panels = []
    for meta, stocks in ranked:
        n   = len(stocks)
        c   = _color(n)
        mid = _q(meta)

        # 展開面板：個股列表
        rows = []
        for r in sorted(stocks, key=lambda x: -(x.get("composite_score") or 0)):
            bullish_pats = [p for p in r["patterns"] if p in _BULLISH]
            pat_html = " ".join(
                f"<span style='color:{_PATTERN_LABEL.get(p,('','#94a3b8'))[1]};font-size:.65rem'>"
                f"{_PATTERN_LABEL.get(p,('','#94a3b8'))[0]}{p}</span>"
                for p in bullish_pats
            )
            chg = r["change_pct"]
            chg_color = "#f87171" if chg > 0 else "#4ade80"
            sign = "+" if chg > 0 else ""
            rows.append(
                f"<div style='display:flex;align-items:center;gap:10px;padding:3px 0;"
                f"border-bottom:1px solid #1e293b'>"
                f"<span style='color:#e2e8f0;font-weight:700;min-width:40px'>{r['stock_id']}</span>"
                f"<span style='color:#94a3b8;font-size:.78rem;min-width:60px'>{r['stock_name']}</span>"
                f"<span style='color:{chg_color};font-size:.78rem;min-width:52px'>{sign}{chg:.2f}%</span>"
                f"<span>{pat_html}</span>"
                f"</div>"
            )
        panels.append(
            f"<div id='mh-{mid}' style='display:none;background:#070b12;border:1px solid #1e293b;"
            f"border-radius:6px;padding:10px 14px;margin-top:6px;margin-bottom:4px'>"
            f"{''.join(rows)}</div>"
        )

        badges.append(
            f"<span onclick=\"var p=document.getElementById('mh-{mid}');"
            f"p.style.display=p.style.display==='none'?'block':'none'\" "
            f"style='display:inline-flex;align-items:center;gap:5px;cursor:pointer;"
            f"background:#0f1624;border:1px solid {c}55;border-radius:6px;"
            f"padding:4px 10px;color:{c};font-size:.78rem;font-weight:600;white-space:nowrap'>"
            f"{meta}<span style='background:{c}22;border-radius:4px;padding:0 5px;"
            f"font-size:.7rem'>{n}</span></span>"
        )

    return (
        "<div style='margin-bottom:20px'>"
        "<div style='color:#475569;font-size:.72rem;margin-bottom:6px;letter-spacing:.05em'>"
        "今日族群型態熱區（點擊展開個股）</div>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>"
        + "".join(badges)
        + "</div>"
        + "".join(panels)
        + "</div>"
        "<hr style='border-color:#1e293b;margin:0 0 20px'>"
    )


def generate(trade_date: date, results: list[dict], output_path: str) -> None:
    date_str = trade_date.strftime("%Y-%m-%d")

    # Classify
    bullish = [r for r in results if any(p in _BULLISH for p in r["patterns"])]
    bearish = [r for r in results if any(p in _BEARISH for p in r["patterns"])
               and not any(p in _BULLISH for p in r["patterns"])]
    neutral = [r for r in results if r["patterns"] == ["箱型整理"]]

    # Screener: bullish only, composite_score >= 55 or score >= 2, top 50 by composite
    screener = sorted(
        [r for r in bullish if (r.get("composite_score", 50) >= 55 or r["score"] >= 2)],
        key=lambda x: (x.get("composite_score") or 0, x["score"]),
        reverse=True,
    )[:50]

    # Pattern groups
    s60d  = [r for r in bullish if "60日突破"  in r["patterns"] and r["score"] >= 2]
    s_dbl = [r for r in bullish if "雙底"      in r["patterns"] and r["score"] >= 2]
    s_tri = [r for r in bullish if "三角突破"  in r["patterns"] and r["score"] >= 2]
    s_vcp = [r for r in bullish if "VCP突破"   in r["patterns"] and r["score"] >= 2]
    s_avoid = [r for r in bearish if r["score"] <= -2]
    s_box = sorted(neutral, key=lambda x: abs(x["score"]), reverse=True)

    body = "\n".join([
        _meta_hits_section(results),
        _section("做多候選 Screener",    screener, f"命中任一看多形態 · score ≥ 2 · Top 50 · {date_str}"),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("形態分區 — VCP量縮底部突破",   s_vcp),
        _section("形態分區 — 三角整理向上突破",  s_tri),
        _section("形態分區 — 雙底",              s_dbl),
        _section("形態分區 — 60日新高突破確認",  s60d),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("盤整觀察（箱型整理）", s_box, "尚未突破，等待方向"),
        "<hr style='border-color:#1e293b;margin:8px 0 24px'>",
        _section("避開清單",             s_avoid, "看空形態命中 · score ≤ -2"),
    ])

    # 回測統計摘要（120日回測，2026H1空頭環境供參考）
    backtest_note = (
        "<details style='margin-bottom:14px;color:#64748b;font-size:.72rem'>"
        "<summary style='cursor:pointer;color:#475569;letter-spacing:.04em'>▸ 回測統計參考（120日，2026H1）</summary>"
        "<div style='margin-top:8px;overflow-x:auto'>"
        "<table style='border-collapse:collapse;font-size:.72rem;min-width:420px'>"
        "<tr><th style='color:#475569;padding:3px 10px;text-align:left;border-bottom:1px solid #1e293b'>形態</th>"
        "<th style='color:#475569;padding:3px 10px'>樣本</th>"
        "<th style='color:#475569;padding:3px 10px'>D+3勝率</th>"
        "<th style='color:#475569;padding:3px 10px'>D+5勝率</th>"
        "<th style='color:#475569;padding:3px 10px'>D+10勝率</th>"
        "<th style='color:#475569;padding:3px 10px'>D+10均報</th></tr>"
        "<tr><td style='color:#e2e8f0;padding:3px 10px'>🟢雙底</td>"
        "<td style='color:#94a3b8;text-align:center'>5248</td>"
        "<td style='color:#f87171;text-align:center'>41%</td>"
        "<td style='color:#f87171;text-align:center'>40%</td>"
        "<td style='color:#f87171;text-align:center'>43%</td>"
        "<td style='color:#f87171;text-align:center'>-1.1%</td></tr>"
        "<tr><td style='color:#e2e8f0;padding:3px 10px'>🔺三角突破</td>"
        "<td style='color:#94a3b8;text-align:center'>3146</td>"
        "<td style='color:#94a3b8;text-align:center'>43%</td>"
        "<td style='color:#94a3b8;text-align:center'>45%</td>"
        "<td style='color:#94a3b8;text-align:center'>48%</td>"
        "<td style='color:#4ade80;text-align:center'>+2.9%</td></tr>"
        "<tr><td style='color:#e2e8f0;padding:3px 10px'>⚡60日突破</td>"
        "<td style='color:#94a3b8;text-align:center'>582</td>"
        "<td style='color:#f87171;text-align:center'>27%</td>"
        "<td style='color:#f87171;text-align:center'>25%</td>"
        "<td style='color:#f87171;text-align:center'>21%</td>"
        "<td style='color:#f87171;text-align:center'>-5.5%</td></tr>"
        "<tr><td style='color:#e2e8f0;padding:3px 10px'>🔻雙頂（做空）</td>"
        "<td style='color:#94a3b8;text-align:center'>905</td>"
        "<td style='color:#4ade80;text-align:center'>51%</td>"
        "<td style='color:#4ade80;text-align:center'>58%</td>"
        "<td style='color:#4ade80;text-align:center'>60%</td>"
        "<td style='color:#4ade80;text-align:center'>+4.3%</td></tr>"
        "<tr><td style='color:#e2e8f0;padding:3px 10px'>▽三角跌破（做空）</td>"
        "<td style='color:#94a3b8;text-align:center'>951</td>"
        "<td style='color:#4ade80;text-align:center'>47%</td>"
        "<td style='color:#4ade80;text-align:center'>49%</td>"
        "<td style='color:#4ade80;text-align:center'>55%</td>"
        "<td style='color:#4ade80;text-align:center'>+3.1%</td></tr>"
        "</table>"
        "<p style='color:#475569;margin-top:6px'>※ 2026H1 為空頭環境，看多形態勝率偏低屬正常；做空形態表現較佳。"
        "VCP 樣本數不足（新增形態），暫無統計。</p>"
        "</div></details>"
    )

    nav = (
        "<nav style='margin-bottom:12px;font-size:.8rem;color:#475569'>"
        "<a href='index.html' style='color:#60a5fa;text-decoration:none'>← 族群</a> · "
        "<a href='chips.html' style='color:#60a5fa;text-decoration:none'>籌碼</a> · "
        "<span style='color:#e2e8f0'>形態</span></nav>"
        + backtest_note
        + "<div style='margin-bottom:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
        "<button class='exch-btn active' data-exch='' onclick='applyFilters(this)'"
        " style='background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;"
        "padding:4px 14px;cursor:pointer;font-size:.78rem'>全部</button>"
        "<button class='exch-btn' data-exch='TWSE' onclick='applyFilters(this)'"
        " style='background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;"
        "padding:4px 14px;cursor:pointer;font-size:.78rem'>🏛 上市</button>"
        "<button class='exch-btn' data-exch='TPEx' onclick='applyFilters(this)'"
        " style='background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;"
        "padding:4px 14px;cursor:pointer;font-size:.78rem'>🏪 上櫃</button>"
        "<input id='s-search' type='text' placeholder='搜尋股號 / 名稱 / 族群…' oninput='applyFilters()'"
        " style='flex:1;min-width:160px;max-width:280px;background:#0f1624;color:#e2e8f0;"
        "border:1px solid #334155;border-radius:6px;padding:4px 10px;font-size:.78rem;outline:none'>"
        "</div>"
        "<script>"
        "let _exch='';"
        "function applyFilters(btn){"
        "if(btn&&btn.dataset.exch!==undefined){"
        "document.querySelectorAll('.exch-btn').forEach(b=>{b.style.background='transparent';b.style.color='#94a3b8';b.style.borderColor='#334155';b.classList.remove('active')});"
        "btn.style.background='#1e293b';btn.style.color='#e2e8f0';btn.style.borderColor='#475569';btn.classList.add('active');"
        "_exch=btn.dataset.exch;}"
        "const q=(document.getElementById('s-search').value||'').trim().toLowerCase();"
        "document.querySelectorAll('tbody tr[data-exchange]').forEach(tr=>{"
        "const exchOk=!_exch||tr.dataset.exchange===_exch;"
        "const srchOk=!q||(tr.dataset.search||'').toLowerCase().includes(q);"
        "tr.style.display=(exchOk&&srchOk)?'':'none'});}"
        "</script>"
    )

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
