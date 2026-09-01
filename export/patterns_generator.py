"""
產生 docs/patterns.html — 量價形態掃描頁
"""
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote as _q

_BULLISH = {"雙底", "頭肩底", "收斂三角", "上升三角", "下降楔型", "多頭拐點", "VCP突破"}
_BEARISH = {"雙頂", "三角跌破"}
_NEUTRAL = {"箱型整理"}

_PATTERN_LABEL = {
    "雙底":    ("", "#86efac"),
    "頭肩底":  ("", "#34d399"),
    "收斂三角": ("", "#86efac"),
    "上升三角": ("", "#6ee7b7"),
    "下降楔型": ("", "#67e8f9"),
    "多頭拐點": ("", "#F0BB55"),
    "VCP突破":  ("", "#a78bfa"),
    "雙頂":    ("", "#fca5a5"),
    "三角跌破": ("", "#fca5a5"),
    "箱型整理": ("", "#98A0B4"),
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
    color = "#37B25C" if closes[-1] >= closes[0] else "#E6432F"
    return (f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
            f"style='display:inline-block;vertical-align:middle'>"
            f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.5' "
            f"stroke-linejoin='round' stroke-linecap='round'/>"
            f"</svg>")


def _pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    color = "#E6432F" if v > 0 else ("#37B25C" if v < 0 else "#636B80")  # 台股：紅漲綠跌
    return f"<span style='color:{color}'>{sign}{v:.2f}%</span>"


def _score_badge(s: int) -> str:
    if s >= 4:
        color, bg = "#E6432F", "rgba(127,29,29,.25)"
    elif s > 0:
        color, bg = "#fb923c", "rgba(120,53,15,.2)"
    elif s <= -4:
        color, bg = "#37B25C", "rgba(6,78,59,.25)"
    elif s < 0:
        color, bg = "#F0BB55", "rgba(30,58,138,.2)"
    else:
        color, bg = "#636B80", "rgba(30,41,59,.4)"
    return (f"<span style='background:{bg};color:{color};border:1px solid {color}33;"
            f"border-radius:4px;padding:1px 8px;font-size:.72rem;font-weight:700'>{s:+d}</span>")


def _composite_badge(score: int | None) -> str:
    """0-100 綜合評分徽章，含填充色進度感。"""
    if score is None:
        return "<span style='color:#293346;font-size:.72rem'>─</span>"
    if score >= 75:
        color, bg = "#37B25C", "rgba(6,78,59,.35)"
    elif score >= 60:
        color, bg = "#86efac", "rgba(6,78,59,.2)"
    elif score >= 45:
        color, bg = "#F0BB55", "rgba(120,53,15,.2)"
    elif score >= 30:
        color, bg = "#fb923c", "rgba(120,53,15,.3)"
    else:
        color, bg = "#E6432F", "rgba(127,29,29,.25)"
    return (f"<span style='background:{bg};color:{color};border:1px solid {color}55;"
            f"border-radius:6px;padding:2px 10px;font-size:.72rem;font-weight:800;"
            f"letter-spacing:.02em'>{score}</span>")


def _pattern_badges(patterns: list[str]) -> str:
    parts = []
    for p in patterns:
        icon, color = _PATTERN_LABEL.get(p, ("", "#98A0B4"))
        parts.append(f"<span style='color:{color};border:1px solid {color}55;"
                     f"border-radius:4px;padding:1px 6px;font-size:.7rem'>{icon}{p}</span>")
    return " ".join(parts)


def _inst_label(f: int, t: int) -> str:
    parts = []
    if f > 0:
        parts.append(f"<span style='color:#E6432F;font-size:.7rem'>外資+{f}日</span>")
    elif f < 0:
        parts.append(f"<span style='color:#37B25C;font-size:.7rem'>外資{f}日</span>")
    if t > 0:
        parts.append(f"<span style='color:#F0BB55;font-size:.7rem'>投信+{t}日</span>")
    elif t < 0:
        parts.append(f"<span style='color:#F0BB55;font-size:.7rem'>投信{t}日</span>")
    return " ".join(parts) or "<span style='color:#37435C;font-size:.7rem'>─</span>"


def _holder_cell(lv_pct: float | None, sh_streak: int) -> str:
    if lv_pct is None:
        return "<span style='color:#293346;font-size:.7rem'>─</span>"
    pct_color = "#E6432F" if lv_pct >= 70 else ("#F0BB55" if lv_pct >= 50 else "#98A0B4")
    streak_str = ""
    if sh_streak > 0:
        streak_str = f"<span style='color:#E6432F;font-size:.7rem'> ↑{sh_streak}w</span>"
    elif sh_streak < 0:
        streak_str = f"<span style='color:#37B25C;font-size:.7rem'> ↓{abs(sh_streak)}w</span>"
    return f"<span style='color:{pct_color};font-size:.72rem;font-weight:700'>{lv_pct:.0f}%{streak_str}</span>"


def _signal_info_cell(r: dict) -> str:
    """訊號日 + 持倉天數 + 進/停/標價位 + R:R。"""
    anchor = r.get("anchor")
    stop   = r.get("stop")
    target = r.get("target")
    rr     = r.get("rr")
    days   = r.get("days_held")
    sig_dt = r.get("signal_date", "")[:10] if r.get("signal_date") else ""

    if anchor is None:
        return "<span style='color:#293346;font-size:.7rem'>─</span>"

    rr_color = "#37B25C" if (rr or 0) >= 2 else ("#F0BB55" if (rr or 0) >= 1 else "#E6432F")
    days_str = f"<span style='color:#636B80;font-size:.65rem'>D+{days}</span> " if days is not None else ""
    date_str = f"<span style='color:#37435C;font-size:.65rem'>{sig_dt}</span><br>" if sig_dt else ""
    levels = (
        f"<span style='font-size:.68rem'>"
        f"進<b style='color:#DADFE8'>{anchor:.2f}</b> "
        f"停<b style='color:#E6432F'>{stop:.2f}</b> "
        f"標<b style='color:#37B25C'>{target:.2f}</b>"
        f"</span>"
    )
    rr_badge = (
        f"<span style='color:{rr_color};font-size:.7rem;font-weight:700;margin-left:4px'>"
        f"R:{rr:.1f}</span>"
    ) if rr is not None else ""

    return f"{date_str}{days_str}{levels}{rr_badge}"


def _stock_row(r: dict) -> str:
    spark = _sparkline_svg(r.get("closes", []))
    comp = r.get("composite_score")
    lv_pct = r.get("lv12_15_pct")
    sh_streak = r.get("sh_streak", 0) or 0
    exch = r.get("exchange", "")
    exch_badge = (
        "<span style='color:#9bc7ff;font-size:.6rem;border:1px solid #416d9f;border-radius:3px;padding:0 4px;margin-left:4px'>上市</span>" if exch == "TWSE"
        else "<span style='color:#cabaff;font-size:.6rem;border:1px solid #6e5999;border-radius:3px;padding:0 4px;margin-left:4px'>上櫃</span>" if exch == "TPEx"
        else ""
    )
    price = r.get("close_price", "")
    price_str = f"{price:.2f}" if isinstance(price, (int, float)) else ""
    return (
        f"<tr data-exchange='{exch}' data-search='{r['stock_id']} {r['stock_name']} {r['meta_sector']}'>"
        f"<td style='color:#DADFE8;font-weight:700'>{r['stock_id']}{exch_badge}</td>"
        f"<td style='color:#DADFE8'>{r['stock_name']}</td>"
        f"<td style='color:#98A0B4;font-size:.72rem'>{r['meta_sector']}</td>"
        f"<td style='color:#DADFE8'>{price_str}</td>"
        f"<td>{_pct(r['change_pct'])}</td>"
        f"<td style='color:#98A0B4'>{r['vol_ratio']:.1f}x</td>"
        f"<td>{_composite_badge(comp)}</td>"
        f"<td>{spark}</td>"
        f"<td style='white-space:normal'>{_pattern_badges(r['patterns'])}</td>"
        f"<td style='white-space:nowrap'>{_signal_info_cell(r)}</td>"
        f"<td>{_holder_cell(lv_pct, sh_streak)}</td>"
        f"<td>{_inst_label(r['inst_streak_foreign'], r['inst_streak_trust'])}</td>"
        f"</tr>"
    )


def _table_header() -> str:
    cols = ["代號", "名稱", "族群", "收盤", "漲跌", "量比", "評分", "走勢", "形態", "訊號/進出價", "大戶", "法人"]
    ths = "".join(f"<th style='color:#636B80;font-weight:500;padding:6px 10px;text-align:left;"
                  f"border-bottom:1px solid #293346;white-space:nowrap'>{c}</th>" for c in cols)
    return f"<thead><tr>{ths}</tr></thead>"


def _section(title: str, rows: list[dict], subtitle: str = "") -> str:
    if not rows:
        return ""
    sub = f"<p style='color:#37435C;font-size:.75rem;margin:2px 0 10px'>{subtitle}</p>" if subtitle else ""
    body = "".join(_stock_row(r) for r in rows)
    return (
        f"<section style='margin-bottom:32px'>"
        f"<h2 style='color:#98A0B4;font-size:.8rem;font-weight:600;letter-spacing:.1em;"
        f"text-transform:uppercase;margin:0 0 6px'>{title}</h2>"
        f"{sub}"
        f"<div style='overflow-x:auto'>"
        f"<table style='width:100%;min-width:760px;border-collapse:collapse'>"
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
        if n >= 5: return "#E6432F"
        if n >= 3: return "#fb923c"
        if n >= 2: return "#F0BB55"
        return "#98A0B4"

    badges = []
    panels = []
    for meta, stocks in ranked:
        n   = len(stocks)
        c   = _color(n)
        mid = _q(meta)

        # 展開面板：個股列表（table 確保欄位對齊）
        rows = []
        for r in sorted(stocks, key=lambda x: -(x.get("composite_score") or 0)):
            bullish_pats = [p for p in r["patterns"] if p in _BULLISH]
            pat_html = " ".join(
                f"<span style='color:{_PATTERN_LABEL.get(p,('','#98A0B4'))[1]};font-size:.65rem'>"
                f"{_PATTERN_LABEL.get(p,('','#98A0B4'))[0]}{p}</span>"
                for p in bullish_pats
            )
            chg = r["change_pct"]
            chg_color = "#E6432F" if chg > 0 else "#37B25C"
            sign = "+" if chg > 0 else ""
            price = r.get("close_price")
            price_str = (f"{price:.2f}" if price and price < 10 else
                         f"{price:.1f}" if price and price < 100 else
                         f"{int(price)}" if price else "─")
            rows.append(
                f"<tr style='border-bottom:1px solid #293346'>"
                f"<td style='color:#DADFE8;font-weight:700;padding:4px 8px 4px 0;white-space:nowrap'>{r['stock_id']}</td>"
                f"<td style='color:#98A0B4;font-size:.78rem;padding:4px 8px;white-space:nowrap'>{r['stock_name']}</td>"
                f"<td style='color:#DADFE8;font-size:.78rem;font-weight:600;padding:4px 8px;white-space:nowrap'>{price_str}</td>"
                f"<td style='color:{chg_color};font-size:.78rem;padding:4px 8px;white-space:nowrap'>{sign}{chg:.2f}%</td>"
                f"<td style='padding:4px 0'>{pat_html}</td>"
                f"</tr>"
            )
        panels.append(
            f"<div id='mh-{mid}' style='display:none;background:#080B12;border:1px solid #293346;"
            f"border-radius:6px;padding:10px 14px;margin-top:6px;margin-bottom:4px'>"
            f"<table style='width:100%;border-collapse:collapse'>{''.join(rows)}</table>"
            f"</div>"
        )

        badges.append(
            f"<span onclick=\"var p=document.getElementById('mh-{mid}');"
            f"p.style.display=p.style.display==='none'?'block':'none'\" "
            f"style='display:inline-flex;align-items:center;gap:5px;cursor:pointer;"
            f"background:#0F1420;border:1px solid {c}55;border-radius:6px;"
            f"padding:4px 10px;color:{c};font-size:.78rem;font-weight:600;white-space:nowrap'>"
            f"{meta}<span style='background:{c}22;border-radius:4px;padding:0 5px;"
            f"font-size:.7rem'>{n}</span></span>"
        )

    return (
        "<div style='margin-bottom:20px'>"
        "<div style='color:#37435C;font-size:.72rem;margin-bottom:6px;letter-spacing:.05em'>"
        "今日族群型態熱區（點擊展開個股）</div>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>"
        + "".join(badges)
        + "</div>"
        + "".join(panels)
        + "</div>"
        "<hr style='border-color:#293346;margin:0 0 20px'>"
    )


def _backtest_row(name: str, n: int, w3: int, w5: int, w10: int, ret10: float) -> str:
    """生成一列回測資料，自動計算 2R 期望值（1:2 風險報酬比）。"""
    def _wc(w: int) -> str:
        c = "#37B25C" if w >= 50 else ("#98A0B4" if w >= 40 else "#E6432F")
        return f"<td style='text-align:center;color:{c}'>{w}%</td>"
    ret_c = "#37B25C" if ret10 > 0 else "#E6432F"
    sign = "+" if ret10 > 0 else ""
    ev2r = 3 * (w10 / 100) - 1          # 2R 期望值 (1:2 RR)
    ev_c = "#37B25C" if ev2r > 0 else "#E6432F"
    ev_sign = "+" if ev2r > 0 else ""
    return (
        f"<tr><td>{name}</td>"
        f"<td style='text-align:center;color:#636B80'>{n:,}</td>"
        f"{_wc(w3)}{_wc(w5)}{_wc(w10)}"
        f"<td style='text-align:center;color:{ret_c}'>{sign}{ret10:.1f}%</td>"
        f"<td style='text-align:center;color:{ev_c};font-weight:700'>{ev_sign}{ev2r:.2f}R</td>"
        f"</tr>"
    )


_BACKTEST_NOTE = (
    "<div class='pt-section'>"
    "<div class='pt-title'>回測統計參考（120日，2026H1）</div>"
    "<div style='overflow-x:auto'>"
    "<table class='pt'>"
    "<thead><tr>"
    "<th>形態</th><th style='text-align:center'>樣本</th>"
    "<th style='text-align:center'>D+3勝率</th><th style='text-align:center'>D+5勝率</th>"
    "<th style='text-align:center'>D+10勝率</th><th style='text-align:center'>D+10均報</th>"
    "<th style='text-align:center' title='1:2風險報酬比期望值 = 3×勝率-1，>0表示正期望'>2R期望值</th>"
    "</tr></thead>"
    "<tbody>"
    + _backtest_row("雙底",           5248, 41, 40, 43, -1.1)
    + _backtest_row("三角突破",        3146, 43, 45, 48, +2.9)
    + _backtest_row("多頭拐點",          582, 27, 25, 21, -5.5)
    + _backtest_row("雙頂（做空）",     905, 51, 58, 60, +4.3)
    + _backtest_row("▽三角跌破（做空）",  951, 47, 49, 55, +3.1)
    + "</tbody></table>"
    "</div>"
    "<p style='color:#37435C;font-size:.7rem;margin-top:8px'>"
    "※ 2R期望值 = 3×D+10勝率 − 1，以 1:2 風險報酬比計算。>0 表示長期正期望；勝率需 >33.3% 才能維持正期望。"
    "<br>※ 2026H1 為空頭環境，看多形態勝率偏低屬正常；VCP 樣本數不足，暫無統計。</p>"
    "</div>"
)

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080B12;color:#DADFE8;font-family:system-ui,sans-serif;padding:12px 20px}
a{color:#F0BB55}
.page-head{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
.nav-links{display:flex;align-items:center;gap:8px;margin-left:auto;white-space:nowrap}
.nav-link{display:inline-flex;align-items:center;min-height:32px;font-family:"Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;font-size:.78rem;font-weight:600;padding:5px 14px;border-radius:6px;border:1px solid #293346;color:#636B80;text-decoration:none;transition:color .15s,border-color .15s,background .15s}
.nav-link:hover{border-color:#37435C;color:#98A0B4}
.nav-link.active{border-color:#F0BB55;color:#DADFE8;background:#161D2C}
.filter-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0 0}
.exch-btn{background:transparent;color:#98A0B4;border:1px solid #293346;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:.72rem;transition:all .15s}
.exch-btn.active{background:#293346;color:#DADFE8;border-color:#37435C}
.s-search{flex:1;min-width:160px;max-width:260px;background:#0F1420;color:#DADFE8;border:1px solid #293346;border-radius:6px;padding:4px 10px;font-size:.78rem;outline:none}
.tab-bar{display:flex;gap:2px;margin:14px 0 0;border-bottom:1px solid #293346}
.tab-btn{font-size:.8rem;padding:9px 16px;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;background:none;color:#636B80;cursor:pointer;font-weight:600;letter-spacing:.02em;transition:all .15s;border-radius:4px 4px 0 0}
.tab-btn:hover{color:#98A0B4;background:#0F1420}
.tab-btn.active{color:#DADFE8;border-bottom-color:#F0BB55;background:#0F1420}
.tab-panel{display:none;padding-top:16px}
.tab-panel.active{display:block}
tbody tr:hover{background:#0F1420}
tbody td{padding:5px 10px;border-bottom:1px solid #293346;vertical-align:middle;white-space:nowrap}
.pt-section{background:#0F1420;border:1px solid #293346;border-radius:10px;padding:14px 16px;margin-bottom:16px}
.pt-title{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#37435C;margin-bottom:10px}
.pt{width:100%;border-collapse:collapse;font-size:.8rem}
.pt th{text-align:left;padding:5px 10px;font-size:.65rem;color:#293346;text-transform:uppercase;border-bottom:1px solid #293346}
.pt td{padding:7px 10px;border-bottom:1px solid #080B12}
.pt tr:last-child td{border-bottom:none}
.pt tr:hover td{background:#161D2C}
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
    s60d   = [r for r in bullish if "多頭拐點"  in r["patterns"] and r["score"] >= 2]
    s_dbl  = [r for r in bullish if "雙底"      in r["patterns"] and r["score"] >= 2]
    s_tri  = [r for r in bullish if any(p in r["patterns"] for p in ("收斂三角", "上升三角", "下降楔型")) and r["score"] >= 2]
    s_vcp  = [r for r in bullish if "VCP突破"   in r["patterns"] and r["score"] >= 2]
    s_avoid = [r for r in bearish if r["score"] <= -2]
    s_box  = sorted(neutral, key=lambda x: abs(x["score"]), reverse=True)

    # Tab panels
    tab1 = _section("做多候選 Screener", screener,
                     f"命中任一看多形態 · score ≥ 2 · Top 50 · {date_str}")

    tab2 = "\n".join([
        _section("VCP 量縮底部突破",  s_vcp),
        _section("三角整理向上突破",  s_tri),
        _section("雙底",              s_dbl),
        _section("多頭排列拐點",     s60d),
    ])

    tab3 = _meta_hits_section(results)

    tab4 = "\n".join([
        _section("避開清單", s_avoid, "看空形態命中 · score ≤ -2"),
        "<div style='height:16px'></div>",
        _section("盤整觀察（箱型整理）", s_box, "尚未突破，等待方向"),
        "<div style='height:16px'></div>",
        _BACKTEST_NOTE,
    ])

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- 禁止瀏覽器快取：同 index.html，每天重產、檔名固定，避免普通 F5 看到舊資料。 -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>形態掃描 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page-head">
  <div style="color:#98A0B4;font-size:1rem;font-weight:600">形態掃描
    <span style="color:#37435C;font-size:.78rem;font-weight:400;margin-left:8px">{date_str}</span>
  </div>
  <div class="nav-links">
    <a class="nav-link" href="index.html">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link active" href="patterns.html" aria-current="page">形態掃描</a>
    <a class="nav-link" href="momentum.html">逆轟策略</a>
  </div>
</div>
<div class="filter-bar">
  <button class="exch-btn active" data-exch="" onclick="applyFilters(this)">全部</button>
  <button class="exch-btn" data-exch="TWSE" onclick="applyFilters(this)">上市</button>
  <button class="exch-btn" data-exch="TPEx" onclick="applyFilters(this)">上櫃</button>
  <input id="s-search" class="s-search" type="text" placeholder="搜尋股號 / 名稱 / 族群…" oninput="applyFilters()">
</div>
<div class="tab-bar">
  <button class="tab-btn" data-tab="tab-screener" onclick="switchTab('tab-screener')">做多候選</button>
  <button class="tab-btn" data-tab="tab-patterns" onclick="switchTab('tab-patterns')">形態分區</button>
  <button class="tab-btn" data-tab="tab-meta"     onclick="switchTab('tab-meta')">META 熱區</button>
  <button class="tab-btn" data-tab="tab-avoid"    onclick="switchTab('tab-avoid')">避開 / 觀察</button>
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
