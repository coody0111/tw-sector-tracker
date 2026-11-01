"""每日報告頁 docs/report.html（永遠最新）＋ docs/reports/YYYY-MM-DD.html（歷史，全部保留）。
規格 docs/superpowers/specs/2026-11-01-daily-report.md，設計稿 docs/superpowers/mockups/daily-report.html。
歷史頁用 <base href="../"> 共用同一份 HTML，頁首導覽和日期選單的相對路徑都以 docs/ 為準。"""
import json
from datetime import date
from pathlib import Path

from export.recommend_generator import CAPITAL_KEY, DEFAULT_CAPITAL, STOP, _alerts, _e, _shares
from export.ui_theme import SHARED_CSS, render_topbar

WEEKDAYS = "一二三四五六日"

PAGE_CSS = """
.rp{max-width:980px;margin:0 auto;display:grid;gap:40px;font-size:15px;line-height:1.65}
.rp section{min-width:0}
.rp h2{margin:0 0 14px;padding-bottom:7px;border-bottom:1px solid var(--ui-border);font-size:1.1rem;font-weight:800}
.rp h3{margin:0 0 8px;color:var(--ui-ink-2);font-size:.8rem;font-weight:700}
.rp h3.sub{margin-top:16px}
.rp-h1{margin:10px 0 16px;font:800 clamp(1.7rem,5vw,2.5rem)/1.25 var(--ui-serif);text-wrap:balance}
.rp-picker{display:flex;align-items:center;justify-content:flex-end;gap:8px;color:var(--ui-ink-2);font-size:.8rem}
.rp-picker select{min-height:44px;padding:0 10px;color:var(--ui-ink);background:var(--ui-panel);border:1px solid var(--ui-border-strong);border-radius:var(--ui-radius);font:inherit;cursor:pointer}
.rp-picker select:focus-visible{outline:3px solid var(--ui-accent);outline-offset:2px}
.tone{display:inline-block;padding:2px 9px;border:1px solid var(--ui-border-strong);border-radius:4px;color:var(--ui-ink-2);font-size:.76rem;font-weight:700}
.tone.bull{border-color:var(--ui-up);color:var(--ui-up)}.tone.bear{border-color:var(--ui-down);color:var(--ui-down)}
.provisional{margin-left:6px;border-color:var(--ui-accent);color:var(--ui-accent)}
.points{margin:0;padding:0;list-style:none;display:grid;gap:9px;max-width:68ch}.points li{padding-left:13px;border-left:2px solid var(--ui-border-strong);font-variant-numeric:tabular-nums}
.up{color:var(--ui-up)}.down{color:var(--ui-down)}
.rp a{color:var(--ui-accent)}
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:18px 22px}.stat span{display:block;color:var(--ui-ink-2);font-size:.76rem}.stat b{display:block;font-size:1.35rem;font-weight:800;line-height:1.3;font-variant-numeric:tabular-nums}.stat b i{font-style:normal}.stat em{font-style:normal;font-size:.76rem;color:var(--ui-ink-2)}
.sum{display:flex;flex-wrap:wrap;gap:6px 26px;margin-bottom:16px;font-variant-numeric:tabular-nums}.sum b{font-size:1.05rem}
.cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
.bar{display:grid;grid-template-columns:5.5em minmax(0,1fr) 3.8em;gap:8px;align-items:center;min-height:27px;font-size:.84rem}.bar b{text-align:right;font-variant-numeric:tabular-nums}.track{height:9px;background:var(--ui-panel-2);border-radius:2px;overflow:hidden}.track i{display:block;height:100%}.track i.up{background:var(--ui-up)}.track i.down{background:var(--ui-down)}
.note{margin:10px 0 0;color:var(--ui-ink-3);font-size:.76rem}
.tw{overflow-x:auto}.rp table{width:100%;border-collapse:collapse;font-size:.86rem;font-variant-numeric:tabular-nums}.rp th,.rp td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--ui-border);white-space:nowrap}.rp thead th{color:var(--ui-ink-3);font-size:.74rem;font-weight:600}.rp tbody th{font-weight:700}.rp .r{text-align:right}.hot{color:var(--ui-accent);font-weight:800}.lead{color:var(--ui-ink-2)}
.empty{padding:13px 14px;background:var(--ui-panel);border:1px dashed var(--ui-border-strong);border-radius:var(--ui-radius)}
.rp .alert{display:inline-block;margin-left:5px;padding:0 6px;border:1px solid var(--ui-accent);border-radius:4px;color:var(--ui-accent);font-size:.72rem}
@media(max-width:760px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.cols{grid-template-columns:minmax(0,1fr)}.rp-picker{justify-content:flex-start}}
"""


def _dir(v) -> str:
    return "" if v is None or v == 0 else ("up" if v > 0 else "down")


def _num(v, fmt: str, suffix: str = "") -> str:
    return "—" if v is None else f"{v:{fmt}}{suffix}"


def _label(d: str) -> str:
    return f"{d}（週{WEEKDAYS[date.fromisoformat(d).weekday()]}）"


def _head(r: dict) -> str:
    tone = r.get("tone")
    cls = {"偏多": " bull", "偏空": " bear"}.get(tone, "")
    badges = f'<span class="tone{cls}">大盤{tone}</span>' if tone else ""
    if r["missing"]:
        badges += f'<span class="tone provisional">暫定：缺{_e("、".join(r["missing"]))}</span>'
    points = "".join(f"<li>{_e(p)}</li>" for p in r["points"])
    return (f'<section aria-labelledby="rp-h1">{badges}<h1 class="rp-h1" id="rp-h1">{_e(r["title"])}</h1>'
            f'<ul class="points">{points}</ul></section>')


def _stat(label: str, value: str, note: str, cls: str = "") -> str:
    return f'<div class="stat"><span>{label}</span><b class="{cls}">{value}</b><em>{_e(note)}</em></div>'


def _market(m: dict) -> str:
    chg, pct, gap = m.get("taiex_change"), m.get("taiex_change_pct"), m.get("taiex_ma20_gap")
    move = "—" if chg is None or pct is None else f"{chg:+,.2f}（{pct:+.2f}%）"
    above, fail = m.get("above_ma20_pct"), m.get("fail_rate")
    gap_pct = None if gap is None else gap * 100
    side = "—" if gap is None else ("在 20 日線上" if gap >= 0 else "在 20 日線下")
    limits = f'<i class="up">{m.get("limit_up", 0)}</i> / <i class="down">{m.get("limit_down", 0)}</i>'
    return ('<section aria-labelledby="rp-m"><h2 id="rp-m">大盤</h2><div class="stats">'
            + _stat("加權收盤", _num(m.get("taiex_close"), ",.2f"), move, _dir(chg))
            + _stat("對 20 日線", _num(gap_pct, "+.1f", "%"), side, _dir(gap))
            + _stat("站上 20 日線", _num(None if above is None else above * 100, ".1f", "%"), "股票池")
            + _stat("突破失敗率", _num(None if fail is None else fail * 100, ".0f", "%"), f"近 {m.get('fail_n', 0)} 筆")
            + _stat("漲停／跌停", limits, "股票池") + "</div></section>")


def _bars(rows: list, top: float) -> str:
    return "".join(
        f'<div class="bar"><span>{_e(x["sector"])}</span><span class="track"><i class="{_dir(x["net"])}" '
        f'style="width:{abs(x["net"]) / top * 100:.1f}%"></i></span><b class="{_dir(x["net"])}">{x["net"]:+,.1f}</b></div>'
        for x in rows)


def _big(b: dict | None) -> str:
    if not b:
        return ""
    fmt = lambda xs: "、".join(f'{x["sector"]} {x["chg"]:+.2f}' for x in xs) or "—"
    return f'<p class="note">本週大戶持股比例增減（百分點）。增加：{_e(fmt(b["up"]))}。減少：{_e(fmt(b["down"]))}。</p>'


def _chips(c: dict | None, big: dict | None) -> str:
    head = '<section aria-labelledby="rp-c"><h2 id="rp-c">籌碼</h2>'
    if not c:
        return head + '<div class="empty">籌碼資料未到。</div></section>'
    margin = c.get("margin_change")
    margin_text = "—" if margin is None else f'{"增" if margin >= 0 else "減"} {abs(margin):,} 張'
    top = max([abs(x["net"]) for x in c["buy"] + c["sell"]] or [1])
    return (f'{head}<div class="sum"><span>外資 <b class="{_dir(c["foreign"])}">{c["foreign"]:+,.0f} 億</b></span>'
            f'<span>投信 <b class="{_dir(c["trust"])}">{c["trust"]:+,.0f} 億</b></span>'
            f'<span>融資 <b>{margin_text}</b></span></div>'
            f'<div class="cols"><div><h3>買超最多的族群（億）</h3>{_bars(c["buy"], top)}</div>'
            f'<div><h3>賣超最多的族群（億）</h3>{_bars(c["sell"], top)}</div></div>'
            f'<p class="note">股票池合計，約 1,036 檔，不是全市場官方總額。族群金額為外資＋投信。</p>{_big(big)}</section>')


def _sectors(rows: list) -> str:
    head = '<section aria-labelledby="rp-s"><h2 id="rp-s">族群熱度前 5</h2>'
    if not rows:
        return head + '<div class="empty">今天沒有熱度資料。</div></section>'
    body = "".join(
        f'<tr><td class="r">{s["rank"]}</td><th scope="row">{_e(s["sector"])}</th><td class="r hot">{s["score"]:.0f}</td>'
        f'<td class="r {_dir(s.get("ret21"))}">{_num(s.get("ret21"), "+.1f", "%")}</td>'
        f'<td class="r {_dir(s.get("inst_ratio"))}">{_num(s.get("inst_ratio"), "+.2f", "%")}</td><td>{_e(s["status"])}</td>'
        f'<td class="lead">{_e("、".join(x["stock_name"] for x in s.get("leaders") or []))}</td></tr>' for s in rows)
    return (f'{head}<div class="tw"><table><thead><tr><th class="r">#</th><th>族群</th><th class="r">熱度</th>'
            '<th class="r">21 日</th><th class="r">法人買超占比</th><th>狀態</th><th>帶頭</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></section>')


def _new_table(cards: list) -> str:
    if not cards:
        return '<div class="empty">今天沒有新訊號。</div>'
    body = "".join(
        f'<tr data-close="{float(c["close"])}"><th scope="row">{_e(c["stock_id"])} {_e(c["stock_name"])}</th>'
        f'<td>{_e(c["meta_sector"])}</td><td>{_e(c["type"])}</td><td class="r">{float(c["close"]):.2f}</td>'
        f'<td class="r shares">{_shares(float(c["close"])):,}</td><td class="r">{float(c["close"]) * (1 - STOP):.2f}</td>'
        f'<td>{_alerts(c)}</td></tr>' for c in cards)
    return ('<div class="tw"><table><thead><tr><th>股票</th><th>族群</th><th>型態</th><th class="r">收盤</th>'
            f'<th class="r">買幾股</th><th class="r">停損價</th><th>提醒</th></tr></thead><tbody>{body}</tbody></table></div>'
            f'<p class="note">股數用你在個股推薦頁輸入的總資金計算（未輸入時用 {DEFAULT_CAPITAL:,} 元），以收盤價估算。'
            f'停損請用實際買進價 × {1 - STOP:.2f}。</p>')


def _active_table(cards: list) -> str:
    if not cards:
        return ""
    body = "".join(
        f'<tr><th scope="row">{_e(c["stock_id"])} {_e(c["stock_name"])}</th><td>{_e(c["meta_sector"])}</td>'
        f'<td>{_e(c["type"])}</td><td class="r">{_e(c["signal_date"][5:].replace("-", "/"))}</td>'
        f'<td class="r">{float(c["close"]):.2f}</td>'
        f'<td class="r {_dir(c.get("since_signal_pct"))}">{_num(c.get("since_signal_pct"), "+.1f", "%")}</td>'
        f'<td>{_alerts(c)}</td></tr>' for c in cards)
    return (f'<h3 class="sub">有效中 {len(cards)} 檔</h3><div class="tw"><table><thead><tr><th>股票</th><th>族群</th><th>型態</th>'
            '<th class="r">訊號日</th><th class="r">收盤</th><th class="r">訊號後</th><th>提醒</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def _withdrawn(rows: list) -> str:
    if not rows:
        return ""
    items = "".join(f'<li>{_e(w["stock_id"])} {_e(w.get("stock_name") or "")}：{_e(w["reason"])}</li>' for w in rows)
    return f'<h3 class="sub">撤回 {len(rows)} 檔</h3><ul class="points">{items}</ul>'


def _recommend(r: dict) -> str:
    return (f'<section aria-labelledby="rp-r"><h2 id="rp-r">個股推薦</h2>{_new_table(r["new"])}{_active_table(r["active"])}'
            f'{_withdrawn(r["withdrawn"])}<p class="note">失效 {r["invalid_n"]} 檔見<a href="recommend.html">個股推薦頁</a>。</p></section>')


def _watch(lines: list) -> str:
    items = "".join(f"<li>{_e(x)}</li>" for x in lines)
    return f'<section aria-labelledby="rp-w"><h2 id="rp-w">明日觀察</h2><ul class="points">{items}</ul></section>'


def _script(day: str, dates: list) -> str:
    """日期選單：優先讀 reports/index.json（舊報告也看得到新日期），讀不到（本機開檔）用內嵌清單。股數讀推薦頁存的總資金。"""
    return f"""<script>
(function(){{
var sel=document.getElementById('rp-day'),cur={json.dumps(day)},wd='日一二三四五六';
function label(d){{return d+'（週'+wd[new Date(d+'T00:00:00').getDay()]+'）'}}
function fill(list){{sel.textContent='';list.forEach(function(d){{var o=document.createElement('option');o.value=d;o.textContent=label(d);o.selected=d===cur;sel.appendChild(o)}})}}
fill({json.dumps(dates)});
fetch('reports/index.json').then(function(r){{return r.ok?r.json():null}}).then(function(l){{if(l&&l.length)fill(l)}}).catch(function(){{}});
sel.addEventListener('change',function(){{location.href='reports/'+sel.value+'.html'}});
var cap=null;try{{cap=parseFloat(String(localStorage.getItem({json.dumps(CAPITAL_KEY)})).replace(/,/g,''))}}catch(e){{}}
if(cap>0)document.querySelectorAll('tr[data-close]').forEach(function(tr){{var s=Math.floor(cap*0.01/(parseFloat(tr.dataset.close)*{STOP}));tr.querySelector('.shares').textContent=s.toLocaleString()}});
}})();
</script>"""


def render(report: dict, dates: list, base: str = "") -> str:
    d = report["date"]
    base_tag = f'<base href="{base}">' if base else ""
    options = "".join(f'<option value="{x}"{" selected" if x == d else ""}>{_label(x)}</option>' for x in dates)
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">{base_tag}<title>每日報告 {d}</title>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800&display=swap">'
        f'<style>{SHARED_CSS}{PAGE_CSS}</style></head><body>{render_topbar("每日報告", "report.html", d)}'
        '<main class="ui-main"><div class="rp"><label class="rp-picker" for="rp-day">報告日期'
        f'<select id="rp-day">{options}</select></label>'
        f'{_head(report)}{_market(report["market"])}{_chips(report["chips"], report.get("big_holders"))}'
        f'{_sectors(report["sectors"])}{_recommend(report)}{_watch(report["watch"])}</div></main>'
        f'{_script(d, dates)}</body></html>')


def generate(report: dict, output_path: str = "docs/report.html", archive_dir: str = "docs/reports") -> None:
    """寫歷史頁（同一天覆蓋成最新版）、日期清單、最新頁。"""
    folder = Path(archive_dir)
    folder.mkdir(parents=True, exist_ok=True)
    d = report["date"]
    dates = sorted({p.stem for p in folder.glob("*.html")} | {d}, reverse=True)
    (folder / f"{d}.html").write_text(render(report, dates, base="../"), encoding="utf-8")
    (folder / "index.json").write_text(json.dumps(dates), encoding="utf-8")
    Path(output_path).write_text(render(report, dates), encoding="utf-8")
