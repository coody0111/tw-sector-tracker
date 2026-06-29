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
            f"border-radius:6px;padding:2px 10px;font-size:.72rem;font-weight:800;"
            f"letter-spacing:.02em'>{score}</span>")


def _pattern_badges(patterns: list[str]) -> str:
    parts = []
    for p in patterns:
        icon, color = _PATTERN_LABEL.get(p, ("", "#94a3b8"))
        parts.append(f"<span style='color:{color};border:1px solid {color}55;"
                     f"border-radius:4px;padding:1px 6px;font-size:.7rem'>{icon}{p}</span>")
    return " ".join(parts)


def _inst_label(f: int, t: int) -> str:
    parts = []
    if f > 0:
        parts.append(f"<span style='color:#f87171;font-size:.7rem'>外資+{f}日</span>")
    elif f < 0:
        parts.append(f"<span style='color:#4ade80;font-size:.7rem'>外資{f}日</span>")
    if t > 0:
        parts.append(f"<span style='color:#fbbf24;font-size:.7rem'>投信+{t}日</span>")
    elif t < 0:
        parts.append(f"<span style='color:#60a5fa;font-size:.7rem'>投信{t}日</span>")
    return " ".join(parts) or "<span style='color:#475569;font-size:.7rem'>─</span>"


def _holder_cell(lv_pct: float | None, sh_streak: int) -> str:
    if lv_pct is None:
        return "<span style='color:#334155;font-size:.7rem'>─</span>"
    pct_color = "#f87171" if lv_pct >= 70 else ("#fbbf24" if lv_pct >= 50 else "#94a3b8")
    streak_str = ""
    if sh_streak > 0:
        streak_str = f"<span style='color:#f87171;font-size:.7rem'> ↑{sh_streak}w</span>"
    elif sh_streak < 0:
        streak_str = f"<span style='color:#4ade80;font-size:.7rem'> ↓{abs(sh_streak)}w</span>"
    return f"<span style='color:{pct_color};font-size:.72rem;font-weight:700'>{lv_pct:.0f}%{streak_str}</span>"


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
        f"<td style='color:#64748b;font-size:.72rem'>{r['meta_sector']}</td>"
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


_BACKTEST_NOTE = (
    "<div class='pt-section'>"
    "<div class='pt-title'>回測統計參考（120日，2026H1）</div>"
    "<div style='overflow-x:auto'>"
    "<table class='pt'>"
    "<thead><tr><th>形態</th><th>樣本</th><th>D+3勝率</th><th>D+5勝率</th><th>D+10勝率</th><th>D+10均報</th></tr></thead>"
    "<tbody>"
    "<tr><td>🟢雙底</td><td style='text-align:center'>5248</td>"
    "<td style='text-align:center;color:#f87171'>41%</td><td style='text-align:center;color:#f87171'>40%</td>"
    "<td style='text-align:center;color:#f87171'>43%</td><td style='text-align:center;color:#f87171'>-1.1%</td></tr>"
    "<tr><td>🔺三角突破</td><td style='text-align:center'>3146</td>"
    "<td style='text-align:center;color:#94a3b8'>43%</td><td style='text-align:center;color:#94a3b8'>45%</td>"
    "<td style='text-align:center;color:#94a3b8'>48%</td><td style='text-align:center;color:#4ade80'>+2.9%</td></tr>"
    "<tr><td>⚡60日突破</td><td style='text-align:center'>582</td>"
    "<td style='text-align:center;color:#f87171'>27%</td><td style='text-align:center;color:#f87171'>25%</td>"
    "<td style='text-align:center;color:#f87171'>21%</td><td style='text-align:center;color:#f87171'>-5.5%</td></tr>"
    "<tr><td>🔻雙頂（做空）</td><td style='text-align:center'>905</td>"
    "<td style='text-align:center;color:#4ade80'>51%</td><td style='text-align:center;color:#4ade80'>58%</td>"
    "<td style='text-align:center;color:#4ade80'>60%</td><td style='text-align:center;color:#4ade80'>+4.3%</td></tr>"
    "<tr><td>▽三角跌破（做空）</td><td style='text-align:center'>951</td>"
    "<td style='text-align:center;color:#4ade80'>47%</td><td style='text-align:center;color:#4ade80'>49%</td>"
    "<td style='text-align:center;color:#4ade80'>55%</td><td style='text-align:center;color:#4ade80'>+3.1%</td></tr>"
    "</tbody></table>"
    "</div>"
    "<p style='color:#475569;font-size:.7rem;margin-top:8px'>※ 2026H1 為空頭環境，看多形態勝率偏低屬正常；VCP 樣本數不足，暫無統計。</p>"
    "</div>"
)

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0f18;color:#e2e8f0;font-family:system-ui,sans-serif;padding:12px 20px}
a{color:#60a5fa}
.nav-links{display:flex;gap:8px;margin:8px 0 0}
.nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid #1e293b;color:#64748b;text-decoration:none;transition:all .15s}
.nav-link:hover{border-color:#475569;color:#94a3b8}
.nav-link.active{border-color:#475569;color:#e2e8f0;background:#141c2e}
.filter-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0 0}
.exch-btn{background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:.72rem;transition:all .15s}
.exch-btn.active{background:#1e293b;color:#e2e8f0;border-color:#475569}
.s-search{flex:1;min-width:160px;max-width:260px;background:#0f1624;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 10px;font-size:.78rem;outline:none}
.tab-bar{display:flex;gap:2px;margin:14px 0 0;border-bottom:1px solid #1e293b}
.tab-btn{font-size:.8rem;padding:9px 16px;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;background:none;color:#64748b;cursor:pointer;font-weight:600;letter-spacing:.02em;transition:all .15s;border-radius:4px 4px 0 0}
.tab-btn:hover{color:#94a3b8;background:#0f1624}
.tab-btn.active{color:#e2e8f0;border-bottom-color:#60a5fa;background:#0f1624}
.tab-panel{display:none;padding-top:16px}
.tab-panel.active{display:block}
tbody tr:hover{background:#0f1624}
tbody td{padding:5px 10px;border-bottom:1px solid #1e293b}
.pt-section{background:#0f1624;border:1px solid #1e293b;border-radius:10px;padding:14px 16px;margin-bottom:16px}
.pt-title{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:10px}
.pt{width:100%;border-collapse:collapse;font-size:.8rem}
.pt th{text-align:left;padding:5px 10px;font-size:.65rem;color:#334155;text-transform:uppercase;border-bottom:1px solid #1e293b}
.pt td{padding:7px 10px;border-bottom:1px solid #0b0f18}
.pt tr:last-child td{border-bottom:none}
.pt tr:hover td{background:#141c2e}
@media(max-width:540px){body{padding:10px}.tab-btn{padding:8px 10px;font-size:.72rem}}
"""

_TAB_JS = """
<script>
function switchTab(id){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelector('.tab-btn[data-tab="'+id+'"]').classList.add('active');
  document.getElementById(id).classList.add('active');
  history.replaceState(null,'','#'+id);
}
const _tabs=['tab-screener','tab-patterns','tab-meta','tab-avoid'];
const _h=location.hash.slice(1);
switchTab(_tabs.includes(_h)?_h:'tab-screener');
let _exch='';
function applyFilters(btn){
  if(btn&&btn.dataset.exch!==undefined){
    document.querySelectorAll('.exch-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    _exch=btn.dataset.exch;
  }
  const q=(document.getElementById('s-search').value||'').trim().toLowerCase();
  document.querySelectorAll('tbody tr[data-exchange]').forEach(tr=>{
    const exchOk=!_exch||tr.dataset.exchange===_exch;
    const srchOk=!q||(tr.dataset.search||'').toLowerCase().includes(q);
    tr.style.display=(exchOk&&srchOk)?'':'none';
  });
}
</script>
"""


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
    s60d   = [r for r in bullish if "60日突破"  in r["patterns"] and r["score"] >= 2]
    s_dbl  = [r for r in bullish if "雙底"      in r["patterns"] and r["score"] >= 2]
    s_tri  = [r for r in bullish if "三角突破"  in r["patterns"] and r["score"] >= 2]
    s_vcp  = [r for r in bullish if "VCP突破"   in r["patterns"] and r["score"] >= 2]
    s_avoid = [r for r in bearish if r["score"] <= -2]
    s_box  = sorted(neutral, key=lambda x: abs(x["score"]), reverse=True)

    # Tab panels
    tab1 = _section("做多候選 Screener", screener,
                     f"命中任一看多形態 · score ≥ 2 · Top 50 · {date_str}")

    tab2 = "\n".join([
        _section("🚀 VCP 量縮底部突破",  s_vcp),
        _section("🔺 三角整理向上突破",  s_tri),
        _section("🟢 雙底",              s_dbl),
        _section("⚡ 60日新高突破確認",  s60d),
    ])

    tab3 = _meta_hits_section(results)

    tab4 = "\n".join([
        _section("📉 避開清單", s_avoid, "看空形態命中 · score ≤ -2"),
        "<div style='height:16px'></div>",
        _section("⬜ 盤整觀察（箱型整理）", s_box, "尚未突破，等待方向"),
        "<div style='height:16px'></div>",
        _BACKTEST_NOTE,
    ])

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>形態掃描 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div style="color:#94a3b8;font-size:1rem;font-weight:600;margin-bottom:2px">形態掃描
  <span style="color:#475569;font-size:.78rem;font-weight:400;margin-left:8px">{date_str}</span>
</div>
<div class="nav-links">
  <a class="nav-link" href="index.html">族群績效</a>
  <a class="nav-link" href="chips.html">籌碼分析</a>
  <a class="nav-link active" href="patterns.html">形態掃描</a>
</div>
<div class="filter-bar">
  <button class="exch-btn active" data-exch="" onclick="applyFilters(this)">全部</button>
  <button class="exch-btn" data-exch="TWSE" onclick="applyFilters(this)">🏛 上市</button>
  <button class="exch-btn" data-exch="TPEx" onclick="applyFilters(this)">🏪 上櫃</button>
  <input id="s-search" class="s-search" type="text" placeholder="搜尋股號 / 名稱 / 族群…" oninput="applyFilters()">
</div>
<div class="tab-bar">
  <button class="tab-btn" data-tab="tab-screener" onclick="switchTab('tab-screener')">🔥 做多候選</button>
  <button class="tab-btn" data-tab="tab-patterns" onclick="switchTab('tab-patterns')">📈 形態分區</button>
  <button class="tab-btn" data-tab="tab-meta"     onclick="switchTab('tab-meta')">📊 META 熱區</button>
  <button class="tab-btn" data-tab="tab-avoid"    onclick="switchTab('tab-avoid')">📉 避開 / 觀察</button>
</div>

<div class="tab-panel" id="tab-screener">
  {tab1}
</div>
<div class="tab-panel" id="tab-patterns">
  {tab2}
</div>
<div class="tab-panel" id="tab-meta">
  {tab3}
</div>
<div class="tab-panel" id="tab-avoid">
  {tab4}
</div>

{_TAB_JS}
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
