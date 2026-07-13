"""
生成 docs/chips.html — 獨立籌碼分頁
資料來源：meta_chips (calc_meta_chips_signals) + stock_chips (get_stock_chips_ranking)
"""
from datetime import date
from html import escape as _html_escape
from pathlib import Path
from urllib.parse import quote
import json

_CUM_THRESHOLD = 15


def _esc(value) -> str:
    """HTML-escape 外部資料（股票名稱/族群名稱等來自 TWSE/TPEx API 回應的字串），
    避免被竄改的回應內容注入進發布到 GitHub Pages 的 chips.html。"""
    return _html_escape(str(value)) if value else ""


def _make_cum_ranks(cum_data: list) -> dict:
    if not cum_data:
        return {"r3": {}, "r5": {}, "r7": {}, "v": {}}
    r3 = {r["meta_name"]: i + 1 for i, r in enumerate(sorted(cum_data, key=lambda x: x["cum3"], reverse=True))}
    r5 = {r["meta_name"]: i + 1 for i, r in enumerate(sorted(cum_data, key=lambda x: (x["cum5"] if x["cum5"] is not None else -999), reverse=True))}
    r7 = {r["meta_name"]: i + 1 for i, r in enumerate(sorted(cum_data, key=lambda x: (x["cum7"] if x["cum7"] is not None else -999), reverse=True))}
    return {"r3": r3, "r5": r5, "r7": r7, "v": {r["meta_name"]: r for r in cum_data}}


def _cum_cell(meta_name: str, cum_ranks: dict, period: str, key: str, val_key: str) -> str:
    """單一時間段累積漲跌幅欄位。"""
    if not cum_ranks:
        return "<td class='cum-cell'>─</td>"
    val = cum_ranks.get("v", {}).get(meta_name, {}).get(val_key)
    if val is None:
        return "<td class='cum-cell' style='color:#334155'>─</td>"
    sign = "+" if val > 0 else ""
    color = "#f87171" if val > 0 else "#4ade80"
    return f"<td class='cum-cell' style='color:{color}'>{sign}{val:.1f}%</td>"


def _meta_link(name: str) -> str:
    """族群名稱 → 可點擊連結，跳到 index.html 對應 META 卡片。"""
    if not name:
        return "─"
    encoded = quote(name, safe="")
    safe_name = _esc(name)
    return (
        f"<a href='index.html#meta={encoded}' "
        f"style='color:inherit;text-decoration:none;border-bottom:1px dotted #475569' "
        f"title='前往 {safe_name} 族群'>{safe_name}</a>"
    )


def _coverage_flag(data: dict) -> str:
    """族群當天橫跨的交易所有一邊資料缺失（例如 TPEx 抓取失敗）時顯示警示 icon，
    提醒這一列的 foreign_net_today/streak/margin 數字可能只反映部分成分股。"""
    if not data.get("partial_coverage"):
        return ""
    return (
        " <span style='color:#fb923c;font-size:.68rem;cursor:help' "
        "title='今日部分交易所（TWSE/TPEx）資料缺失，此數字可能只反映部分成分股'>⚠</span>"
    )


def _net_color(n: int) -> str:
    return "#f87171" if n > 0 else ("#4ade80" if n < 0 else "#64748b")


def _price_cell(close, change_pct) -> str:
    # close 可能是 NULL→NaN（停牌/全額交割），NaN 不是 None → 要一起擋，否則 int(nan) crash
    if close is None or (isinstance(close, float) and close != close):
        return "<td style='color:#334155'>─</td>"
    price_str = f"{close:.2f}" if close < 10 else (f"{close:.1f}" if close < 100 else f"{int(close)}")
    if change_pct is not None:
        sign = "+" if change_pct > 0 else ""
        color = "#f87171" if change_pct > 0 else ("#4ade80" if change_pct < 0 else "#64748b")
        return (f"<td><span style='color:#e2e8f0;font-weight:600'>{price_str}</span>"
                f"<br><span style='color:{color};font-size:.68rem'>{sign}{change_pct:.1f}%</span></td>")
    return f"<td style='color:#e2e8f0;font-weight:600'>{price_str}</td>"


def _fmt_net(n: int) -> str:
    """顯示法人買賣超張數（原始單位：股，除以 1000 = 張）。"""
    if n == 0:
        return "<span style='color:#475569'>─</span>"
    zhang = n // 1000
    sign = "+" if n > 0 else ""
    color = _net_color(n)
    if abs(zhang) >= 10000:
        return f"<span style='color:{color};font-weight:700'>{sign}{zhang/10000:.1f}萬張</span>"
    return f"<span style='color:{color};font-weight:700'>{sign}{zhang:,}張</span>"


def _streak_badge(s: int, label: str = "") -> str:
    if s == 0:
        return ""
    if s > 0:
        txt = f"外資連買 {s}日" if not label else f"{label}連買{s}日"
        return f"<span style='color:#f87171;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"
    else:
        txt = f"外資連賣 {abs(s)}日" if not label else f"{label}連賣{abs(s)}日"
        return f"<span style='color:#4ade80;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"


def _trust_streak_badge(s: int) -> str:
    if s == 0:
        return ""
    if s > 0:
        txt = f"投信連買 {s}日"
        return f"<span style='color:#fbbf24;background:rgba(120,53,15,.25);border:1px solid rgba(120,53,15,.5);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"
    else:
        txt = f"投信連賣 {abs(s)}日"
        return f"<span style='color:#60a5fa;background:rgba(30,58,138,.25);border:1px solid rgba(30,58,138,.5);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"


def _ratio_bar(ratio: float) -> str:
    w = int(ratio * 100)
    color = "#f87171" if ratio >= 0.6 else ("#fb923c" if ratio >= 0.4 else "#475569")
    pct_txt = f"{ratio*100:.0f}%"
    return (
        f"<div style='display:flex;align-items:center;gap:6px'>"
        f"<div style='flex:1;height:4px;background:#1e293b;border-radius:2px'>"
        f"<div style='height:4px;width:{w}%;background:{color};border-radius:2px'></div></div>"
        f"<span style='color:{color};font-size:.7rem;font-weight:700;min-width:30px'>{pct_txt}</span>"
        f"</div>"
    )


def _section(title: str, body: str, icon: str = "") -> str:
    return f"""
<div class="chips-section">
  <div class="cs-title">{icon} {title}</div>
  {body}
</div>"""


def _meta_streak_table(meta_chips: dict, streak_key: str, sort_desc: bool = True) -> str:
    rows = [
        (name, data.get(streak_key, 0), data)
        for name, data in meta_chips.items()
        if data.get(streak_key, 0) != 0
    ]
    rows.sort(key=lambda x: x[1], reverse=sort_desc)
    if not rows:
        return "<div class='no-data'>無資料</div>"

    html = "<table class='ct'><thead><tr><th>族群</th><th>外資今日</th><th>投信今日</th><th>狀態</th></tr></thead><tbody>"
    for name, streak, data in rows:
        f_net = data.get("foreign_net_today", 0)
        t_net = data.get("trust_net_today", 0)
        badge = _streak_badge(data.get("foreign_streak", 0)) if streak_key == "foreign_streak" else _trust_streak_badge(data.get("trust_streak", 0))
        html += f"<tr><td class='ct-name'>{_meta_link(name)}</td><td>{_fmt_net(f_net)}</td><td>{_fmt_net(t_net)}</td><td>{badge}</td></tr>"
    html += "</tbody></table>"
    return html


def _trust_meta_table(meta_chips: dict) -> str:
    rows = [
        (name, data.get("trust_streak", 0), data)
        for name, data in meta_chips.items()
        if data.get("trust_streak", 0) != 0
    ]
    rows.sort(key=lambda x: x[1], reverse=True)
    if not rows:
        return "<div class='no-data'>無資料</div>"

    html = "<table class='ct'><thead><tr><th>族群</th><th>投信今日</th><th>外資今日</th><th>狀態</th></tr></thead><tbody>"
    for name, streak, data in rows:
        f_net = data.get("foreign_net_today", 0)
        t_net = data.get("trust_net_today", 0)
        badge = _trust_streak_badge(streak)
        html += f"<tr><td class='ct-name'>{_meta_link(name)}</td><td>{_fmt_net(t_net)}</td><td>{_fmt_net(f_net)}</td><td>{badge}</td></tr>"
    html += "</tbody></table>"
    return html


def _data_date_badge(data_date, latest) -> str:
    """個股實際資料日落後該區塊最新日時，標一個橘色日期徽章，避免跨交易日資料
    （TWSE/TPEx 發布進度不同步、per-stock 取最新）被謊報成同一天。同日或缺值時不標。"""
    if not data_date or not latest or data_date == latest:
        return ""
    md = data_date[5:].replace("-", "/") if len(str(data_date)) >= 10 else str(data_date)
    return (f" <span style='color:#fbbf24;font-size:.6rem;font-weight:700;"
            f"border:1px solid #fbbf2455;border-radius:3px;padding:0 3px' "
            f"title='此列資料日期為 {data_date}，落後榜上其他列'>📅{md}</span>")


def _latest_data_date(rows: list):
    """一組列裡最新的 data_date（跨交易所 per-stock 最新時可能有多個日期）。"""
    return max((r.get("data_date") for r in rows if r.get("data_date")), default=None)


def _stock_rank_table(stocks: list, header: str, net_key: str = "foreign_net") -> str:
    if not stocks:
        return "<div class='no-data'>無資料</div>"
    latest_dd = _latest_data_date(stocks)
    html = f"<table class='ct'><thead><tr><th>#</th><th>股票</th><th>族群</th><th>收盤</th><th>{header}</th><th>投信</th></tr></thead><tbody>"
    for i, s in enumerate(stocks, 1):
        net = s.get(net_key, 0)
        trust = s.get("trust_net", 0)
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}{_data_date_badge(s.get('data_date'), latest_dd)}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td>{_fmt_net(net)}</td>"
            f"<td>{_fmt_net(trust)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _composite_mini(score: int | None) -> str:
    """Compact 0-100 score chip for chips.html tables."""
    if score is None:
        return ""
    if score >= 75:   color = "#4ade80"
    elif score >= 60: color = "#86efac"
    elif score >= 45: color = "#fbbf24"
    elif score >= 30: color = "#fb923c"
    else:             color = "#f87171"
    return (f"<span style='color:{color};border:1px solid {color}55;border-radius:4px;"
            f"padding:1px 7px;font-size:.72rem;font-weight:800'>{score}</span>")


def _inst_strong_table(rows: list) -> str:
    if not rows:
        return "<div class='no-data'>無符合條件個股</div>"
    has_comp = any(r.get("composite_score") is not None for r in rows)
    comp_th = "<th>評分</th>" if has_comp else ""
    html = (
        "<table class='ct'><thead><tr>"
        f"<th>#</th><th>股票</th><th>族群</th><th>收盤</th>{comp_th}<th>外資</th><th>投信</th>"
        "<th>外資今日</th><th>投信今日</th><th>合計</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        comp_td = f"<td>{_composite_mini(s.get('composite_score'))}</td>" if has_comp else ""
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"{comp_td}"
            f"<td>{_streak_badge(s['foreign_streak'], '外資')}</td>"
            f"<td>{_trust_streak_badge(s['trust_streak'])}</td>"
            f"<td>{_fmt_net(s.get('foreign_net') or 0)}</td>"
            f"<td>{_fmt_net(s.get('trust_net') or 0)}</td>"
            f"<td>{_fmt_net(s.get('total_net') or 0)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _inst_streak_table(rows: list, streak_key: str, net_key: str, cum_key: str, label: str) -> str:
    if not rows:
        return "<div class='no-data'>無資料</div>"
    html = (
        f"<table class='ct'><thead><tr>"
        f"<th>#</th><th>股票</th><th>族群</th><th>收盤</th><th>連買</th>"
        f"<th>{label}今日</th><th>{label}累計</th><th>10日漲幅</th>"
        f"</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        streak = s.get(streak_key, 0)
        net = s.get(net_key) or 0
        cum = s.get(cum_key) or 0
        price_cum = s.get("price_cum_pct")
        badge = _streak_badge(streak, '外資') if streak_key == 'foreign_streak' else _trust_streak_badge(streak)
        if price_cum is None:
            price_cum_html = "<span style='color:#475569'>─</span>"
        else:
            p_color = "#f87171" if price_cum >= 0 else "#4ade80"
            p_sign = "+" if price_cum >= 0 else ""
            price_cum_html = f"<span style='color:{p_color};font-weight:700'>{p_sign}{price_cum:.1f}%</span>"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td>{badge}</td>"
            f"<td>{_fmt_net(net)}</td>"
            f"<td>{_fmt_net(cum)}</td>"
            f"<td>{price_cum_html}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _margin_alert_table(alerts: list) -> str:
    if not alerts:
        return "<div class='no-data'>無融資擴張警示</div>"
    latest_dd = _latest_data_date(alerts)
    html = "<table class='ct'><thead><tr><th>#</th><th>股票</th><th>族群</th><th>收盤</th><th>融資餘額</th><th>增加量</th><th>增幅</th></tr></thead><tbody>"
    for i, s in enumerate(alerts, 1):
        pct = s["alert_pct"]
        color = "#fb923c" if pct >= 10 else "#fbbf24"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}{_data_date_badge(s.get('data_date'), latest_dd)}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td style='color:#94a3b8'>{s['margin_balance']:,}</td>"
            f"<td style='color:#f87171'>+{s['margin_change']:,}</td>"
            f"<td><span style='color:{color};font-weight:700'>+{pct:.1f}%</span></td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _margin_divergence_table(rows: list, divergence_type: str) -> str:
    if not rows:
        label = "無看空背離個股" if divergence_type == "bearish" else "無融資鬆動個股"
        return f"<div class='no-data'>{label}</div>"
    if divergence_type == "bearish":
        thead = "<thead><tr><th>#</th><th>股票</th><th>族群</th><th>收盤</th><th>融資增幅</th><th>股價跌幅</th><th>天數</th></tr></thead>"
    else:
        thead = "<thead><tr><th>#</th><th>股票</th><th>族群</th><th>收盤</th><th>融資減幅</th><th>股價漲幅</th><th>天數</th></tr></thead>"
    html = f"<table class='ct'>{thead}<tbody>"
    for i, s in enumerate(rows, 1):
        mpct = s["margin_pct"]
        ppct = s["price_pct"]
        if divergence_type == "bearish":
            m_html = f"<span style='color:#f87171;font-weight:700'>+{mpct:.1f}%</span>"
            p_html = f"<span style='color:#4ade80;font-weight:700'>{ppct:.1f}%</span>"
        else:
            m_html = f"<span style='color:#4ade80;font-weight:700'>{mpct:.1f}%</span>"
            p_html = f"<span style='color:#f87171;font-weight:700'>+{ppct:.1f}%</span>"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td>{m_html}</td>"
            f"<td>{p_html}</td>"
            f"<td style='color:#475569;font-size:.72rem'>{s['days']}日</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _concentration_table(meta_chips: dict) -> str:
    rows = [
        (name, data.get("foreign_buy_ratio", 0), data)
        for name, data in meta_chips.items()
    ]
    rows.sort(key=lambda x: x[1], reverse=True)
    if not rows:
        return "<div class='no-data'>無資料</div>"

    html = "<table class='ct'><thead><tr><th>族群</th><th>外資買超比例（今日買超家數 / 成分股）</th><th>外資今日</th></tr></thead><tbody>"
    for name, ratio, data in rows:
        buy_count = data.get("foreign_buy_count", 0)
        total = data.get("total_stocks", 1)
        f_net = data.get("foreign_net_today", 0)
        bar = _ratio_bar(ratio)
        html += (
            f"<tr>"
            f"<td class='ct-name'>{_meta_link(name)}{_coverage_flag(data)}</td>"
            f"<td style='min-width:160px'>{bar} <span style='color:#475569;font-size:.72rem'>{buy_count}/{total}</span></td>"
            f"<td>{_fmt_net(f_net)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _shareholder_table(rows: list) -> str:
    """大戶持倉排行表。rows: list of dicts with stock_id, stock_name, meta_sector,
    lv12_15_pct, lv12_15_shares, share_chg, week_chg, streak,
    company_shares, company_chg, company_pledge_pct,
    major_holder_shares, major_holder_chg, major_holder_pledge_pct,
    lv12_shares, lv12_pct, lv12_chg, lv15_shares, lv15_pct, lv15_chg"""
    if not rows:
        return "<div class='no-data'>無大戶持倉資料（尚未執行 --update-shareholder）</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>族群</th><th>收盤(週漲跌)</th>"
        "<th>近5日</th><th>近7日</th><th>近10日</th><th>近14日</th>"
        "<th>大戶持倉%</th><th>週變化</th><th>大戶張數變化</th><th>連增週</th>"
        "<th>400張大戶</th><th>1000張大戶</th>"
        "<th>公司派持股</th><th>大股東持股</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        pct = s.get("lv12_15_pct", 0) or 0
        chg = s.get("week_chg")
        streak = int(s.get("streak") or 0)

        chg_html = "<span style='color:#475569'>─</span>"
        if chg is not None:
            sign = "+" if chg > 0 else ""
            chg_color = "#f87171" if chg > 0 else ("#4ade80" if chg < 0 else "#64748b")
            chg_html = f"<span style='color:{chg_color};font-weight:700'>{sign}{chg:.2f}%</span>"

        share_chg = s.get("share_chg")
        share_chg_html = "<span style='color:#475569'>─</span>"
        if share_chg is not None:
            lots = share_chg / 1000  # 股數 → 張數
            sign = "+" if lots > 0 else ""
            color = "#f87171" if lots > 0 else ("#4ade80" if lots < 0 else "#64748b")
            share_chg_html = f"<span style='color:{color};font-weight:700'>{sign}{lots:,.0f}張</span>"

        if streak > 0:
            streak_html = (f"<span style='color:#f87171;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↑{streak}週</span>")
        elif streak < 0:
            streak_html = (f"<span style='color:#4ade80;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↓{abs(streak)}週</span>")
        else:
            streak_html = "<span style='color:#475569'>─</span>"

        pct_color = "#f87171" if pct >= 70 else ("#fbbf24" if pct >= 50 else "#94a3b8")

        company_html = _insider_cell(s.get("company_shares"), s.get("company_chg"), s.get("company_pledge_pct"))
        major_html = _insider_cell(s.get("major_holder_shares"), s.get("major_holder_chg"), s.get("major_holder_pledge_pct"))
        lv12_html = _insider_cell(s.get("lv12_shares"), s.get("lv12_chg"), s.get("lv12_pct"), pct_label="持股")
        lv15_html = _insider_cell(s.get("lv15_shares"), s.get("lv15_chg"), s.get("lv15_pct"), pct_label="持股")

        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"{_chg_cell(s.get('chg_5d'))}"
            f"{_chg_cell(s.get('chg_7d'))}"
            f"{_chg_cell(s.get('chg_10d'))}"
            f"{_chg_cell(s.get('chg_14d'))}"
            f"<td style='color:{pct_color};font-weight:700'>{pct:.1f}%</td>"
            f"<td>{chg_html}</td>"
            f"<td>{share_chg_html}</td>"
            f"<td>{streak_html}</td>"
            f"{lv12_html}"
            f"{lv15_html}"
            f"{company_html}"
            f"{major_html}"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _insider_cell(shares, chg, pct, pct_label: str = "質押") -> str:
    """內部人/大戶分層持股欄位：張數（第一行）＋ 週/月變化張數（第二行）＋ 第三行百分比
    （預設當「質押%」用，大戶分層欄位改傳 pct_label='持股' 顯示「持股%」）。缺值顯示「─」。"""
    if shares is None:
        return "<td style='color:#334155'>─</td>"
    lots = shares / 1000
    lines = [f"<span style='color:#e2e8f0;font-weight:600'>{lots:,.0f}張</span>"]
    if chg is not None:
        chg_lots = chg / 1000
        sign = "+" if chg_lots > 0 else ""
        color = "#f87171" if chg_lots > 0 else ("#4ade80" if chg_lots < 0 else "#64748b")
        lines.append(f"<span style='color:{color};font-size:.68rem'>{sign}{chg_lots:,.0f}張</span>")
    if pct is not None:
        lines.append(f"<span style='color:#64748b;font-size:.64rem'>{pct_label}{pct:.1f}%</span>")
    return f"<td>{'<br>'.join(lines)}</td>"


def _chg_cell(pct) -> str:
    """累積漲跌%欄（近5日／近7日）：紅漲綠跌，缺值「─」。回傳完整 <td>（與 _price_cell 一致，
    呼叫端不要再外包 <td>）。"""
    if pct is None:
        return "<td style='color:#334155'>─</td>"
    sign = "+" if pct > 0 else ""
    color = "#f87171" if pct > 0 else ("#4ade80" if pct < 0 else "#64748b")
    return (f"<td><span style='color:{color};font-weight:600;font-size:.72rem'>"
            f"{sign}{pct:.2f}%</span></td>")


_CSS = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"Segoe UI",sans-serif;background:#0b0f18;color:#e2e8f0;padding:12px 20px}
  .header{margin-bottom:16px}
  h1{font-size:1.1rem;font-weight:600;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}
  .mkt-bar{display:flex;align-items:center;gap:16px;margin-top:8px;padding:12px 16px;background:#141c2e;border-radius:10px;flex-wrap:wrap}
  .mkt-date{font-size:1rem;font-weight:600;color:#f1f5f9}
  .nav-links{display:flex;gap:8px;margin-top:10px}
  .nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid #1e293b;color:#64748b;text-decoration:none;transition:all .15s}
  .nav-link:hover{border-color:#475569;color:#94a3b8}
  .nav-link.active{border-color:#475569;color:#e2e8f0;background:#141c2e}
  .tab-bar{display:flex;gap:2px;margin:16px 0 0;border-bottom:1px solid #1e293b}
  .tab-btn{font-size:.8rem;padding:9px 18px;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;background:none;color:#64748b;cursor:pointer;font-weight:600;letter-spacing:.02em;transition:all .15s;border-radius:4px 4px 0 0}
  .tab-btn:hover{color:#94a3b8;background:#0f1624}
  .tab-btn.active{color:#e2e8f0;border-bottom-color:#60a5fa;background:#0f1624}
  .tab-panel{display:none;padding-top:16px}
  .tab-panel.active{display:block}
  .chips-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
  @media(max-width:900px){.chips-grid{grid-template-columns:1fr}}
  .chips-section{background:#0f1624;border:1px solid #1e293b;border-radius:10px;padding:14px 16px;margin-bottom:16px}
  .chips-section-half{background:#0f1624;border:1px solid #1e293b;border-radius:10px;padding:14px 16px}
  .cs-title{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:10px}
  .ct{width:100%;border-collapse:collapse}
  .ct th{text-align:left;padding:5px 10px;font-size:.65rem;color:#334155;text-transform:uppercase;border-bottom:1px solid #1e293b}
  .ct td{padding:7px 10px;border-bottom:1px solid #0b0f18;font-size:.8rem}
  .ct tr:last-child td{border-bottom:none}
  .ct tr:hover td{background:#141c2e}
  .ct-name{font-weight:600;color:#e2e8f0;min-width:90px}
  .ct-meta{color:#94a3b8;font-size:.72rem}
  .ct-rank{color:#334155;font-size:.72rem;font-weight:700;text-align:center;width:24px}
  .sid{color:#475569;font-size:.72rem;font-weight:600}
  .no-data{color:#334155;font-size:.8rem;padding:12px 0;text-align:center}
  .footer{margin-top:28px;font-size:.7rem;color:#1e293b;text-align:center;padding-bottom:20px}
  .cum-cell{font-size:.85rem;font-weight:700;text-align:center;white-space:nowrap;padding:4px 10px}
  @media(max-width:540px){body{padding:12px}.chips-grid{grid-template-columns:1fr}.tab-btn{padding:8px 10px;font-size:.72rem}}
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
const _tabs=['tab-signal','tab-inst','tab-margin','tab-meta','tab-holder'];
const _h=location.hash.slice(1);
switchTab(_tabs.includes(_h)?_h:'tab-signal');
</script>
"""


def _build_exchange_ui() -> tuple[str, str]:
    """讀 stock_universe.csv 建立股票代號 -> 交易所對照表，回傳 (JS 變數字串, 篩選按鈕 HTML)。"""
    exch_map: dict = {}
    try:
        import pandas as pd
        u = pd.read_csv("data/stock_universe.csv", dtype=str, usecols=["stock_id", "exchange"])
        exch_map = u.set_index("stock_id")["exchange"].to_dict()
    except Exception:
        pass
    exch_js_var = f"const EXCH={json.dumps(exch_map, ensure_ascii=False)};"
    exch_filter_btns = (
        "<div style='margin:8px 0 4px;display:flex;gap:6px'>"
        "<button class='exch-btn active' data-exch='' onclick='filterExch(this)'"
        " style='background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;"
        "padding:3px 12px;cursor:pointer;font-size:.72rem'>全部</button>"
        "<button class='exch-btn' data-exch='TWSE' onclick='filterExch(this)'"
        " style='background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;"
        "padding:3px 12px;cursor:pointer;font-size:.72rem'>🏛 上市</button>"
        "<button class='exch-btn' data-exch='TPEx' onclick='filterExch(this)'"
        " style='background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;"
        "padding:3px 12px;cursor:pointer;font-size:.72rem'>🏪 上櫃</button>"
        "</div>"
    )
    return exch_js_var, exch_filter_btns


def _build_section1(meta_chips: dict, cum_ranks: dict) -> str:
    """Section 1: META 外資連買/連賣排行"""
    buy_streak_rows = [(n, d) for n, d in meta_chips.items() if d.get("foreign_streak", 0) > 0]
    buy_streak_rows.sort(key=lambda x: x[1]["foreign_streak"], reverse=True)
    sell_streak_rows = [(n, d) for n, d in meta_chips.items() if d.get("foreign_streak", 0) < 0]
    sell_streak_rows.sort(key=lambda x: x[1]["foreign_streak"])

    def _streak_row(name: str, data: dict) -> str:
        fs = data.get("foreign_streak", 0)
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        badge = _streak_badge(fs)
        return (
            f"<tr><td class='ct-name'>{_meta_link(name)}{_coverage_flag(data)}</td>"
            f"<td>{_fmt_net(fn)}</td><td>{_fmt_net(tn)}</td>"
            f"{_cum_cell(name, cum_ranks, '3d', 'r3', 'cum3')}"
            f"{_cum_cell(name, cum_ranks, '5d', 'r5', 'cum5')}"
            f"{_cum_cell(name, cum_ranks, '7d', 'r7', 'cum7')}"
            f"<td>{badge}</td></tr>"
        )

    buy_tbody = "".join(_streak_row(n, d) for n, d in buy_streak_rows) or "<tr><td colspan='7' class='no-data'>無連買族群</td></tr>"
    sell_tbody = "".join(_streak_row(n, d) for n, d in sell_streak_rows) or "<tr><td colspan='7' class='no-data'>無連賣族群</td></tr>"

    thead = "<thead><tr><th>族群</th><th>外資今日</th><th>投信今日</th><th style='text-align:center'>3d</th><th style='text-align:center'>5d</th><th style='text-align:center'>7d</th><th>狀態</th></tr></thead>"
    return f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">▲ 外資連買族群</div>
    <table class="ct">{thead}<tbody>{buy_tbody}</tbody></table>
  </div>
  <div class="chips-section-half">
    <div class="cs-title">▼ 外資連賣族群</div>
    <table class="ct">{thead}<tbody>{sell_tbody}</tbody></table>
  </div>
</div>"""


def _build_section2(stock_chips: dict) -> str:
    """Section 2: 外資大買/大賣個股 Top10"""
    buy_stocks = stock_chips.get("foreign_top_buy", [])
    sell_stocks = stock_chips.get("foreign_top_sell", [])
    return f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">▲ 外資大買個股 Top 10</div>
    {_stock_rank_table(buy_stocks, "外資買超")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">▼ 外資大賣個股 Top 10</div>
    {_stock_rank_table(sell_stocks, "外資賣超")}
  </div>
</div>"""


def _build_section3(meta_chips: dict, cum_ranks: dict) -> str:
    """Section 3: META 投信加碼彙總"""
    trust_rows = [(n, d.get("trust_streak", 0), d) for n, d in meta_chips.items() if d.get("trust_streak", 0) != 0]
    trust_rows.sort(key=lambda x: x[1], reverse=True)

    def _trust_row(name: str, streak: int, data: dict) -> str:
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        badge = _trust_streak_badge(streak)
        return (
            f"<tr><td class='ct-name'>{_meta_link(name)}{_coverage_flag(data)}</td>"
            f"<td>{_fmt_net(tn)}</td><td>{_fmt_net(fn)}</td>"
            f"{_cum_cell(name, cum_ranks, '3d', 'r3', 'cum3')}"
            f"{_cum_cell(name, cum_ranks, '5d', 'r5', 'cum5')}"
            f"{_cum_cell(name, cum_ranks, '7d', 'r7', 'cum7')}"
            f"<td>{badge}</td></tr>"
        )

    trust_tbody = "".join(_trust_row(n, s, d) for n, s, d in trust_rows) or "<tr><td colspan='7' class='no-data'>無資料</td></tr>"
    return f"""
<div class="chips-section">
  <div class="cs-title">投信加碼 META 彙總</div>
  <table class="ct"><thead><tr><th>族群</th><th>投信今日</th><th>外資今日</th><th style='text-align:center'>3d</th><th style='text-align:center'>5d</th><th style='text-align:center'>7d</th><th>狀態</th></tr></thead>
  <tbody>{trust_tbody}</tbody></table>
</div>"""


def _build_section35(meta_chips: dict, cum_ranks: dict) -> str:
    """Section 3.5: 越跌越買 — 族群近期下跌但法人仍持續買進"""
    def _pct_cell(val, neutral_zero: bool = False) -> str:
        if val is None:
            return "<td style='text-align:center;color:#334155'>─</td>"
        sign = "+" if val > 0 else ""
        color = "#f87171" if val > 0 else ("#4ade80" if val < 0 else "#64748b")
        return f"<td style='text-align:center;color:{color};font-weight:700'>{sign}{val:.1f}%</td>"

    dip_buy_rows = []
    for name, data in meta_chips.items():
        fs = data.get("foreign_streak", 0)
        ts = data.get("trust_streak", 0)
        if fs <= 0 and ts <= 0:
            continue
        cum_vals = cum_ranks.get("v", {}).get(name, {})
        cum5 = cum_vals.get("cum5")
        if cum5 is None or cum5 >= -1.0:
            continue
        dip_buy_rows.append((name, data, cum_vals, fs, ts))
    dip_buy_rows.sort(key=lambda x: (x[2].get("cum5") or 0))  # 跌最多排前面

    def _dip_buy_row(name: str, data: dict, cum_vals: dict, fs: int, ts: int) -> str:
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        f_badge = _streak_badge(fs) if fs > 0 else ""
        t_badge = _trust_streak_badge(ts) if ts > 0 else ""
        return (
            f"<tr><td class='ct-name'>{_meta_link(name)}{_coverage_flag(data)}</td>"
            + _pct_cell(cum_vals.get("cum1"))
            + _pct_cell(cum_vals.get("cum3"))
            + _pct_cell(cum_vals.get("cum5"))
            + _pct_cell(cum_vals.get("cum7"))
            + f"<td>{_fmt_net(fn)}</td><td>{_fmt_net(tn)}</td>"
            + f"<td>{f_badge}</td><td>{t_badge}</td></tr>"
        )

    if not dip_buy_rows:
        return ""

    dip_tbody = "".join(_dip_buy_row(*r) for r in dip_buy_rows)
    dip_thead = ("<thead><tr>"
                 "<th>族群</th>"
                 "<th style='text-align:center'>今日</th>"
                 "<th style='text-align:center'>3日</th>"
                 "<th style='text-align:center'>5日</th>"
                 "<th style='text-align:center'>7日</th>"
                 "<th>外資今日</th><th>投信今日</th>"
                 "<th>外資狀態</th><th>投信狀態</th>"
                 "</tr></thead>")
    return f"""
<div class="chips-section">
  <div class="cs-title">📉 越跌越買 — 5日跌逾 1% 但法人仍連買</div>
  <table class="ct">{dip_thead}<tbody>{dip_tbody}</tbody></table>
</div>"""


def _build_section4(stock_chips: dict) -> str:
    """Section 4: 融資擴張警示"""
    margin_alerts = stock_chips.get("margin_alerts", [])
    return f"""
<div class="chips-section">
  <div class="cs-title">融資擴張警示（增幅 &gt; 5%）</div>
  {_margin_alert_table(margin_alerts)}
</div>"""


def _build_section5(meta_chips: dict) -> str:
    """Section 5: META 法人籌碼集中度"""
    return f"""
<div class="chips-section">
  <div class="cs-title">META 外資籌碼集中度（買超股數 / 總股數）</div>
  {_concentration_table(meta_chips)}
</div>"""


def _percentile_ranks(values: list) -> list:
    """回傳每個值對應的百分位排名（0~1，最大值→1.0，最小值→0.0，同值取平均名次）。
    只有 1 個值時直接給 1.0（沒有比較對象，視為滿分，避免除以 0）。"""
    n = len(values)
    if n <= 1:
        return [1.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return [r / (n - 1) for r in ranks]


def _composite_sort(candidates: list, streak_key: str) -> list:
    """連買天數跟股價累積漲幅各自轉成百分位排名、加總當綜合分數排序（Composite Score，
    參考量化多因子排名常見做法：percentile rank 加總，而非直接拿其中一個因子當排序）。
    避免像百容（漲幅大但連買天數短）跟長連買但漲幅普通的股票互相排擠掉對方——純用
    漲幅排序，長連買、股價還沒噴出來的個股會被完全擠出榜單；純用連買天數排序，
    絕對股數小的中小型股又會被大型股壓過去（2026-07-09 Cody 討論後採用此法）。"""
    if not candidates:
        return []
    streak_vals = [c.get(streak_key, 0) for c in candidates]
    price_vals = [c.get("price_cum_pct") or 0 for c in candidates]
    streak_ranks = _percentile_ranks(streak_vals)
    price_ranks = _percentile_ranks(price_vals)
    scored = list(zip(candidates, (s + p for s, p in zip(streak_ranks, price_ranks))))
    scored.sort(key=lambda x: -x[1])
    return [c for c, _score in scored]


def _build_section6(inst_scan: list) -> tuple[str, str]:
    """Section 6a/6b: 法人持續買進個股（過濾 ETF/特別股，只留 4 位數純數字代碼）"""
    import re as _re
    def _is_stock(sid: str) -> bool:
        return bool(_re.match(r'^[1-9]\d{3}$', str(sid)))

    strong = sorted(
        [x for x in inst_scan if x.get("both_streak", 0) >= 2 and _is_stock(x.get("stock_id", ""))],
        key=lambda x: -x["both_streak"]
    )
    # 排序改用「連買天數 + 股價累積漲幅」的 Composite Score（見 _composite_sort），不是
    # 單純累積買超股數或單純漲幅：純用絕對股數排名會被大型股/高股本股主宰前段班，把
    # 「外資買超雖然股數不多、但確實推動股價」的中小型股擠出榜單（2026-07-09 實測案例：
    # 百容 2483 外資連買 3 天、10 日內大漲，但用絕對股數排到第 37 名，被擠出前 15）；
    # 純用漲幅排序又會把「連買很久但股價還沒反應」的個股完全埋掉。用 min_price_cum_pct
    # 濾掉外資買超但股價完全沒動的雜訊（可能是被動式資金流入，不是有效訊號）。
    top_foreign = _composite_sort(
        [x for x in inst_scan if x.get("foreign_streak", 0) >= 3 and _is_stock(x.get("stock_id", ""))
         and (x.get("price_cum_pct") or 0) >= 5],
        "foreign_streak"
    )[:15]
    # 投信榜比照外資榜（2026-07-09 Cody 要求一致）：同樣加 price_cum_pct>=5% 篩選、
    # 排序改用 Composite Score。
    top_trust = _composite_sort(
        [x for x in inst_scan if x.get("trust_streak", 0) >= 5 and _is_stock(x.get("stock_id", ""))
         and (x.get("price_cum_pct") or 0) >= 5],
        "trust_streak"
    )[:15]

    s6a_html = f"""
<div class="chips-section">
  <div class="cs-title">🔥 強力訊號 — 外資+投信同步連買 &ge;2 日</div>
  {_inst_strong_table(strong)}
</div>"""

    s6b_html = f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">外資持續買進 Top 15（連買 &ge;3 日 + 10日漲幅 &ge;5%，綜合排序）</div>
    {_inst_streak_table(top_foreign, 'foreign_streak', 'foreign_net', 'cum_foreign', '外資')}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">投信持續買進 Top 15（連買 &ge;5 日 + 10日漲幅 &ge;5%，綜合排序）</div>
    {_inst_streak_table(top_trust, 'trust_streak', 'trust_net', 'cum_trust', '投信')}
  </div>
</div>"""
    return s6a_html, s6b_html


def _build_section7(margin_divergence: dict) -> str:
    """Section 7: 融資背離警示"""
    days_used = margin_divergence.get("days_used", 0)
    bearish = margin_divergence.get("bearish", [])
    bullish = margin_divergence.get("bullish", [])
    if days_used < 2:
        return """
<div class="chips-section">
  <div class="cs-title">融資背離警示</div>
  <div class="no-data">融資資料不足（需至少 2 個交易日），請先執行 --backfill-marg</div>
</div>"""
    days_label = f"（近 {days_used} 個交易日）"
    return f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">⚠ 看空背離 — 融資增 + 股價跌 {days_label}</div>
    {_margin_divergence_table(bearish, "bearish")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">✦ 融資鬆動 — 融資減 + 股價漲 {days_label}</div>
    {_margin_divergence_table(bullish, "bullish")}
  </div>
</div>"""


def _build_section8(shareholder_data: list) -> tuple[str, str]:
    """Section 8: 大戶持倉（集保 ≥400張）"""
    if not shareholder_data:
        return (
            "<div class='chips-section'><div class='cs-title'>大戶持倉</div>"
            "<div class='no-data'>無資料（請執行 python main.py --update-shareholder）</div></div>",
            "",
        )
    sh_increasing = [r for r in shareholder_data if (r.get("streak") or 0) > 0]
    sh_decreasing = [r for r in shareholder_data if (r.get("streak") or 0) < 0]
    sh_increasing.sort(key=lambda x: (-(x.get("streak") or 0), -(x.get("lv12_15_pct") or 0)))
    sh_decreasing.sort(key=lambda x: ((x.get("streak") or 0), -(x.get("lv12_15_pct") or 0)))

    s8_html = f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">📈 大戶連增倉 Top 30（≥400張，集保）</div>
    {_shareholder_table(sh_increasing[:30])}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">📉 大戶連減倉 Top 20</div>
    {_shareholder_table(sh_decreasing[:20])}
  </div>
</div>"""
    sh_date = shareholder_data[0].get("date", "")
    s8_note = f"<p style='color:#475569;font-size:.72rem;margin:4px 0 12px'>集保資料日期：{sh_date}｜共 {len(shareholder_data)} 支股票</p>"
    return s8_html, s8_note


def generate(
    trade_date: date,
    meta_chips: dict,
    stock_chips: dict,
    inst_scan: list = None,
    margin_divergence: dict = None,
    cum_data: list = None,
    meta_signals: dict = None,
    shareholder_data: list = None,
    output_path: str = "docs/chips.html",
) -> bool:
    """回傳是否實際寫入了 output_path；meta_chips/stock_chips 兩者皆空時不寫檔、回傳 False，
    讓呼叫端可以分辨「真的產生成功」跟「靜默跳過」，不要無條件記成功。"""
    if not meta_chips and not stock_chips:
        return False
    inst_scan = inst_scan or []
    shareholder_data = shareholder_data or []
    cum_ranks = _make_cum_ranks(cum_data or [])
    margin_divergence = margin_divergence or {}

    exch_js_var, exch_filter_btns = _build_exchange_ui()

    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]
    chips_date = stock_chips.get("chips_date", date_str)

    s1_html = _build_section1(meta_chips, cum_ranks)
    s2_html = _build_section2(stock_chips)
    s3_html = _build_section3(meta_chips, cum_ranks)
    s35_html = _build_section35(meta_chips, cum_ranks)
    s4_html = _build_section4(stock_chips)
    s5_html = _build_section5(meta_chips)
    s6a_html, s6b_html = _build_section6(inst_scan)
    s7_html = _build_section7(margin_divergence)
    s8_html, s8_note = _build_section8(shareholder_data)

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <!-- 禁止瀏覽器快取：同 index.html，每天重產、檔名固定，避免普通 F5 看到舊資料。 -->
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>台股籌碼面板 {date_str}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>台股電子半導體族群追蹤</h1>
    <div class="mkt-bar">
      <span class="mkt-date">📅 籌碼資料：{chips_date}（週{weekday}）</span>
    </div>
    <div class="nav-links">
      <a class="nav-link" href="index.html">族群績效</a>
      <a class="nav-link active" href="chips.html">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
    </div>
    <div class="tab-bar">
      <button class="tab-btn" data-tab="tab-signal" onclick="switchTab('tab-signal')">🔥 強力訊號</button>
      <button class="tab-btn" data-tab="tab-inst" onclick="switchTab('tab-inst')">外資 / 投信</button>
      <button class="tab-btn" data-tab="tab-margin" onclick="switchTab('tab-margin')">⚠ 融資警示</button>
      <button class="tab-btn" data-tab="tab-meta" onclick="switchTab('tab-meta')">META 分析</button>
      <button class="tab-btn" data-tab="tab-holder" onclick="switchTab('tab-holder')">🏦 大戶持倉</button>
    </div>
  </div>
  {exch_filter_btns}

  <div class="tab-panel" id="tab-signal">
    {s6a_html}
  </div>

  <div class="tab-panel" id="tab-inst">
    {s6b_html}
    {s2_html}
    {s1_html}
    {s3_html}
    {s35_html}
  </div>

  <div class="tab-panel" id="tab-margin">
    {s7_html}
    {s4_html}
  </div>

  <div class="tab-panel" id="tab-meta">
    {s5_html}
  </div>

  <div class="tab-panel" id="tab-holder">
    {s8_note}
    {s8_html}
  </div>

  <div class="footer">資料來源：TWSE 三大法人 ｜ 台灣：漲紅跌綠 ｜ 外資正值=買超</div>
  {_TAB_JS}
  <script>
  {exch_js_var}
  // 在個股代號旁加上市/上櫃 badge
  document.querySelectorAll('span.sid').forEach(function(span){{
    const exch=EXCH[span.textContent.trim()];
    if(exch==='TWSE') span.insertAdjacentHTML('afterend','<span style="color:#60a5fa;font-size:.6rem;border:1px solid #1e3a5f;border-radius:3px;padding:0 4px;margin-left:4px">上市</span>');
    else if(exch==='TPEx') span.insertAdjacentHTML('afterend','<span style="color:#a78bfa;font-size:.6rem;border:1px solid #3b1f6e;border-radius:3px;padding:0 4px;margin-left:4px">上櫃</span>');
  }});
  function filterExch(btn){{
    document.querySelectorAll('.exch-btn').forEach(b=>{{b.style.background='transparent';b.style.color='#94a3b8';b.style.borderColor='#334155';b.classList.remove('active')}});
    btn.style.background='#1e293b';btn.style.color='#e2e8f0';btn.style.borderColor='#475569';btn.classList.add('active');
    const exch=btn.dataset.exch;
    document.querySelectorAll('table.ct tbody tr').forEach(tr=>{{
      const sid=tr.querySelector('.sid');
      if(!sid)return;
      const ex=EXCH[sid.textContent.trim()]||'';
      tr.style.display=(!exch||ex===exch)?'':'none';
    }});
  }}
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return True
