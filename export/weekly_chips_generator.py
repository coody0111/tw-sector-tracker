"""每週籌碼報告頁 docs/weekly.html（永遠最新）＋ docs/weekly/YYYY-MM-DD.html（歷史，全部保留）。
版面沿用每日報告（export/report_generator.py），歷史頁一樣用 <base href="../">。"""
import json
from pathlib import Path

from export.recommend_generator import _e
from export.report_generator import PAGE_CSS, _dir, _label
from export.ui_theme import SHARED_CSS, render_topbar
from recommend.weekly_chips import DANGER, WATCH


def _signed(v, fmt: str = "+.2f", suffix: str = "") -> str:
    if v is None:
        return '<td class="r">—</td>'
    return f'<td class="r {_dir(v)}">{format(v, fmt).replace("-", "−")}{suffix}</td>'


def _table(head: list, rows: list, left: int = 1) -> str:
    th = "".join(("<th>" if i < left else '<th class="r">') + f"{_e(h)}</th>" for i, h in enumerate(head))
    body = "".join(f"<tr>{r}</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _market(w: dict) -> str:
    rows = [f'<th>{_e(r["name"])}</th><td class="r">{r["close"]:,.2f}</td>{_signed(r["day_pct"], suffix="%")}'
            f'{_signed(r["week_pct"], suffix="%")}{_signed(r["ma60_pct"], suffix="%")}' for r in w["indices"]]
    table = _table(["指數", "收盤", "當日", "本週", "距季線"], rows) if rows else '<div class="empty">指數資料未到。</div>'
    return f'<section aria-labelledby="w-m"><h2 id="w-m">大盤與櫃買</h2>{table}</section>'


def _futures(w: dict) -> str:
    f = w["futures"]
    head = '<section aria-labelledby="w-f"><h2 id="w-f">台指期</h2>'
    if not f:
        return head + '<div class="empty">台指期資料未到。</div></section>'
    change = "" if w["futures_oi_change"] is None else f'，比上週 {w["futures_oi_change"]:+,} 口'.replace("-", "−")
    rows = [f'<th>{name}</th>{_signed(int(f[key]), "+,d")}' for name, key in
            (("外資及陸資", "foreign_net"), ("投信", "trust_net"), ("自營商", "dealer_net"))]
    return (f'{head}<p class="lead">{_e(f["contract"])} 一般盤收 {int(f["close"]):,}，漲跌 {int(f["change"]):+,}，'
            f'成交 {int(f["volume"]):,} 口，未平倉 {int(f["open_interest"]):,} 口。</p>'
            f'{_table(["三大法人", "未平倉淨額（口）"], rows)}<p class="note">外資淨額{_e(change)}。</p></section>')


def _ratio_rows(rows: list) -> list:
    return [f'<th>{_e(r["stock_id"])} {_e(r["stock_name"])}</th><td class="r">{r["balance"]:,.0f}</td><td class="r">{r["close"]:,.1f}</td>'
            f'<td class="r">{r["avg"]:,.1f}</td><td class="r">{r["ratio"]:.1f}%</td>' for r in rows]


def _maintenance(m: dict) -> str:
    pct = lambda v: "—" if v is None else f"{v:.1f}%"
    head = ["股票", "融資張數", "收盤", "20 日均價", "維持率（估）"]
    danger = (_table(head, _ratio_rows(m["danger"])) if m["danger"] else '<div class="empty">沒有低於 130% 的股票。</div>')
    scopes = [f'<th>{n}</th><td class="r">{pct(m[k])}</td>' for n, k in (("全部", "all"), ("上市", "twse"), ("上櫃", "tpex"))]
    return (f'<section aria-labelledby="w-r"><h2 id="w-r">融資維持率（估）</h2>'
            f'{_table(["範圍", "維持率（估）"], scopes)}'
            f'<p class="note">{m["n"]} 檔有融資的股票，用融資市值加權；{m["below_watch"]} 檔低於 {WATCH}%，{m["below_danger"]} 檔低於 {DANGER}%。</p>'
            f'<h3 class="sub">融資市值最大 10 檔</h3>{_table(head, _ratio_rows(m["largest"]))}'
            f'<h3 class="sub">低於 {DANGER}%</h3>{danger}'
            '<p class="note">這是估計值，只適合看相對風險，不是真實維持率。官方沒有公布這個數字；公式假設融資成本等於 20 日均價，'
            '成本較低的舊融資實際上會比這裡安全。近 20 日有除權息的股票也會偏低。</p></section>')


def _holders(title: str, rows: list) -> str:
    body = [f'<th>{_e(r["stock_id"])} {_e(r["stock_name"])}</th><td>{_e(r["meta_sector"])}</td><td class="r">{r["lv12_15_pct"]:.2f}</td>'
            f'{_signed(r["week_chg"])}<td class="r">{int(r["streak"])}</td>' for r in rows]
    return f'<h3 class="sub">{title}</h3>{_table(["股票", "族群", "大戶持股%", "本週增減", "連續週數"], body, left=2)}'


def _pairs(left_title: str, left: list, right_title: str, right: list, key: str, fmt: str) -> str:
    rows = []
    for i in range(max(len(left), len(right))):
        cell = lambda xs, name: (f'<th>{_e(xs[i][name])}</th>{_signed(xs[i][key], fmt)}' if i < len(xs) else '<th></th><td></td>')
        rows.append(cell(left, _name(left)) + cell(right, _name(right)))
    return _table([left_title, "增減", right_title, "增減"], rows)


def _name(xs: list) -> str:
    return "sector" if xs and "sector" in xs[0] else "name"


def _big(w: dict) -> str:
    sectors = _pairs("族群增加最多", w["sectors_up"], "族群減少最多", w["sectors_down"], "big_chg", "+.2f") if w["sectors_up"] or w["sectors_down"] else ""
    return (f'<section aria-labelledby="w-b"><h2 id="w-b">大戶增減</h2><p class="note">大戶是持股 400 張以上，增減單位是百分點；'
            f'連續週數為正代表連增，為負代表連減。</p>{_holders("增加最多 10 檔", w["holders_up"])}{_holders("減少最多 10 檔", w["holders_down"])}'
            f'{"<h3 class=sub>族群</h3>" + sectors if sectors else ""}</section>')


def _margin(w: dict) -> str:
    verb = "增加" if w["margin_total"] >= 0 else "減少"
    return (f'<section aria-labelledby="w-g"><h2 id="w-g">融資增減</h2><p class="lead">股票池本週{verb} {abs(w["margin_total"]):,} 張。</p>'
            f'{_pairs("融資增加", w["margin_up"], "融資減少", w["margin_down"], "chg", "+,d")}</section>')


def _script(day: str, dates: list) -> str:
    return f"""<script>
(function(){{
var sel=document.getElementById('w-day'),cur={json.dumps(day)},wd='日一二三四五六';
function fill(list){{sel.textContent='';list.forEach(function(d){{var o=document.createElement('option');o.value=d;o.textContent=d+'（週'+wd[new Date(d+'T00:00:00').getDay()]+'）';o.selected=d===cur;sel.appendChild(o)}})}}
fill({json.dumps(dates)});
fetch('weekly/index.json').then(function(r){{return r.ok?r.json():null}}).then(function(l){{if(l&&l.length)fill(l)}}).catch(function(){{}});
sel.addEventListener('change',function(){{location.href='weekly/'+sel.value+'.html'}});
}})();
</script>"""


def render(w: dict, dates: list, base: str = "") -> str:
    d = w["date"]
    base_tag = f'<base href="{base}">' if base else ""
    options = "".join(f'<option value="{x}"{" selected" if x == d else ""}>{_label(x)}</option>' for x in dates)
    points = "".join(f"<li>{_e(p)}</li>" for p in w["points"])
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">{base_tag}<title>每週籌碼 {d}</title>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800&display=swap">'
        f'<style>{SHARED_CSS}{PAGE_CSS}</style></head><body>{render_topbar("每週籌碼", "weekly.html", d)}'
        '<main class="ui-main"><div class="rp"><label class="rp-picker" for="w-day">報告日期'
        f'<select id="w-day">{options}</select></label>'
        f'<section aria-labelledby="w-t"><h2 id="w-t" class="rp-h1">本週籌碼報告</h2><ul class="points">{points}</ul></section>'
        f'{_market(w)}{_futures(w)}{_maintenance(w["maintenance"])}{_big(w)}{_margin(w)}'
        '<p class="note">指數與融資從本週一起算，大戶是集保資料日對上一個資料日。'
        '融資與大戶都是股票池合計（約 1,036 檔），不是全市場官方總額。排行沒有過濾流動性，'
        '小型股可能因為總股數少而變動較大。本報告只描述籌碼變化，沒有回測過是否能當買賣依據。</p>'
        f'</div></main>{_script(d, dates)}</body></html>')


def generate(w: dict, output_path: str = "docs/weekly.html", archive_dir: str = "docs/weekly") -> None:
    folder = Path(archive_dir)
    folder.mkdir(parents=True, exist_ok=True)
    d = w["date"]
    dates = sorted({p.stem for p in folder.glob("*.html")} | {d}, reverse=True)
    (folder / f"{d}.html").write_text(render(w, dates, base="../"), encoding="utf-8")
    (folder / "index.json").write_text(json.dumps(dates), encoding="utf-8")
    Path(output_path).write_text(render(w, dates), encoding="utf-8")
