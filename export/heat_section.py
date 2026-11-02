"""族群績效頁（docs/index.html）最上方的「族群熱度」區（2026-11-02 Cody：熱度頁整合進族群績效，重複的丟掉）。

輸入是 recommend.sector_heat.sector_heat 的結果（推薦 payload 的 "heat"）。留下熱度排行表（可展開成員）與進榜／掉出；
原熱度頁的前 3 名卡片跟排行表前 3 列重複，拿掉。「轉熱／退燒」改叫「進榜／掉出」，免得跟方塊上依 5 日報酬算的「增溫／退燒」混在一起。
樣式用 index 自己的 token（--up、--panel…），class 一律 hx- 開頭，不跟 index 既有樣式衝突。
推薦發布（20:00 後）只重寫標記之間這一段（patch_index），不重產整個 index。"""
from html import escape
from pathlib import Path

START, END = "<!--heat-section:start-->", "<!--heat-section:end-->"

HEAT_SECTION_CSS = r"""
.hx{margin:0 0 8px;padding:0 16px 8px}
.hx .section-head{padding:18px 0 6px;align-items:flex-end}
.hx-note{margin:0 0 10px;color:var(--ink-2);font-size:.76rem;line-height:1.55}
.hx-movers{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 10px;font-size:.8rem;color:var(--ink-2)}
.hx-movers b{color:var(--ink);font-weight:650}
.hx-wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--border);border-radius:6px}
.hx-table{width:100%;border-collapse:collapse;font-size:.82rem;white-space:nowrap}
.hx-table th{position:sticky;top:0;padding:8px 10px;background:var(--panel-2);color:var(--ink-2);font-weight:600;text-align:left;border-bottom:1px solid var(--border)}
.hx-table td{padding:7px 10px;border-bottom:1px solid var(--border)}
.hx-table .r{text-align:right}
.hx-table tbody tr:hover>td{background:var(--panel-2)}
.hx-score{color:var(--accent);font-weight:700}
.hx-toggle{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0;background:none;border:0;color:var(--ink);font:inherit;font-weight:650;cursor:pointer}
.hx-toggle::before{content:"▸";color:var(--ink-3);transition:transform .15s}
.hx-toggle[aria-expanded="true"]::before{transform:rotate(90deg)}
.hx-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.hx-pull{color:var(--accent)}
.hx-members>td{padding:0 10px 10px 34px;background:var(--panel-2)}
.hx-mini{border-collapse:collapse;font-size:.78rem}
.hx-mini th,.hx-mini td{padding:5px 12px 5px 0;background:none;border-bottom:1px solid var(--border)}
.hx-empty{padding:18px;color:var(--ink-3);background:var(--panel);border:1px solid var(--border);border-radius:6px}
@media(max-width:768px){.hx{padding:0 4px 8px}.hx-toggle{min-height:44px}}
@media(prefers-reduced-motion:reduce){.hx-toggle::before{transition:none}}
"""

_JS = """<script>
document.querySelectorAll(".hx-toggle").forEach(function(b){
  b.addEventListener("click",function(){
    var open=b.getAttribute("aria-expanded")==="true", row=document.getElementById(b.getAttribute("aria-controls"));
    b.setAttribute("aria-expanded",open?"false":"true"); if(row){row.hidden=open}
  });
});
</script>"""


def _e(v) -> str:
    return escape("" if v is None else str(v))


def _signed(v, suffix: str = "%", nd: int = 1) -> str:
    if v is None:
        return '<span class="muted">—</span>'
    v = float(v)
    cls = "up" if v > 0 else "down" if v < 0 else "muted"
    return f'<span class="{cls}">{"+" if v > 0 else "−" if v < 0 else ""}{abs(v):.{nd}f}{suffix}</span>'


def _ratio(v) -> str:
    return "—" if v is None else f"{v:.0f}%"


def _change(s: dict) -> str:
    """名次變化：▲3／▼2／新進／持平（顏色之外也有符號）。"""
    prev = s.get("prev_rank")
    if prev is None:
        return '<span class="muted">新進</span>'
    d = prev - s["rank"]
    if d > 0:
        return f'<span class="up">▲{d}</span>'
    if d < 0:
        return f'<span class="down">▼{-d}</span>'
    return '<span class="muted">持平</span>'


def _status(s: str) -> str:
    return f'<span class="hx-pull">{_e(s)}</span>' if s == "拉回中" else f'<span class="muted">{_e(s)}</span>'


def _members(members: list) -> str:
    rows = "".join(
        f'<tr><td class="tabular">{m["rank"]}</td><td>{_e(m["stock_id"])} {_e(m["stock_name"])}</td>'
        f'<td class="r tabular">{m["close"]:,.2f}</td><td class="r tabular">{_signed(m["ret21"])}</td>'
        f'<td class="r tabular">{m["net5_lots"]:,}</td></tr>' for m in members)
    return ('<table class="hx-mini"><thead><tr><th>#</th><th>股票</th><th class="r">收盤</th><th class="r">21 日</th>'
            f'<th class="r">法人 5 日（張）</th></tr></thead><tbody>{rows}</tbody></table>')


def _row(i: int, s: dict) -> str:
    mid = f"hx-m-{i}"
    return (
        f'<tr><td class="tabular">{s["rank"]}</td>'
        f'<td><button type="button" class="hx-toggle" aria-expanded="false" aria-controls="{mid}">{_e(s["sector"])}'
        f' <span class="muted">{s["n"]} 檔</span></button></td>'
        f'<td class="r tabular hx-score">{s["score"]:.0f}</td><td class="r">{_change(s)}</td>'
        f'<td class="r tabular">{_signed(s["ret5"])}</td><td class="r tabular">{_signed(s["ret21"])}</td>'
        f'<td class="r tabular">{_signed(s["inst_ratio"], "%", 2)}</td><td class="r tabular">{_ratio(s["inst_breadth"])}</td>'
        f'<td class="r tabular">{_ratio(s["above_ma20"])}</td><td class="r tabular">{s["limit_up"]}</td>'
        f'<td class="r tabular">{_signed(s["foreign_chg"], " pp", 2)}</td><td class="r tabular">{_signed(s["big_chg"], " pp", 2)}</td>'
        f'<td>{_status(s["status"])}</td></tr>'
        f'<tr id="{mid}" class="hx-members" hidden><td colspan="13">{_members(s.get("members") or [])}</td></tr>'
    )


def _movers(heat: dict) -> str:
    entered = "、".join(f'<b>{_e(s["sector"])}</b>（#{s["rank"]}）' for s in heat.get("heating") or []) or "沒有"
    left = "、".join(f'<b>{_e(s["sector"])}</b>（#{s["prev_rank"]} → {"#" + str(s["rank"]) if s.get("rank") else "不在排行"}）'
                     for s in heat.get("cooling") or []) or "沒有"
    since = _e(heat.get("compare_date") or "")
    return f'<div class="hx-movers"><span>跟 {since} 比，進榜：{entered}</span><span>掉出：{left}</span></div>'


def render_section(heat: dict | None) -> str:
    """index 最上方的熱度區（含標記與展開用的 script）；沒有熱度資料時顯示空狀態。"""
    heat = heat or {}
    top = heat.get("top") or []
    d = heat.get("date") or ""
    when = f"{d[5:7]}/{d[8:10]} 收盤資料" if d else ""
    head = ('<div class="section-head compact"><div><span class="eyebrow">SECTOR HEAT</span>'
            f'<h2 id="heat-title">族群熱度 前 {len(top)}</h2></div><span class="count">{when}</span></div>')
    if not top:
        body = '<div class="hx-empty">還沒有熱度資料（每晚籌碼到齊後產生）。</div>'
    else:
        body = (
            '<p class="hx-note">熱度＝近 21 日漲幅與法人買超占比的百分位平均（0～100）。回測：熱度前 20% 的族群之後 20 天平均 +5.6%'
            '（全部族群 +4.0%）。外資變化、大戶週增只顯示、不計入熱度。點族群名稱展開成員。</p>'
            + _movers(heat)
            + '<div class="hx-wrap"><table class="hx-table"><thead><tr><th>#</th><th>族群</th><th class="r">熱度</th>'
            '<th class="r">名次變化</th><th class="r">5 日</th><th class="r">21 日</th>'
            '<th class="r" title="近 5 日外資＋投信買超金額 ÷ 族群總市值">法人買超占比</th><th class="r">買超家數</th>'
            '<th class="r">站上 MA20</th><th class="r">漲停</th>'
            '<th class="r" title="外資持股比例 5 日變化（市值加權）">外資變化</th>'
            '<th class="r" title="集保 400 張以上大戶週變化（市值加權）">大戶週增</th><th>狀態</th></tr></thead>'
            f'<tbody>{"".join(_row(i, s) for i, s in enumerate(top))}</tbody></table></div>'
        )
    return f'{START}<section class="hx" id="heat" aria-labelledby="heat-title">{head}{body}</section>{_JS}{END}'


SHELL = '<div class="page-shell">'


def patch_index(heat: dict | None, path: str = "docs/index.html") -> bool:
    """推薦發布時只換掉 index 裡標記之間的熱度區。整合前產的舊頁面沒有標記：在 page-shell 開頭插入（連同樣式），
    等下次重產 index 就換成正式版。檔案不在、也找不到 page-shell 就不動，回傳 False。"""
    p = Path(path)
    if not p.exists():
        return False
    html = p.read_text(encoding="utf-8")
    i, j = html.find(START), html.find(END)
    if 0 <= i < j:
        html = html[:i] + render_section(heat) + html[j + len(END):]
    elif SHELL in html:
        html = html.replace(SHELL, f"{SHELL}<style>{HEAT_SECTION_CSS}</style>{render_section(heat)}", 1)
    else:
        return False
    p.write_text(html, encoding="utf-8")
    return True
