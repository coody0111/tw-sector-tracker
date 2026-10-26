"""個股推薦頁 docs/recommend.html（規格 §10、設計稿 docs/superpowers/mockups/recommend-page.html）。

輸入是 recommend.daily.run_daily 的 payload；股數／停損用頁面上的總資金在瀏覽器算（只存 localStorage），
伺服器端先用預設 100 萬算好一份，沒有 JS 也看得到。"""
from html import escape
from pathlib import Path

from export.ui_theme import SHARED_CSS, render_topbar
from recommend.exits import MAX_HOLD, STOP, TRAIL

RISK = 0.01                      # 每筆風險＝總資金 1%（規格 §11）
DEFAULT_CAPITAL = 1_000_000
CAPITAL_KEY = "tw-recommend-capital-v1"
STRATEGY = "突破策略"
# 回測對照：官方行情＋除權息／減資漲跌修正後（2026-10-26 Cody 跑 --backtest-recommend，2025-01 起，已出場 2,392 筆）
BACKTEST_REF = {"win_rate": 0.25, "payoff": 5.35, "mean_r": 0.86, "pf": 1.81}
ROUTE_LABELS = (("法人", "法人大買"), ("外資", "外資大增"), ("投信", "投信持續"), ("大戶", "大戶大增"))
TYPE_LABELS = {"整理": ("整理型", "box"), "續攻": ("續攻型", "run")}


def _e(v) -> str:
    return escape("" if v is None else str(v))


def _price(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if v >= 1000:
        return f"{v:,.0f}"
    s = f"{v:.2f}".rstrip("0")
    return s + "0" if s.endswith(".") else s          # 595 → 595.0、337.5、317.25


def _signed(v, suffix: str = "%", nd: int = 1) -> str:
    """帶正負號與紅漲綠跌的數字；None 顯示 —。"""
    if v is None:
        return '<span class="muted">—</span>'
    v = float(v)
    cls = "up" if v > 0 else "down" if v < 0 else "muted"
    return f'<span class="{cls}">{"+" if v > 0 else "−" if v < 0 else ""}{abs(v):.{nd}f}{suffix}</span>'


def _ratio(v, nd: int = 0) -> str:
    return "—" if v is None else f"{float(v) * 100:.{nd}f}%"


def _shares(price: float, capital: float = DEFAULT_CAPITAL) -> int:
    return int(capital * RISK // (price * STOP)) if price else 0


def _type_chip(t: str) -> str:
    label, cls = TYPE_LABELS.get(t, (t, ""))
    return f'<span class="type {cls}">{_e(label)}</span>'


def _alerts(c: dict) -> str:
    return "".join(f'<span class="alert">{_e(a)}</span>' for a in c.get("alerts") or [])


# ── 頁首大盤條 ─────────────────────────────────────────────

def _market(header: dict, taiex_above, taiex_gap) -> str:
    h = header or {}
    fail = h.get("fail_rate")
    fail_html = (f'<strong class="num">{_ratio(fail)}</strong><small class="num">近 10 日 {h.get("fail_n", 0)} 筆訊號</small>'
                 if fail is not None else f'<strong class="muted">樣本不足</strong><small class="num">{h.get("fail_n", 0)} 筆</small>')
    if taiex_above is None:
        taiex_html = '<strong class="muted">—</strong><small>資料不足</small>'
    else:
        gap = "" if taiex_gap is None else f'<small class="num">距 MA20 {_signed(taiex_gap * 100)}</small>'
        taiex_html = (f'<strong class="{"up" if taiex_above else "down"}">在 MA20 之{"上" if taiex_above else "下"}</strong>'
                      + gap)
    return (
        '<div class="market" aria-label="大盤資訊">'
        f'<div class="mcell"><label>股票池站上 MA20</label><strong class="num">{_ratio(h.get("above_ma20_pct"))}</strong>'
        '<small>20 日均量 ≥ 300 張的股票</small></div>'
        f'<div class="mcell"><label>近 10 日突破失敗率</label>{fail_html}</div>'
        f'<div class="mcell"><label>加權指數</label>{taiex_html}</div>'
        f'<div class="mcell"><label>今日漲停／跌停</label><strong class="num"><span class="up">{h.get("limit_up", "—")}</span>'
        f' ／ <span class="down">{h.get("limit_down", "—")}</span></strong><small>全部股票</small></div>'
        '</div><p class="market-note">大盤資訊只給你參考，不會擋掉訊號。</p>'
    )


def _capital() -> str:
    return (
        '<div class="capital"><div class="capital-inner">'
        f'<div><label for="capital">總資金</label><br><input id="capital" type="text" inputmode="numeric" '
        f'value="{DEFAULT_CAPITAL:,}" aria-describedby="capital-hint"></div>'
        f'<div class="rule"><span>每筆風險 <b class="num">{RISK:.0%}</b> ＝ <b class="num" id="risk">'
        f'{DEFAULT_CAPITAL * RISK:,.0f}</b> 元</span><span>停損 <b class="num">{STOP:.0%}</b></span>'
        f'<span>出場：最高收盤回落 <b class="num">{TRAIL:.0%}</b>，最多 {MAX_HOLD} 天</span></div>'
        '<span class="capital-hint" id="capital-hint">只存在你的瀏覽器，不會上傳。股數以收盤價估算，'
        f'停損請用實際買進價 × {1 - STOP:.2f}。</span></div></div>'
    )


# ── 今日新訊號 ─────────────────────────────────────────────

def _card(c: dict) -> str:
    price = float(c["close"])
    hits = set((c.get("routes") or "").split(","))
    routes = "".join(f'<span class="route{" hit" if k in hits else ""}">{label}</span>' for k, label in ROUTE_LABELS)
    shares = _shares(price)
    extra = []
    if "乖離大" in (c.get("alerts") or []) and c.get("bias10") is not None:
        extra.append(f"MA10 乖離 {c['bias10']:.0f}%")
    if c.get("type") == "續攻" and c.get("ret20_prev") is not None:
        extra.append(f"前 20 日漲 {c['ret20_prev']:.0f}%")
    elif c.get("rng20") is not None:
        extra.append(f"前 20 日區間 {c['rng20']:.0f}%")
    top = '<span class="chip-cons">近 21 天前 20 名</span>' if c.get("top21") else ""
    vr = "" if c.get("vr") is None else f'<span class="muted small">量比 {c["vr"]:.2f}</span>'
    return (
        f'<article class="card" data-price="{price}">'
        f'<div class="c-head"><span class="c-id">{_e(c["stock_id"])}</span><span class="c-name">{_e(c["stock_name"])}</span>'
        f'{_type_chip(c.get("type"))}</div>'
        f'<div class="price"><span class="close num">{_price(price)}</span><span class="chg num">{_signed(c.get("change_pct"))}</span>{vr}</div>'
        f'<div class="routes">{routes}</div>'
        '<div class="order">'
        f'<div><label>買幾股</label><strong class="shares num">{shares:,}</strong><small class="amount">約 {shares * price / 1e4:.1f} 萬</small></div>'
        f'<div><label>停損價</label><strong class="stop num">{price * (1 - STOP):.2f}</strong><small>−{STOP:.0%}</small></div>'
        f'<div><label>最多虧</label><strong class="loss num">{DEFAULT_CAPITAL * RISK / 1e4:.1f} 萬</strong><small>總資金 {RISK:.0%}</small></div>'
        '</div>'
        f'<div class="foot">{_alerts(c)}{top}{"".join(f"<span>{_e(x)}</span>" for x in extra)}'
        f'<span>+24% 參考價 <b class="num t24">{price * 1.24:.1f}</b></span></div>'
        '</article>'
    )


def _withdrawn_block(withdrawn: list, shareholder_date) -> str:
    """集保更新後撤回（不再符合）：附理由，提醒開盤先不要買。"""
    if not withdrawn:
        return ""
    rows = "".join(f'<li><b class="num">{_e(w["stock_id"])}</b> {_e(w.get("stock_name"))}：{_e(w["reason"])}</li>'
                   for w in withdrawn)
    when = f"（集保 {_e(shareholder_date)} 更新後不再符合，開盤先不要買）" if shareholder_date else "（集保更新後不再符合）"
    return f'<div class="withdrawn"><strong>集保更新後撤回 {len(withdrawn)} 檔</strong>{when}<ul>{rows}</ul></div>'


def _new_section(groups: list, withdrawn: list | None = None, shareholder_date=None) -> str:
    n = sum(g["count"] for g in groups)
    head = ('<div class="sec-head"><h2 id="new-h">今日新訊號</h2>'
            f'<span class="count">{n} 檔</span><span class="hint">突破策略：漲停＋創 90 日高＋籌碼任一路線，明天開盤買</span></div>'
            + _withdrawn_block(withdrawn or [], shareholder_date))
    if not groups:
        return f'<section aria-labelledby="new-h">{head}<div class="ui-empty"><strong>今天沒有新訊號</strong>收盤後沒有股票符合條件。</div></section>'
    body = "".join(
        f'<div class="sector"><div class="sector-head">{_e(g["sector"])} <span class="n">{g["count"]} 檔</span></div>'
        f'<div class="cards">{"".join(_card(c) for c in g["cards"])}</div></div>'
        for g in groups)
    return f'<section aria-labelledby="new-h">{head}{body}</section>'


# ── 仍有效／已失效 ─────────────────────────────────────────

def _active_section(active: list, invalid: list) -> str:
    head = ('<div class="sec-head"><h2 id="active-h">前幾天的推薦，仍有效</h2>'
            f'<span class="count">{len(active)} 檔</span><span class="hint">保留 3 個交易日；股數和停損用現價重算</span></div>')
    if active:
        rows = "".join(
            f'<tr class="row-price" data-price="{c["close"]}"><td><span class="num">{_e(c["signal_date"][5:])}</span> '
            f'<span class="dayn">第 {c["day_n"]} 天</span></td><td>{_e(c["stock_id"])} {_e(c["stock_name"])}</td>'
            f'<td>{_e(_type_label(c.get("type")))}</td>'
            f'<td class="r num">{_price(c["signal_close"])}</td><td class="r num">{_price(c["close"])}</td>'
            f'<td class="r num">{_signed(c.get("since_signal_pct"))}</td>'
            f'<td class="r num shares">{_shares(float(c["close"])):,}</td>'
            f'<td class="r num stop">{float(c["close"]) * (1 - STOP):.2f}</td><td>{_alerts(c)}</td></tr>'
            for c in active)
        table = ('<div class="table-wrap"><table><thead><tr><th>推薦日</th><th>股票</th><th>型態</th>'
                 '<th class="r">推薦日收盤</th><th class="r">現價</th><th class="r">推薦後</th><th class="r">買幾股</th>'
                 f'<th class="r">停損價</th><th>提醒</th></tr></thead><tbody>{rows}</tbody></table></div>')
    else:
        table = '<div class="ui-empty">前兩天的推薦都已失效或沒有推薦。</div>'
    inv = ""
    if invalid:
        rows = "".join(
            f'<tr><td class="num">{_e(c["signal_date"][5:])}</td><td>{_e(c["stock_id"])} {_e(c["stock_name"])}</td>'
            f'<td class="r num">{_price(c["signal_close"])}</td><td class="r num">{_price(c["close"])}</td>'
            f'<td class="r num">{_signed(c.get("since_signal_pct"))}</td></tr>' for c in invalid)
        inv = (f'<details class="invalid"><summary>已失效 {len(invalid)} 檔（跌破推薦日收盤 −{STOP:.0%}）</summary>'
               '<div class="table-wrap"><table><thead><tr><th>推薦日</th><th>股票</th><th class="r">推薦日收盤</th>'
               f'<th class="r">現價</th><th class="r">推薦後</th></tr></thead><tbody>{rows}</tbody></table></div></details>')
    return f'<section aria-labelledby="active-h">{head}{table}{inv}</section>'


# ── 近 21 天最強 ───────────────────────────────────────────

def _status(s: str) -> str:
    if s == "拉回中":
        return '<span class="chip-cons">拉回中</span>'
    return f'<span class="muted">{_e(s)}</span>'


def _leader_stock_row(r: dict) -> str:
    vr = r.get("vr5_20")
    return (
        f'<tr><td class="num" data-v="{r["rank"]}">{r["rank"]}</td><td>{_e(r["stock_id"])} {_e(r["stock_name"])}</td>'
        f'<td>{_e(r["meta_sector"])}</td><td class="r num" data-v="{r["ret21"]}">{_signed(r["ret21"])}</td>'
        f'<td class="r num" data-v="{r["from_high"]}">{_signed(r["from_high"])}</td>'
        f'<td class="r num" data-v="{r["rng5"]}">{r["rng5"]:.1f}%</td>'
        f'<td class="r num" data-v="{"" if vr is None else vr}">{"—" if vr is None else f"{vr:.2f}"}</td>'
        f'<td>{_status(r["status"])}</td></tr>'
    )


def _leaders_section(lead: dict) -> str:
    lead = lead or {}
    sectors, stocks = lead.get("sectors") or [], lead.get("stocks") or []
    head = ('<div class="sec-head"><h2 id="lead-h">近 21 天最強</h2><span class="hint">漲幅排行；標「拉回中」的是離 21 日高點'
            '已跌 10% 以上（族群 8%）。回測：前 20 名裡拉回中之後 20 天平均 +7.9%，上攻中 +5.4%，整理中 +1.8%</span></div>')
    if not stocks and not sectors:
        return f'<section aria-labelledby="lead-h">{head}<div class="ui-empty">資料不足 22 個交易日。</div></section>'
    sec_rows = "".join(
        f'<tr><td class="num">{r["rank"]}</td><td>{_e(r["sector"])} <span class="muted small">{r["n"]} 檔</span></td>'
        f'<td class="r num" data-v="{r["ret21"]}">{_signed(r["ret21"])}</td><td class="r num" data-v="{r["from_high"]}">{_signed(r["from_high"])}</td>'
        f'<td class="r num" data-v="{r["rng5"]}">{r["rng5"]:.1f}%</td><td>{_status(r["status"])}</td></tr>' for r in sectors)
    stk_rows = "".join(_leader_stock_row(r) for r in stocks)
    return (
        f'<section aria-labelledby="lead-h">{head}<div class="split">'
        f'<div><h3>族群 前 {len(sectors)}</h3><div class="table-wrap"><table><thead><tr><th>#</th><th>族群</th>'
        '<th class="r">21 日</th><th class="r">離高點</th><th class="r">5 日區間</th><th>狀態</th></tr></thead>'
        f'<tbody>{sec_rows}</tbody></table></div></div>'
        f'<div><h3>個股 前 {len(stocks)}</h3><div class="table-wrap"><table class="sortable"><thead><tr>'
        '<th data-sort>#</th><th>股票</th><th>族群</th><th class="r" data-sort>21 日</th><th class="r" data-sort>離高點</th>'
        '<th class="r" data-sort>5 日區間</th><th class="r" data-sort>量比 5/20</th><th>狀態</th></tr></thead>'
        f'<tbody>{stk_rows}</tbody></table></div><p class="score-note">點欄位標題可排序。</p></div>'
        '</div></section>'
    )


# ── 成績單 ────────────────────────────────────────────────

def _tile(label: str, value: str, note: str, lag: bool = False) -> str:
    return (f'<div class="tile"><label>{label}</label><strong class="num">{value}</strong>'
            f'<small class="{"lag" if lag else ""}">{note}</small></div>')


def _r(v) -> str:
    return _signed(v, "R", 2)


def _score_tiles(s: dict) -> str:
    n = s.get("n") or 0
    enough = n >= 20      # 已出場 20 筆以上才跟回測比高低
    ref = BACKTEST_REF

    def cmp(key, fmt):
        v = s.get(key)
        if v is None:
            return "—", f"回測 {fmt(ref[key])}", False
        lag = enough and v < ref[key]
        return fmt(v), f"回測 {fmt(ref[key])}{'（低於回測）' if lag else ''}", lag

    tiles = [_tile("推薦筆數", f'{n + (s.get("open_n") or 0) + (s.get("unfilled_n") or 0)}',
                   f'已出場 {n}・持有中 {s.get("open_n") or 0}')]
    for label, key, fmt in (("勝率", "win_rate", lambda v: f"{v:.0%}"), ("賺賠比", "payoff", lambda v: f"{v:.1f}"),
                            ("每筆平均", "mean_r", lambda v: f"{v:+.2f}R"), ("獲利因子 PF", "pf", lambda v: f"{v:.2f}")):
        value, note, lag = cmp(key, fmt)
        tiles.append(_tile(label, value, note, lag))
    tiles.append(_tile("買不到", str(s.get("unfilled_n") or 0), "隔天一字漲停"))
    return f'<div class="score">{"".join(tiles)}</div>'


def _pf(v) -> str:
    return "—" if v is None else f"{float(v):.2f}"


def _type_label(t) -> str:
    return TYPE_LABELS.get(t, (t or "",))[0]


def _month_row(r: dict, peak: float) -> str:
    mr = r.get("mean_r")
    bar = "" if mr is None else (f'<span class="bar" style="width:{abs(mr) / peak * 80:.0f}px;'
                                 f'background:var(--ui-{"up" if mr > 0 else "down"})"></span>')
    return (f'<tr><td class="num">{_e(r["month"])}</td><td class="r num">{r["n"]}</td>'
            f'<td class="r num">{_ratio(r.get("win_rate"))}</td><td class="r num">{_r(mr)}{bar}</td>'
            f'<td class="r num">{_pf(r.get("pf"))}</td></tr>')


def _score_tables(s: dict) -> str:
    by_type = "".join(
        f'<tr><td>{_e(_type_label(r["type"]))}</td><td class="r num">{r["n"]}</td>'
        f'<td class="r num">{_r(r.get("mean_r"))}</td><td class="r num">{_pf(r.get("pf"))}</td></tr>'
        for r in s.get("by_type") or [])
    months = sorted(s.get("by_month") or [], key=lambda r: r["month"], reverse=True)
    peak = max([abs(r["mean_r"]) for r in months if r.get("mean_r") is not None] or [1]) or 1
    by_month = "".join(_month_row(r, peak) for r in months)
    return (
        '<div class="split"><div><h3>分型態</h3><div class="table-wrap"><table><thead><tr><th>型態</th><th class="r">筆數</th>'
        f'<th class="r">每筆</th><th class="r">PF</th></tr></thead><tbody>{by_type}</tbody></table></div></div>'
        '<div><h3>按月（推薦月份）</h3><div class="table-wrap"><table><thead><tr><th>月份</th><th class="r">筆數</th>'
        f'<th class="r">勝率</th><th class="r">每筆</th><th class="r">PF</th></tr></thead><tbody>{by_month}</tbody></table></div></div></div>'
    )


def _pct100(v) -> str:
    return _signed(None if v is None else float(v) * 100)


def _dv(v) -> str:
    return "" if v is None else _e(v)


def _detail_row(r: dict) -> str:
    reason = r.get("exit_reason") or "等待進場"
    closed = reason not in ("持有中", "買不到", "撤回", "等待進場")
    return (
        f'<tr><td class="num" data-v="{_e(r["signal_date"])}">{_e(r["signal_date"][2:])}</td>'
        f'<td>{_e(r["stock_id"])} {_e(r.get("stock_name"))}</td><td>{_e(_type_label(r.get("type")))}</td>'
        f'<td class="r num">{_price(r.get("entry_price"))}</td>'
        f'<td class="r num">{_price(r.get("exit_price")) if closed else ""}</td>'
        f'<td class="{"" if closed else "muted"}">{_e(reason)}</td>'
        f'<td class="r num" data-v="{_dv(r.get("ret"))}">{_pct100(r.get("ret"))}</td>'
        f'<td class="r num" data-v="{_dv(r.get("r_multiple"))}">{_r(r.get("r_multiple")) if closed else "—"}</td>'
        f'<td class="r num" data-v="{_dv(r.get("mfe"))}">{_pct100(r.get("mfe"))}</td></tr>'
    )


def _detail_table(rows: list) -> str:
    if not rows:
        return ""
    return (
        f'<h3 class="detail-h">明細（{len(rows)} 筆，點欄位標題可排序）</h3><div class="table-wrap"><table class="sortable"><thead><tr>'
        '<th data-sort>推薦日</th><th>股票</th><th>型態</th><th class="r">進場</th><th class="r">出場</th><th>原因</th>'
        '<th class="r" data-sort>報酬</th><th class="r" data-sort>R</th><th class="r" data-sort>最高曾漲</th></tr></thead>'
        f'<tbody>{"".join(_detail_row(r) for r in rows)}</tbody></table></div>'
    )


def _score_section(summary: dict, rows: list) -> str:
    head = ('<div class="sec-head"><h2 id="score-h">推薦成績單</h2><span class="hint">每筆推薦依規則追蹤到出場'
            f'（停損 {STOP:.0%}、回落 {TRAIL:.0%}、{MAX_HOLD} 天），跟回測並列</span></div>')
    s = summary or {}
    if not s.get("n") and not s.get("open_n") and not rows:
        return f'<section aria-labelledby="score-h">{head}<div class="ui-empty">還沒有推薦紀錄。</div></section>'
    note = ('<p class="score-note">已出場滿 20 筆才比較高低。實際明顯比回測差時，要回頭檢查規則是否過度擬合，'
            '或市場是否改變。回測：官方行情 2025-01 起。</p>')
    return f'<section aria-labelledby="score-h">{head}{_score_tiles(s)}{note}{_score_tables(s)}{_detail_table(rows)}</section>'


# ── 組頁 ──────────────────────────────────────────────────

PAGE_CSS = r"""
.num{font-family:var(--ui-mono);font-variant-numeric:tabular-nums}
.up{color:var(--ui-up)}.down{color:var(--ui-down)}.muted{color:var(--ui-ink-2)}.small{font-size:.72rem}
.market{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--ui-border);border:1px solid var(--ui-border);border-radius:var(--ui-radius);overflow:hidden}
.mcell{padding:10px 14px;background:var(--ui-panel);min-width:0}
.mcell label{display:block;color:var(--ui-ink-3);font-size:.66rem;letter-spacing:.06em}
.mcell strong{display:block;margin-top:2px;font-size:1.05rem}
.mcell small{color:var(--ui-ink-3);font-size:.68rem}
.market-note{margin:6px 0 0;color:var(--ui-ink-3);font-size:.7rem}
.capital{position:sticky;top:var(--ui-sticky-top);z-index:5;margin-top:16px;background:var(--ui-bg);border-bottom:1px solid var(--ui-border)}
.capital-inner{display:flex;flex-wrap:wrap;align-items:center;gap:10px 22px;padding-block:10px}
.capital label{color:var(--ui-ink-2);font-size:.78rem;font-weight:600}
.capital input{width:150px;min-height:40px;padding:6px 10px;border:1px solid var(--ui-border-strong);border-radius:var(--ui-radius);background:var(--ui-panel-2);color:var(--ui-ink);font:600 1rem var(--ui-mono)}
.capital input:focus-visible{outline:2px solid var(--ui-accent);outline-offset:1px}
.rule{display:flex;gap:16px;flex-wrap:wrap;color:var(--ui-ink-2);font-size:.78rem}.rule b{color:var(--ui-ink)}
.capital-hint{color:var(--ui-ink-3);font-size:.7rem}
section{margin-top:28px}
.sec-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.sec-head h2{margin:0;font-size:1rem;font-weight:750}
.sec-head .count{color:var(--ui-accent);font:700 .78rem var(--ui-mono)}
.sec-head .hint{color:var(--ui-ink-3);font-size:.72rem}
.sector{margin-top:14px}
.sector-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;color:var(--ui-ink-2);font-size:.8rem;font-weight:700}
.sector-head .n{color:var(--ui-ink);font-family:var(--ui-mono)}
.sector-head::after{content:"";flex:1;height:1px;background:var(--ui-border)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px}
.card{display:grid;gap:10px;padding:14px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius);min-width:0;transition:border-color .15s}
.card:hover{border-color:var(--ui-border-strong)}
.c-head{display:flex;align-items:baseline;gap:8px;min-width:0}
.c-id{color:var(--ui-ink-3);font:700 .78rem var(--ui-mono)}
.c-name{font-size:1rem;font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.type{margin-left:auto;padding:1px 8px;border:1px solid var(--ui-border-strong);border-radius:4px;font-size:.7rem;font-weight:700;white-space:nowrap}
.type.box{color:var(--ui-accent);border-color:rgba(240,187,85,.5)}
.type.run{color:#8FB6F0;border-color:rgba(143,182,240,.45)}
.price{display:flex;align-items:baseline;gap:10px}
.price .close{font-size:1.3rem;font-weight:700}.price .chg{font-size:.9rem;font-weight:700}
.routes{display:flex;flex-wrap:wrap;gap:5px}
.route{padding:1px 7px;border-radius:4px;font-size:.7rem;border:1px solid var(--ui-border);color:var(--ui-ink-3)}
.route.hit{color:var(--ui-ink);border-color:var(--ui-border-strong);background:var(--ui-panel-2)}
.order{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--ui-border);border:1px solid var(--ui-border);border-radius:5px;overflow:hidden}
.order div{padding:7px 9px;background:var(--ui-panel-2);min-width:0}
.order label{display:block;color:var(--ui-ink-3);font-size:.64rem;letter-spacing:.04em}
.order strong{display:block;font-size:.92rem;font-weight:700}
.order small{color:var(--ui-ink-3);font:.68rem var(--ui-mono)}
.foot{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;color:var(--ui-ink-3);font-size:.72rem}
.alert{padding:1px 7px;border-radius:4px;font-size:.7rem;font-weight:700;color:#E39A3B;border:1px solid rgba(227,154,59,.5);background:rgba(227,154,59,.08)}
.chip-cons{padding:1px 7px;border-radius:4px;font-size:.7rem;font-weight:700;color:var(--ui-accent);border:1px solid rgba(240,187,85,.5);background:rgba(240,187,85,.08);white-space:nowrap}
.table-wrap{overflow-x:auto;border:1px solid var(--ui-border);border-radius:var(--ui-radius)}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th,td{padding:8px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--ui-border)}
th{color:var(--ui-ink-3);font-size:.68rem;font-weight:600;letter-spacing:.04em;background:var(--ui-panel)}
th[data-sort]{cursor:pointer;user-select:none}th[data-sort]:hover{color:var(--ui-ink)}
th[aria-sort=ascending]::after{content:" ▲"}th[aria-sort=descending]::after{content:" ▼"}
td.r,th.r{text-align:right}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--ui-panel)}
.dayn{display:inline-block;padding:0 6px;border-radius:4px;background:var(--ui-panel-2);color:var(--ui-ink-2);font-size:.7rem}
details.invalid{margin-top:10px}
details.invalid summary{cursor:pointer;color:var(--ui-ink-2);font-size:.82rem;min-height:36px;display:flex;align-items:center}
details.invalid summary:focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}
details.invalid table{color:var(--ui-ink-3)}
.score{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{padding:10px 12px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius)}
.tile label{display:block;color:var(--ui-ink-3);font-size:.66rem;letter-spacing:.05em}
.tile strong{display:block;font-size:1.2rem;font-weight:700}
.tile small{display:block;color:var(--ui-ink-3);font:.7rem var(--ui-mono)}.tile small.lag{color:#E39A3B}
.score-note{margin:8px 0 0;color:var(--ui-ink-3);font-size:.72rem}
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:14px;margin-top:14px}
.split h3,.detail-h{margin:0 0 6px;color:var(--ui-ink-2);font-size:.78rem;font-weight:700}.detail-h{margin-top:18px}
.bar{display:inline-block;height:6px;border-radius:3px;vertical-align:middle;margin-left:6px}
.withdrawn{margin-bottom:12px;padding:10px 14px;border:1px solid rgba(227,154,59,.5);border-radius:var(--ui-radius);background:rgba(227,154,59,.08);color:var(--ui-ink-2);font-size:.8rem}
.withdrawn strong{color:#E39A3B}.withdrawn ul{margin:6px 0 0;padding-left:18px}.withdrawn li{margin:2px 0}
.page-foot{margin-top:40px;color:var(--ui-ink-3);font-size:.7rem}
@media(max-width:760px){.market{grid-template-columns:repeat(2,minmax(0,1fr))}.cards{grid-template-columns:minmax(0,1fr)}.split{grid-template-columns:minmax(0,1fr)}.capital{position:static}}
@media(prefers-reduced-motion:reduce){.card{transition:none}}
"""

PAGE_JS = r"""
(function(){
  var KEY=%KEY%, RISK=%RISK%, STOP=%STOP%, input=document.getElementById("capital");
  function fmt(n){return Math.round(n).toLocaleString("en-US")}
  function read(){try{return localStorage.getItem(KEY)}catch(e){return null}}
  function save(v){try{localStorage.setItem(KEY,v)}catch(e){}}
  function capital(){var v=Number(String(input.value).replace(/[^\d.]/g,""));return v>0?v:0}
  function render(){
    var risk=capital()*RISK;
    document.getElementById("risk").textContent=fmt(risk);
    document.querySelectorAll(".card[data-price]").forEach(function(card){
      var p=Number(card.dataset.price), shares=Math.floor(risk/(p*STOP));
      card.querySelector(".shares").textContent=fmt(shares);
      card.querySelector(".amount").textContent="約 "+(shares*p/10000).toFixed(1)+" 萬";
      card.querySelector(".loss").textContent=(risk/10000).toFixed(1)+" 萬";
    });
    document.querySelectorAll(".row-price[data-price]").forEach(function(tr){
      var p=Number(tr.dataset.price);
      tr.querySelector(".shares").textContent=fmt(Math.floor(risk/(p*STOP)));
    });
  }
  var saved=read(); if(saved){input.value=saved}
  input.addEventListener("input",function(){save(input.value);render()});
  input.addEventListener("blur",function(){if(capital()){input.value=fmt(capital());save(input.value)}});
  render();
  document.querySelectorAll("table.sortable th[data-sort]").forEach(function(th){
    th.tabIndex=0;
    function sort(){
      var table=th.closest("table"), col=Array.prototype.indexOf.call(th.parentNode.children,th);
      var dir=th.getAttribute("aria-sort")==="descending"?"ascending":"descending";
      table.querySelectorAll("th[aria-sort]").forEach(function(x){x.removeAttribute("aria-sort")});
      th.setAttribute("aria-sort",dir);
      var body=table.tBodies[0], rows=Array.prototype.slice.call(body.rows);
      function key(tr){var td=tr.cells[col], v=td.dataset.v!==undefined?td.dataset.v:td.textContent; var n=Number(v); return v!==""&&!isNaN(n)?n:v}
      rows.sort(function(a,b){var x=key(a),y=key(b); if(x===y)return 0; if(x===""||x===undefined)return 1; if(y===""||y===undefined)return -1; return (x<y?-1:1)*(dir==="ascending"?1:-1)});
      rows.forEach(function(tr){body.appendChild(tr)});
    }
    th.addEventListener("click",sort);
    th.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();sort()}});
  });
})();
"""


def render(payload: dict) -> str:
    p = payload
    date_html = f'資料日 <b>{_e(p.get("trade_date"))}</b> 收盤'
    js = (PAGE_JS.replace("%KEY%", f'"{CAPITAL_KEY}"').replace("%RISK%", str(RISK)).replace("%STOP%", str(STOP)))
    body = (
        _market(p.get("header"), p.get("taiex_above_ma20"), p.get("taiex_ma20_gap"))
        + _capital()
        + _new_section(p.get("new") or [], p.get("withdrawn"), p.get("shareholder_date"))
        + _active_section(p.get("active") or [], p.get("invalid") or [])
        + _leaders_section(p.get("leaders"))
        + _score_section((p.get("scorecard") or {}).get(STRATEGY), (p.get("scorecard_rows") or {}).get(STRATEGY) or [])
        + f'<p class="page-foot">R＝報酬 ÷ 停損 {STOP:.0%}。成績已扣手續費與證交稅。這是研究工具的訊號整理，買賣請自行判斷。</p>'
    )
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>個股推薦 {_e(p.get("trade_date"))}</title><style>{SHARED_CSS}{PAGE_CSS}</style></head><body>'
        f'{render_topbar("個股推薦", "recommend.html", date_html)}'
        f'<main class="ui-main">{body}</main><script>{js}</script></body></html>'
    )


def generate(payload: dict, output_path: str = "docs/recommend.html") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(render(payload), encoding="utf-8")
