"""族群熱度頁 docs/heat.html（規格 docs/superpowers/specs/2026-10-27-sector-heat-report.md）。
輸入是 recommend.sector_heat.sector_heat 的結果（推薦 payload 的 "heat"），跟推薦一起在 20:00 資料到齊後產生。
樣式沿用推薦頁（export/recommend_generator.py 的 PAGE_CSS）＋共用頁首。"""
from pathlib import Path

from export.recommend_generator import PAGE_CSS, _e, _price, _signed, _status
from export.ui_theme import SHARED_CSS, render_topbar


def _change(s: dict) -> str:
    """跟 compare_date 比的名次變化：▲3／▼2／新進／持平（顏色之外也有符號，色盲也看得出來）。"""
    prev = s.get("prev_rank")
    if prev is None:
        return '<span class="muted">新進</span>'
    d = prev - s["rank"]
    if d > 0:
        return f'<span class="up">▲{d}</span>'
    if d < 0:
        return f'<span class="down">▼{-d}</span>'
    return '<span class="muted">持平</span>'


def _ratio(v) -> str:
    return "—" if v is None else f"{v:.0f}%"


def _pp(v) -> str:
    return _signed(v, " pp", 2)


def _sentence(s: dict) -> str:
    above = "—" if s.get("above_ma20") is None else f"{round(s['above_ma20'] / 100 * s['n'])}"
    inst = "—" if s.get("inst_ratio") is None else f"{s['inst_ratio']:.2f}%"
    ret21 = "—" if s.get("ret21") is None else f"{s['ret21']:+.1f}%"
    return f"近 21 日 {ret21}、法人 5 日買超占市值 {inst}、{s['n']} 檔有 {above} 檔站上月線、{s['status']}"


def _hot_card(s: dict) -> str:
    leaders = "".join(
        f'<li><span class="num">{_e(m["stock_id"])}</span> {_e(m["stock_name"])}<span class="num">{_signed(m["ret21"])}</span></li>'
        for m in s.get("leaders") or [])
    return (
        f'<article class="hot"><div class="hot-head"><span class="hot-rank num">#{s["rank"]}</span>'
        f'<h3>{_e(s["sector"])}</h3>{_status(s["status"])}</div>'
        f'<div class="hot-score"><strong class="num">{s["score"]:.0f}</strong><span>熱度</span>{_change(s)}</div>'
        f'<p>{_e(_sentence(s))}</p><ol class="hot-leaders">{leaders}</ol></article>'
    )


def _member_rows(members: list) -> str:
    return "".join(
        f'<tr><td class="num">{m["rank"]}</td><td>{_e(m["stock_id"])} {_e(m["stock_name"])}</td>'
        f'<td class="r num">{_price(m["close"])}</td><td class="r num">{_signed(m["ret21"])}</td>'
        f'<td class="r num">{m["net5_lots"]:,}</td></tr>' for m in members)


def _row(i: int, s: dict) -> str:
    mid = f"heat-m-{i}"
    name = (f'<button type="button" class="sec-toggle" aria-expanded="false" aria-controls="{mid}">{_e(s["sector"])}'
            f' <span class="muted small">{s["n"]} 檔</span></button>')
    row = (f'<tr><td class="num">{s["rank"]}</td><td>{name}</td><td class="r num"><b>{s["score"]:.0f}</b></td>'
           f'<td class="r">{_change(s)}</td><td class="r num">{_signed(s["ret5"])}</td><td class="r num">{_signed(s["ret21"])}</td>'
           f'<td class="r num">{_signed(s["inst_ratio"], "%", 2)}</td><td class="r num">{_ratio(s["inst_breadth"])}</td>'
           f'<td class="r num">{_ratio(s["above_ma20"])}</td><td class="r num">{s["limit_up"]}</td>'
           f'<td class="r num">{_pp(s["foreign_chg"])}</td><td class="r num">{_pp(s["big_chg"])}</td>'
           f'<td>{_status(s["status"])}</td></tr>')
    return (row + f'<tr id="{mid}" class="sec-members" hidden><td colspan="13"><table class="mini"><thead><tr><th>#</th>'
            '<th>股票</th><th class="r">收盤</th><th class="r">21 日</th><th class="r">法人 5 日（張）</th></tr></thead>'
            f'<tbody>{_member_rows(s.get("members") or [])}</tbody></table></td></tr>')


def _top_table(top: list) -> str:
    rows = "".join(_row(i, s) for i, s in enumerate(top))
    return (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>族群</th>'
        '<th class="r" title="近 21 日漲幅、法人買超占比的百分位平均（0～100）">熱度</th>'
        '<th class="r">名次變化</th><th class="r">5 日</th><th class="r">21 日</th>'
        '<th class="r" title="近 5 日外資＋投信買超金額 ÷ 族群總市值">法人買超占比</th><th class="r">買超家數</th>'
        '<th class="r">站上 MA20</th><th class="r">漲停</th>'
        '<th class="r" title="外資持股比例 5 日變化（市值加權，只顯示、不計分）">外資變化</th>'
        '<th class="r" title="集保 400 張以上大戶週變化（市值加權，只顯示、不計分）">大戶週增</th><th>狀態</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div><p class="score-note">點族群名稱展開成員。外資變化、大戶週增只顯示、不計入熱度。</p>'
    )


def _movers(heat: dict) -> str:
    heating = "".join(f'<li><b>{_e(s["sector"])}</b> <span class="muted">#{s["rank"]}</span> {_change(s)}</li>'
                      for s in heat.get("heating") or []) or '<li class="muted">沒有</li>'
    cooling = "".join(f'<li><b>{_e(s["sector"])}</b> <span class="muted">#{s["prev_rank"]} → '
                      f'{"#" + str(s["rank"]) if s.get("rank") else "不在排行"}</span></li>'
                      for s in heat.get("cooling") or []) or '<li class="muted">沒有</li>'
    since = _e(heat.get("compare_date") or "")
    return (
        f'<section aria-labelledby="move-h"><div class="sec-head"><h2 id="move-h">轉熱／退燒</h2>'
        f'<span class="hint">跟 {since} 比：前 10 名的進出</span></div><div class="movers">'
        f'<div><h3>剛轉熱</h3><ul>{heating}</ul></div><div><h3>退燒中</h3><ul>{cooling}</ul></div></div></section>'
    )


HEAT_CSS = r"""
.hot-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.hot{display:grid;gap:10px;padding:16px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius)}
.hot-head{display:flex;align-items:center;gap:10px}.hot-head h3{margin:0;font-size:1.05rem;font-weight:750}
.hot-rank{color:var(--ui-accent);font-weight:700}.hot-head .chip-cons,.hot-head span:last-child{margin-left:auto}
.hot-score{display:flex;align-items:baseline;gap:8px}.hot-score strong{font-size:2rem;line-height:1}.hot-score span{color:var(--ui-ink-3);font-size:.75rem}
.hot p{margin:0;color:var(--ui-ink-2);font-size:.8rem}
.hot-leaders{margin:0;padding:0;list-style:none;display:grid;gap:4px;font-size:.8rem}
.hot-leaders li{display:flex;gap:8px}.hot-leaders li span:last-child{margin-left:auto}
.movers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.movers>div{padding:12px 16px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius)}
.movers h3{margin:0 0 6px;color:var(--ui-ink-2);font-size:.78rem}.movers ul{margin:0;padding-left:18px;display:grid;gap:4px;font-size:.82rem}
@media(max-width:760px){.hot-grid,.movers{grid-template-columns:minmax(0,1fr)}.sec-toggle{min-height:44px}}
"""

HEAT_JS = r"""
document.querySelectorAll(".sec-toggle").forEach(function(b){
  b.addEventListener("click",function(){
    var open=b.getAttribute("aria-expanded")==="true", row=document.getElementById(b.getAttribute("aria-controls"));
    b.setAttribute("aria-expanded",open?"false":"true"); if(row){row.hidden=open}
  });
});
"""


def render(heat: dict) -> str:
    top = heat.get("top") or []
    head = ('<div class="sec-head"><h2 id="top-h">族群熱度</h2><span class="hint">熱度＝近 21 日漲幅與法人買超占比的百分位平均；'
            '回測：熱度前 20% 的族群之後 20 天平均 +5.6%（全部族群 +4.0%）</span></div>')
    if not top:
        body = f'<section aria-labelledby="top-h">{head}<div class="ui-empty">資料不足。</div></section>'
    else:
        body = (f'<section aria-labelledby="top-h">{head}<div class="hot-grid">{"".join(_hot_card(s) for s in top[:3])}</div></section>'
                f'<section aria-labelledby="rank-h"><div class="sec-head"><h2 id="rank-h">熱度排行 前 {len(top)}</h2></div>'
                f'{_top_table(top)}</section>{_movers(heat)}')
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>族群熱度 {_e(heat.get("date"))}</title><style>{SHARED_CSS}{PAGE_CSS}{HEAT_CSS}</style></head><body>'
        f'{render_topbar("族群熱度", "heat.html", heat.get("date"))}'
        f'<main class="ui-main">{body}</main><script>{HEAT_JS}</script></body></html>'
    )


def generate(heat: dict, output_path: str = "docs/heat.html") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(render(heat), encoding="utf-8")
