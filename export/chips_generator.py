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
        return "<td class='cum-cell' style='color:var(--subtle)'>─</td>"
    sign = "+" if val > 0 else ""
    color = "#E6432F" if val > 0 else "#37B25C"
    return f"<td class='cum-cell' style='color:{color}'>{sign}{val:.1f}%</td>"


def _meta_link(name: str) -> str:
    """族群名稱 → 可點擊連結，跳到 index.html 對應 META 卡片。"""
    if not name:
        return "─"
    encoded = quote(name, safe="")
    safe_name = _esc(name)
    return (
        f"<a href='index.html#meta={encoded}' "
        f"style='color:inherit;text-decoration:none;border-bottom:1px dotted var(--border-strong)' "
        f"title='前往 {safe_name} 族群'>{safe_name}</a>"
    )


def _coverage_flag(data: dict) -> str:
    """族群當天橫跨的交易所有一邊資料缺失（例如 TPEx 抓取失敗）時顯示警示 icon，
    提醒這一列的 foreign_net_today/streak/margin 數字可能只反映部分成分股。"""
    if not data.get("partial_coverage"):
        return ""
    return (
        " <span class='coverage-flag' "
        "title='今日部分交易所（TWSE/TPEx）資料缺失，此數字可能只反映部分成分股'>資料不完整</span>"
    )


def _net_color(n: int) -> str:
    return "#E6432F" if n > 0 else ("#37B25C" if n < 0 else "var(--muted)")


def _price_cell(close, change_pct) -> str:
    # close 可能是 NULL→NaN（停牌/全額交割），NaN 不是 None → 要一起擋，否則 int(nan) crash
    if close is None or (isinstance(close, float) and close != close):
        return "<td style='color:var(--subtle)'>─</td>"
    price_str = f"{close:.2f}" if close < 10 else (f"{close:.1f}" if close < 100 else f"{int(close)}")
    if change_pct is not None:
        sign = "+" if change_pct > 0 else ""
        color = "#E6432F" if change_pct > 0 else ("#37B25C" if change_pct < 0 else "var(--muted)")
        return (f"<td><span style='color:var(--text);font-weight:600'>{price_str}</span>"
                f"<br><span style='color:{color};font-size:.68rem'>{sign}{change_pct:.1f}%</span></td>")
    return f"<td style='color:var(--text);font-weight:600'>{price_str}</td>"


def _fmt_net(n: int) -> str:
    """顯示法人買賣超張數（原始單位：股，除以 1000 = 張）。"""
    if n == 0:
        return "<span style='color:var(--subtle)'>─</span>"
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
        return f"<span style='color:#E6432F;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"
    else:
        txt = f"外資連賣 {abs(s)}日" if not label else f"{label}連賣{abs(s)}日"
        return f"<span style='color:#37B25C;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"


def _trust_streak_badge(s: int) -> str:
    if s == 0:
        return ""
    if s > 0:
        txt = f"投信連買 {s}日"
        return f"<span style='color:#F0BB55;background:rgba(120,53,15,.25);border:1px solid rgba(120,53,15,.5);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"
    else:
        txt = f"投信連賣 {abs(s)}日"
        return f"<span style='color:#60a5fa;background:rgba(30,58,138,.25);border:1px solid rgba(30,58,138,.5);border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>{txt}</span>"


def _ratio_bar(ratio: float) -> str:
    w = int(ratio * 100)
    color = "#E6432F" if ratio >= 0.6 else ("#fb923c" if ratio >= 0.4 else "var(--subtle)")
    pct_txt = f"{ratio*100:.0f}%"
    return (
        f"<div style='display:flex;align-items:center;gap:6px'>"
        f"<div style='flex:1;height:4px;background:var(--surface-2);border-radius:2px'>"
        f"<div style='height:4px;width:{w}%;background:{color};border-radius:2px'></div></div>"
        f"<span style='color:{color};font-size:.7rem;font-weight:700;min-width:30px'>{pct_txt}</span>"
        f"</div>"
    )


def _section(title: str, body: str, icon: str = "") -> str:
    return f"""
<div class="chips-section">
  <div class="cs-title">{title}</div>
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
    return (f" <span style='color:#F0BB55;font-size:.6rem;font-weight:700;"
            f"border:1px solid #F0BB5555;border-radius:3px;padding:0 3px' "
            f"title='此列資料日期為 {data_date}，落後榜上其他列'>資料日 {md}</span>")


def _latest_data_date(rows: list):
    """一組列裡最新的 data_date（跨交易所 per-stock 最新時可能有多個日期）。"""
    return max((r.get("data_date") for r in rows if r.get("data_date")), default=None)


def _section_date_suffix(rows: list) -> str:
    """該區塊自己最新一筆的資料日期，標在 section/半版標題旁。

    跟 _data_date_badge（逐列、跟區塊內最新日比）是不同基準：那個只在區塊內「混用不同
    交易日」時才會標，若整個區塊一致落後 headline 一天（區塊內同日），逐列徽章會全部
    不標，畫面上完全看不出這個區塊其實是舊資料。這裡改成不論如何都標出區塊自己的
    資料日期，讓「整批落後」也有跡可尋（見 debug-tasks.md #5）。無資料時不標。"""
    latest = _latest_data_date(rows)
    if not latest:
        return ""
    md = latest[5:].replace("-", "/") if len(str(latest)) >= 10 else str(latest)
    return f" <span class='cs-date'>· 資料日 {md}</span>"


def _stock_rank_table(stocks: list, header: str, net_key: str = "foreign_net") -> str:
    """外資籌碼個股排行——只看外資（獨立區塊，不混投信，見 debug-tasks.md 外資/法人拆分）。
    「外資持股%」欄位是存量資料（TWSE MI_QFIIS/TPEx tpex_3insti_qfii，全體外資持有股數/
    總發行股數），跟 {header} 欄（三大法人今日買賣超，流量資料）是不同維度、不同資料源，
    缺值（新股/未上榜)顯示「─」不報錯。"""
    if not stocks:
        return "<div class='no-data'>無資料</div>"
    latest_dd = _latest_data_date(stocks)
    html = (
        f"<table class='ct'><thead><tr><th>#</th><th>股票</th><th>族群</th><th>收盤</th>"
        f"<th>{header}</th><th>外資持股%</th></tr></thead><tbody>"
    )
    for i, s in enumerate(stocks, 1):
        net = s.get(net_key, 0)
        foreign_pct = s.get("foreign_pct")
        foreign_pct_html = "<span style='color:var(--subtle)'>─</span>" if foreign_pct is None else f"{foreign_pct:.1f}%"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}{_data_date_badge(s.get('data_date'), latest_dd)}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td>{_fmt_net(net)}</td>"
            f"<td>{foreign_pct_html}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _composite_mini(score: int | None) -> str:
    """Compact 0-100 score chip for chips.html tables."""
    if score is None:
        return ""
    if score >= 75:   color = "#37B25C"
    elif score >= 60: color = "#86efac"
    elif score >= 45: color = "#F0BB55"
    elif score >= 30: color = "#fb923c"
    else:             color = "#E6432F"
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
        "<th>外資今日</th><th>投信今日</th><th>合計</th><th>買超占量</th><th>10日</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        comp_td = f"<td>{_composite_mini(s.get('composite_score'))}</td>" if has_comp else ""
        flow_ratio = s.get("institutional_flow_ratio_pct")
        flow_html = "─" if flow_ratio is None else f"{flow_ratio:.2f}%"
        price_cum = s.get("price_cum_pct")
        price_html = "─" if price_cum is None else f"{price_cum:+.1f}%"
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
            f"<td><strong>{flow_html}</strong></td>"
            f"<td>{price_html}</td>"
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
            price_cum_html = "<span style='color:var(--subtle)'>─</span>"
        else:
            p_color = "#E6432F" if price_cum >= 0 else "#37B25C"
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
        color = "#fb923c" if pct >= 10 else "#F0BB55"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}{_data_date_badge(s.get('data_date'), latest_dd)}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td style='color:var(--subtle)'>{s['margin_balance']:,}</td>"
            f"<td style='color:#E6432F'>+{s['margin_change']:,}</td>"
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
            m_html = f"<span style='color:#E6432F;font-weight:700'>+{mpct:.1f}%</span>"
            p_html = f"<span style='color:#37B25C;font-weight:700'>{ppct:.1f}%</span>"
        else:
            m_html = f"<span style='color:#37B25C;font-weight:700'>{mpct:.1f}%</span>"
            p_html = f"<span style='color:#E6432F;font-weight:700'>+{ppct:.1f}%</span>"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s['stock_name'])}</td>"
            f"<td class='ct-meta'>{_meta_link(s['meta_sector'])}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
            f"<td>{m_html}</td>"
            f"<td>{p_html}</td>"
            f"<td style='color:var(--muted);font-size:.75rem'>{s['days']}日</td>"
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
            f"<td style='min-width:160px'>{bar} <span style='color:var(--muted);font-size:.75rem'>{buy_count}/{total}</span></td>"
            f"<td>{_fmt_net(f_net)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _calc_trend_svg(trend: list) -> dict | None:
    """把 get_shareholder_trend() 的輸出（舊到新的 [{date, lv12_15_pct}, ...]）換算成
    SVG viewBox座標。固定 viewBox "0 0 92 32"：Y軸文字留白 x=0~20、圖表繪製區
    x=22~92/y=2~18、X軸日期文字 y=29。

    回傳 None 時代表資料點不足2筆畫不出線，呼叫端要顯示「資料不足」文字。"""
    if len(trend) < 2:
        return None

    values = [t["lv12_15_pct"] for t in trend]
    lo, hi = min(values), max(values)
    rng = hi - lo

    n = len(trend)
    plot_left, plot_right = 22.0, 92.0
    plot_top, plot_bottom = 2.0, 18.0

    line_points = []
    for i, t in enumerate(trend):
        x = plot_left + (plot_right - plot_left) * i / (n - 1)
        if rng == 0:
            y = (plot_top + plot_bottom) / 2  # 防除零：全部持平畫在垂直置中
        else:
            y = plot_bottom - (t["lv12_15_pct"] - lo) / rng * (plot_bottom - plot_top)
        line_points.append(f"{x:.1f},{y:.1f}")

    area_points = line_points + [f"{plot_right:.1f},20.0", f"{plot_left:.1f},20.0"]

    x_labels = []
    for t in trend:
        # "2026-07-17" -> "07/17"
        parts = t["date"].split("-")
        x_labels.append(f"{parts[1]}/{parts[2]}")

    return {
        "line_points": line_points,
        "area_points": area_points,
        "x_labels": x_labels,
        "y_max_label": f"{hi:.1f}",
        "y_min_label": f"{lo:.1f}",
        "end_point": line_points[-1],
    }


def _holder_card_html(row: dict, rank: int, max_abs_week_chg: float) -> str:
    """單張大戶持倉卡片：排名/名稱/收盤、週變化發散長條(依max_abs_week_chg動態縮放)、
    次要指標(連增減週數/張數變化/1000張以上)一行小字、近N週趨勢SVG走勢圖。"""
    week_chg = row.get("week_chg") or 0.0
    direction = "up" if week_chg >= 0 else "down"
    bar_pct = abs(week_chg) / max_abs_week_chg * 50 if max_abs_week_chg > 0 else 0
    streak = row.get("streak") or 0
    streak_txt = f"連增{streak}週" if streak > 0 else (f"連減{abs(streak)}週" if streak < 0 else "")
    streak_pill = (
        f'<span class="hc-streak-pill {direction}">{streak_txt}</span>' if streak_txt else ""
    )

    price_cls = "up" if (row.get("change_pct") or 0) >= 0 else "down"
    price_pct = row.get("change_pct")
    price_pct_str = f"{price_pct:+.1f}%" if price_pct is not None else "─"
    close_val = row.get("close")
    close_str = f"{close_val}" if close_val is not None else "─"

    share_chg = row.get("share_chg")
    share_chg_lots = round(share_chg / 1000) if share_chg is not None else None
    share_chg_str = f"{share_chg_lots:+,}張" if share_chg_lots is not None else "─"
    share_chg_color = "var(--up)" if (share_chg_lots or 0) >= 0 else "var(--down)"

    trend = _calc_trend_svg(row.get("trend") or [])
    if trend is None:
        trend_html = '<div class="hc-trend-empty">近期資料不足，尚無法繪製趨勢</div>'
    else:
        line = " ".join(trend["line_points"])
        area = " ".join(trend["area_points"])
        end_x, end_y = trend["end_point"].split(",")
        x_label_els = []
        n_labels = len(trend["x_labels"])
        for i, lbl in enumerate(trend["x_labels"]):
            x = 22.0 + (92.0 - 22.0) * i / (n_labels - 1) if n_labels > 1 else 22.0
            anchor = "start" if i == 0 else ("end" if i == n_labels - 1 else "middle")
            x_label_els.append(f'<text x="{x:.1f}" y="29" text-anchor="{anchor}">{_esc(lbl)}</text>')
        trend_dir_cls = " down" if direction == "down" else ""
        trend_html = f"""<div class="hc-trend{trend_dir_cls}">
  <svg viewBox="0 0 92 32">
    <line class="trend-grid" x1="22" y1="18" x2="92" y2="18"/>
    <polyline class="trend-area" points="{area}"/>
    <polyline class="trend-line" points="{line}"/>
    <circle class="trend-end" cx="{end_x}" cy="{end_y}" r="2"/>
    <text class="axis-label" x="20" y="6">{trend['y_max_label']}</text>
    <text class="axis-label" x="20" y="19">{trend['y_min_label']}</text>
    {''.join(x_label_els)}
  </svg>
</div>"""

    return f"""<div class="holder-card">
  <div class="hc-top">
    <span class="hc-rank">#{rank}</span>
    <span class="hc-name">{_esc(row.get('stock_name', ''))}</span><span class="hc-sid">{_esc(row['stock_id'])}</span>
    <span class="hc-price {price_cls}">{close_str} <span style="font-size:.62rem">{price_pct_str}</span></span>
  </div>
  <div class="hc-meta">{_esc(row.get('meta_sector', ''))}</div>
  <div class="hc-bar-row">
    <div class="hc-divbar"><span class="{direction}" style="width:{bar_pct:.1f}%"></span></div>
    <span class="hc-week {direction}">{week_chg:+.1f}%</span>
    <span class="hc-abs">{row.get('lv12_15_pct') or 0:.1f}%</span>
  </div>
  <div class="hc-badges">
    {streak_pill}
    <span>張數變化 <b style="color:{share_chg_color}">{share_chg_str}</b></span>
    <span>1000張以上 <b>{row.get('lv15_pct') or 0:.1f}%</b></span>
  </div>
  {trend_html}
</div>"""


def _holder_column_html(rows: list, direction: str) -> str:
    """一整欄（連增倉或連減倉）的卡片grid。direction只影響空狀態文案，實際每張卡的
    up/down是各自依自己的week_chg正負決定（連減倉欄位裡理論上week_chg都是負的，但
    這裡不假設，用各自實際符號渲染，比較穩健）。"""
    if not rows:
        return "<div class='no-data'>無資料</div>"
    max_abs_week_chg = max((abs(r.get("week_chg") or 0) for r in rows), default=0) or 1.0
    cards = "".join(
        _holder_card_html(row, i + 1, max_abs_week_chg) for i, row in enumerate(rows)
    )
    return f'<div class="holder-grid">{cards}</div>'


def _shareholder_table(rows: list) -> str:
    """大戶籌碼排行表（集保 TDCC 分層）。rows: list of dicts with stock_id,
    stock_name, meta_sector, lv12_15_pct, lv12_15_shares, share_chg, week_chg, streak,
    lv15_shares, lv15_pct, lv15_chg。

    兩層大戶指標：
    - 400張以上大戶%＝lv12_15_pct（TDCC level 12+13+14+15 累計，≥400,001股，包含1000張以上
      那層），也是本表主指標，streak/週變化/連增週都是以這個累計值為基礎追蹤。
    - 1000張以上大戶%＝lv15_pct（level 15 單獨，≥1,000,001股）。
    （曾經有過的「400張大戶」窄 band 欄位用 lv12_shares，那其實只算 level 12 單一級距
    400,001~600,000股，不是累計≥400張，命名跟數字對不上，已拿掉。）

    董監持股（company_shares/major_holder_shares 等）獨立在 _insider_holdings_table()，
    跟大戶籌碼是不同資料源（TDCC 集保 vs 公開觀測站董監申報），拆開避免混為一談。"""
    if not rows:
        return "<div class='no-data'>無大戶籌碼資料（尚未執行 --update-shareholder）</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>族群</th><th>收盤(週漲跌)</th>"
        "<th>近5日</th><th>近7日</th><th>近10日</th><th>近14日</th>"
        "<th>400張以上大戶%</th><th>週變化</th><th>大戶張數變化</th><th>連增週</th>"
        "<th>1000張以上大戶</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        pct = s.get("lv12_15_pct", 0) or 0
        chg = s.get("week_chg")
        streak = int(s.get("streak") or 0)

        chg_html = "<span style='color:var(--subtle)'>─</span>"
        if chg is not None:
            sign = "+" if chg > 0 else ""
            chg_color = "#E6432F" if chg > 0 else ("#37B25C" if chg < 0 else "var(--muted)")
            chg_html = f"<span style='color:{chg_color};font-weight:700'>{sign}{chg:.2f}%</span>"

        share_chg = s.get("share_chg")
        share_chg_html = "<span style='color:var(--subtle)'>─</span>"
        if share_chg is not None:
            lots = share_chg / 1000  # 股數 → 張數
            sign = "+" if lots > 0 else ""
            color = "#E6432F" if lots > 0 else ("#37B25C" if lots < 0 else "var(--muted)")
            share_chg_html = f"<span style='color:{color};font-weight:700'>{sign}{lots:,.0f}張</span>"

        if streak > 0:
            streak_html = (f"<span style='color:#E6432F;background:rgba(127,29,29,.2);border:1px solid rgba(127,29,29,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↑{streak}週</span>")
        elif streak < 0:
            streak_html = (f"<span style='color:#37B25C;background:rgba(6,78,59,.2);border:1px solid rgba(6,78,59,.4);"
                           f"border-radius:4px;padding:1px 7px;font-size:.7rem;font-weight:700'>↓{abs(streak)}週</span>")
        else:
            streak_html = "<span style='color:var(--subtle)'>─</span>"

        pct_color = "#E6432F" if pct >= 70 else ("#F0BB55" if pct >= 50 else "var(--subtle)")

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
            f"{lv15_html}"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _insider_holdings_table(rows: list) -> str:
    """董監持股表（公司派/大股東持股申報，跟大戶籌碼是不同資料源）。
    rows: list of dicts with stock_id, stock_name, meta_sector, close, change_pct,
    company_shares, company_chg, company_pledge_pct,
    major_holder_shares, major_holder_chg, major_holder_pledge_pct"""
    if not rows:
        return "<div class='no-data'>無董監持股資料（尚未執行 --update-insider-holdings）</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>族群</th><th>收盤(週漲跌)</th>"
        "<th>公司派持股</th><th>大股東持股</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        company_html = _insider_cell(s.get("company_shares"), s.get("company_chg"), s.get("company_pledge_pct"))
        major_html = _insider_cell(s.get("major_holder_shares"), s.get("major_holder_chg"), s.get("major_holder_pledge_pct"))
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{_esc(s['stock_id'])}</span> {_esc(s.get('stock_name',''))}</td>"
            f"<td class='ct-meta'>{_meta_link(s.get('meta_sector',''))}</td>"
            f"{_price_cell(s.get('close'), s.get('change_pct'))}"
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
        return "<td style='color:var(--subtle)'>─</td>"
    lots = shares / 1000
    lines = [f"<span style='color:var(--text);font-weight:600'>{lots:,.0f}張</span>"]
    if chg is not None:
        chg_lots = chg / 1000
        sign = "+" if chg_lots > 0 else ""
        color = "#E6432F" if chg_lots > 0 else ("#37B25C" if chg_lots < 0 else "var(--muted)")
        lines.append(f"<span style='color:{color};font-size:.68rem'>{sign}{chg_lots:,.0f}張</span>")
    if pct is not None:
        lines.append(f"<span style='color:var(--muted);font-size:.75rem'>{pct_label}{pct:.1f}%</span>")
    return f"<td>{'<br>'.join(lines)}</td>"


def _chg_cell(pct) -> str:
    """累積漲跌%欄（近5日／近7日）：紅漲綠跌，缺值「─」。回傳完整 <td>（與 _price_cell 一致，
    呼叫端不要再外包 <td>）。"""
    if pct is None:
        return "<td style='color:var(--subtle)'>─</td>"
    sign = "+" if pct > 0 else ""
    color = "#E6432F" if pct > 0 else ("#37B25C" if pct < 0 else "var(--muted)")
    return (f"<td><span style='color:{color};font-weight:600;font-size:.72rem'>"
            f"{sign}{pct:.2f}%</span></td>")


_CSS = """
  :root{--bg:#080B12;--surface:#0F1420;--surface-2:#161D2C;--surface-3:#1E2738;--border:#293346;--border-strong:#37435C;--text:#DADFE8;--muted:#98A0B4;--subtle:#636B80;--accent:#F0BB55;--accent-soft:rgba(240,187,85,.16);--focus:#F0BB55;--up:#E6432F;--down:#37B25C;--radius:8px}
  *{box-sizing:border-box}
  html{background:var(--bg);overflow-x:hidden}
  body{margin:0;min-width:320px;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;background:var(--bg);color:var(--text);line-height:1.5;overflow-x:hidden}
  button,input{font:inherit}button{touch-action:manipulation}
  a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
  .skip-link{position:fixed;left:12px;top:8px;z-index:1000;transform:translateY(-160%);padding:9px 13px;background:var(--text);color:var(--bg);border-radius:6px;font-weight:750}
  .skip-link:focus{transform:translateY(0)}
  .app-shell{min-height:100dvh}
  .topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:28px;min-height:64px;padding:0 24px;border-bottom:1px solid var(--border);background:rgba(8,11,18,.96);backdrop-filter:blur(12px)}
  .brand-lockup{display:flex;align-items:baseline;gap:12px;min-width:max-content}
  h1{margin:0;font-size:1rem;font-weight:760;color:var(--text);letter-spacing:.015em}
  .page-name{font-size:.75rem;color:var(--accent);font-weight:750;padding-left:12px;border-left:1px solid var(--border-strong)}
  .nav-links{display:flex;align-items:stretch;gap:2px;align-self:stretch;white-space:nowrap}
  .nav-link{display:inline-flex;align-items:center;padding:0 13px;border-bottom:2px solid transparent;color:var(--muted);text-decoration:none;font-size:.8125rem;font-weight:650;transition:color .16s,background .16s,border-color .16s}
  .nav-link:hover{color:var(--text);background:var(--surface)}
  .nav-link.active{color:var(--text);border-bottom-color:var(--accent);background:var(--surface)}
  .data-status{margin-left:auto;display:grid;grid-template-columns:auto auto;column-gap:10px;align-items:baseline;white-space:nowrap}
  .data-status span{color:var(--subtle);font-size:.6875rem;font-weight:700}
  .data-status strong{font-size:.8125rem;font-weight:720;font-variant-numeric:tabular-nums;color:var(--text)}
  .workspace{display:grid;grid-template-columns:216px minmax(0,1fr);max-width:1840px;margin:0 auto;min-height:calc(100dvh - 64px)}
  .section-nav{border-right:1px solid var(--border);background:#0B0F19;padding:20px 14px}
  .section-nav-inner{position:sticky;top:84px}
  .section-nav-label{padding:0 10px 9px;color:var(--subtle);font-size:.6875rem;font-weight:800;letter-spacing:.08em}
  .tab-groups{display:flex;flex-direction:column;gap:14px}
  .tab-group{display:flex;flex-direction:column;gap:4px}
  .tab-group-label{font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;color:var(--subtle);padding-left:2px}
  .tab-bar{display:flex;flex-direction:column;gap:3px}
  .tab-btn{width:100%;min-height:44px;padding:9px 11px;border:0;border-left:3px solid transparent;border-radius:6px;background:transparent;color:var(--muted);text-align:left;cursor:pointer;font-size:.8125rem;font-weight:680;transition:background .16s,color .16s,border-color .16s}
  .tab-btn:hover{color:var(--text);background:var(--surface)}
  .tab-btn:active{background:var(--surface-3)}
  .tab-btn.active{color:var(--text);border-left-color:var(--accent);background:var(--accent-soft)}
  .section-nav-note{margin:18px 10px 0;padding-top:14px;border-top:1px solid var(--border);color:var(--subtle);font-size:.6875rem;line-height:1.65}
  .main-content{min-width:0;padding:20px 24px 32px}
  .chips-toolbar{position:sticky;top:76px;z-index:10;display:flex;align-items:end;gap:12px;margin:0 0 16px;padding:10px 12px;background:rgba(15,20,32,.97);border:1px solid var(--border);border-radius:var(--radius);box-shadow:0 8px 24px rgba(3,4,7,.24)}
  .search-field{display:grid;grid-template-columns:auto minmax(220px,320px);align-items:center;gap:9px;color:var(--muted);font-size:.75rem;font-weight:700}
  .search-field input{width:100%;height:40px;padding:8px 11px;color:var(--text);background:var(--bg);border:1px solid var(--border-strong);border-radius:6px}
  .search-field input::placeholder{color:var(--subtle)}
  .exchange-filter{display:flex;border:1px solid var(--border-strong);border-radius:6px;overflow:hidden}
  .exch-btn{min-width:62px;height:40px;padding:7px 13px;background:transparent;color:var(--muted);border:0;border-right:1px solid var(--border-strong);cursor:pointer;font-size:.8125rem;font-weight:650}
  .exch-btn:last-child{border-right:0}.exch-btn:hover{color:var(--text);background:var(--surface-2)}
  .exch-btn.active{color:var(--text);background:var(--accent-soft);box-shadow:inset 0 -2px 0 var(--accent)}
  .filter-result{margin-left:auto;min-height:20px;color:var(--muted);font-size:.75rem;font-variant-numeric:tabular-nums}
  .tab-panel{display:none;min-width:0}.tab-panel.active{display:block}
  .chips-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-bottom:14px}
  .chips-section,.chips-section-half{min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 14px;overflow:hidden}
  .chips-section{margin-bottom:14px}
  .cs-title{font-size:.8125rem;font-weight:780;color:var(--text);margin-bottom:8px}
  .cs-description,.data-note{margin:0 0 11px;color:var(--muted);font-size:.75rem;max-width:90ch}
  .cs-date{color:var(--subtle);font-weight:600}.coverage-flag{display:inline-block;margin-left:5px;padding:1px 5px;border:1px solid #b77935;border-radius:4px;color:#ffc37d;font-size:.625rem;font-weight:750;cursor:help}
  .table-shell{max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;border:1px solid var(--border);border-radius:6px;scrollbar-width:thin;scrollbar-color:var(--border-strong) transparent}
  .ct{width:100%;min-width:max-content;border-collapse:collapse;font-variant-numeric:tabular-nums}
  .ct th{position:sticky;top:0;z-index:1;text-align:left;padding:7px 9px;font-size:.6875rem;color:var(--muted);background:var(--surface-2);border-bottom:1px solid var(--border);white-space:nowrap}
  .ct td{padding:7px 9px;border-bottom:1px solid var(--border);font-size:.8125rem;white-space:nowrap}
  .ct tbody tr:nth-child(even) td{background:rgba(22,29,44,.2)}
  .ct tr:last-child td{border-bottom:none}.ct tr:hover td{background:var(--surface-3)}
  .sort-button{display:inline-flex;align-items:center;gap:5px;min-height:32px;padding:3px 4px;border:0;background:transparent;color:inherit;font-weight:inherit;cursor:pointer}
  .sort-button::after{content:"↕";color:var(--subtle);font-size:.6875rem}
  th[aria-sort="ascending"] .sort-button::after{content:"↑";color:var(--accent)}
  th[aria-sort="descending"] .sort-button::after{content:"↓";color:var(--accent)}
  .table-toggle{display:none;width:100%;min-height:44px;margin-top:8px;border:1px solid var(--border-strong);border-radius:6px;background:var(--surface-2);color:var(--text);cursor:pointer}
  [hidden]{display:none!important}
  .market-badge{display:inline-block;margin-left:5px;padding:0 4px;border:1px solid var(--border-strong);border-radius:3px;color:var(--muted);font-size:.625rem}
  .market-badge.twse{border-color:#416d9f;color:#9bc7ff}.market-badge.tpex{border-color:#6e5999;color:#cabaff}
  .ct-name{font-weight:700;color:var(--text);min-width:90px}.ct-meta{color:var(--muted);font-size:.75rem}
  .ct-rank{color:var(--subtle);font-size:.75rem;font-weight:700;text-align:center;width:32px}.sid{color:var(--muted);font-size:.75rem;font-weight:720}
  .no-data{color:var(--muted);font-size:.8125rem;padding:18px 8px;text-align:center;border:1px dashed var(--border);border-radius:6px;background:rgba(8,11,18,.35)}
  .footer{margin:28px 0 0;font-size:.6875rem;color:var(--subtle);text-align:center;padding-bottom:8px}
  .cum-cell{font-size:.8125rem;font-weight:700;text-align:center;white-space:nowrap;padding:6px 9px}
  @media(max-width:1100px){
    .topbar{gap:16px}.workspace{display:block}.section-nav{position:sticky;top:64px;z-index:15;padding:8px 16px;border-right:0;border-bottom:1px solid var(--border)}
    .section-nav-inner{position:static}.section-nav-label,.section-nav-note,.tab-group-label{display:none}.tab-groups{flex-direction:row;gap:4px;overflow-x:auto;scrollbar-width:thin}.tab-group{flex-direction:row;gap:4px}.tab-bar{flex-direction:row;gap:4px}
    .tab-btn{flex:0 0 auto;width:auto;padding:8px 13px;border-left:0;border-bottom:2px solid transparent;border-radius:6px 6px 0 0;text-align:center;white-space:nowrap}
    .tab-btn.active{border-left-color:transparent;border-bottom-color:var(--accent)}.chips-toolbar{top:124px}
  }
  @media(max-width:760px){
    .topbar{position:static;min-height:auto;padding:12px 14px;flex-wrap:wrap;gap:10px 16px}.brand-lockup{width:100%}.nav-links{height:42px;order:3;width:100%;overflow-x:auto;border-top:1px solid var(--border)}
    .nav-link{padding:0 12px}.data-status{margin-left:0}.section-nav{position:static}.main-content{padding:12px}
    .chips-toolbar{position:static;align-items:stretch;flex-wrap:wrap}.search-field{grid-template-columns:1fr;width:100%;gap:4px}.search-field input{min-width:0}
    .exchange-filter{flex:1}.exch-btn{flex:1}.filter-result{margin-left:0;width:100%}.chips-grid{grid-template-columns:minmax(0,1fr)}
  }
  @media(max-width:540px){
    .page-name{display:none}.main-content{padding:10px}.chips-section,.chips-section-half{padding:11px}.tab-btn{min-height:44px}
    .ct td{font-size:.75rem}.ct th{font-size:.6875rem}.table-toggle{display:block}
  }
  @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
  .holder-grid{display:grid;grid-template-columns:1fr;gap:8px}
  @media(min-width:640px){.holder-grid{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}}
  .holder-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:11px 13px}
  .hc-top{display:flex;align-items:baseline;gap:6px}
  .hc-rank{font-family:ui-monospace,monospace;font-size:.62rem;color:var(--subtle);flex-shrink:0}
  .hc-name{font-weight:700;font-size:.88rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .hc-sid{font-family:ui-monospace,monospace;color:var(--subtle);font-size:.64rem}
  .hc-meta{font-size:.64rem;color:var(--subtle);margin-top:1px}
  .hc-price{font-family:ui-monospace,monospace;font-weight:700;font-size:.8rem;flex-shrink:0}
  .hc-price.up{color:var(--up)}.hc-price.down{color:var(--down)}
  .hc-bar-row{display:flex;align-items:center;gap:8px;margin-top:9px}
  .hc-divbar{flex:1;height:7px;background:var(--surface-2);border-radius:3px;position:relative;overflow:hidden}
  .hc-divbar::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--border-strong)}
  .hc-divbar span{position:absolute;top:0;bottom:0;border-radius:2px}
  .hc-divbar span.up{left:50%;background:var(--up)}
  .hc-divbar span.down{right:50%;background:var(--down)}
  .hc-week{font-family:ui-monospace,monospace;font-weight:800;font-size:.66rem;flex-shrink:0;width:46px;
    text-align:center;padding:3px 0;border-radius:8px;border:1px solid}
  .hc-week.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
  .hc-week.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
  .hc-abs{font-family:ui-monospace,monospace;font-size:.64rem;color:var(--subtle);flex-shrink:0;width:38px;text-align:right}
  .hc-badges{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap;font-family:ui-monospace,monospace;font-size:.64rem;color:var(--subtle)}
  .hc-badges b{color:var(--text);font-weight:700}
  .hc-streak-pill{padding:2px 7px;border-radius:8px;font-weight:800;font-size:.62rem;border:1px solid}
  .hc-streak-pill.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
  .hc-streak-pill.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
  .hc-trend{margin-top:8px}
  .hc-trend svg{display:block;width:100%;height:auto}
  .hc-trend text{font-family:ui-monospace,monospace;font-size:4.2px;fill:var(--subtle)}
  .hc-trend .axis-label{text-anchor:end}
  .hc-trend .trend-line{fill:none;stroke:var(--muted);stroke-width:1.4}
  .hc-trend .trend-area{fill:var(--muted);opacity:.08}
  .hc-trend .trend-end{fill:var(--accent)}
  .hc-trend.down .trend-line{stroke:var(--down)}
  .hc-trend.down .trend-area{fill:var(--down)}
  .hc-trend.down .trend-end{fill:var(--down)}
  .hc-trend .trend-grid{stroke:var(--border);stroke-width:1;stroke-dasharray:2,2}
  .hc-trend-empty{font-size:.68rem;color:var(--subtle);padding:6px 0;font-style:italic}
"""

_TAB_JS = """
<script>
function switchTab(id, focusTab=false){
  document.querySelectorAll('.tab-btn').forEach(b=>{
    const selected=b.dataset.tab===id;
    b.classList.toggle('active',selected);
    b.setAttribute('aria-selected',String(selected));
    b.tabIndex=selected?0:-1;
    if(selected&&focusTab)b.focus();
  });
  document.querySelectorAll('.tab-panel').forEach(p=>{
    const selected=p.id===id;
    p.classList.toggle('active',selected);
    p.hidden=!selected;
  });
  history.replaceState(null,'','#'+id);
  if(typeof applyFilters==='function')applyFilters();
}
const _tabs=['tab-signal','tab-dipbuy','tab-stealth','tab-inst','tab-foreign','tab-trust','tab-margin','tab-holder','tab-insider'];
document.querySelector('.tab-groups').addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();
  const current=_tabs.indexOf(document.activeElement.dataset.tab);
  const next=e.key==='Home'?0:e.key==='End'?_tabs.length-1:
    (current+(e.key==='ArrowRight'?1:-1)+_tabs.length)%_tabs.length;
  switchTab(_tabs[next],true);
});
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
        "<div class='chips-toolbar' aria-label='籌碼表格篩選'>"
        "<label class='search-field' for='stock-search'><span>搜尋股票</span>"
        "<input id='stock-search' type='search' inputmode='search' placeholder='代號或名稱' autocomplete='off'></label>"
        "<div class='exchange-filter' role='group' aria-label='交易市場'>"
        "<button type='button' class='exch-btn active' data-exch='' aria-pressed='true'>全部</button>"
        "<button type='button' class='exch-btn' data-exch='TWSE' aria-pressed='false'>上市</button>"
        "<button type='button' class='exch-btn' data-exch='TPEx' aria-pressed='false'>上櫃</button>"
        "</div><span id='filter-result' class='filter-result' aria-live='polite'></span></div>"
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
    <div class="cs-title">外資連買族群</div>
    <table class="ct">{thead}<tbody>{buy_tbody}</tbody></table>
  </div>
  <div class="chips-section-half">
    <div class="cs-title">外資連賣族群</div>
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
    <div class="cs-title">外資大買個股 Top 10{_section_date_suffix(buy_stocks)}</div>
    {_stock_rank_table(buy_stocks, "外資買超")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">外資大賣個股 Top 10{_section_date_suffix(sell_stocks)}</div>
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
            return "<td style='text-align:center;color:var(--subtle)'>─</td>"
        sign = "+" if val > 0 else ""
        color = "#E6432F" if val > 0 else ("#37B25C" if val < 0 else "var(--muted)")
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
        return """
<div class="chips-section">
  <div class="cs-title">越跌越買：5日跌逾 1% 但法人仍連買</div>
  <div class="no-data">今日沒有族群同時符合「5日跌逾 1%」且「外資或投信仍連買」。</div>
</div>"""

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
  <div class="cs-title">越跌越買：5日跌逾 1% 但法人仍連買</div>
  <table class="ct">{dip_thead}<tbody>{dip_tbody}</tbody></table>
</div>"""


def _build_section_stealth(meta_chips: dict, cum_ranks: dict) -> str:
    """外資偷偷買 — 外資連買、但股價盤整（5日在 -1%~+1%）＝市場還沒發現的默默吸貨。
    只看外資（不看投信），跟『越跌越買』(明顯下跌) 用 5日漲跌區間區隔開。"""
    def _pct_cell(val) -> str:
        if val is None:
            return "<td style='text-align:center;color:var(--subtle)'>─</td>"
        sign = "+" if val > 0 else ""
        color = "#E6432F" if val > 0 else ("#37B25C" if val < 0 else "var(--subtle)")
        return f"<td style='text-align:center;color:{color};font-weight:700'>{sign}{val:.1f}%</td>"

    rows = []
    for name, data in meta_chips.items():
        fs = data.get("foreign_streak", 0)
        if fs <= 0:                       # 只要外資連買
            continue
        cum_vals = cum_ranks.get("v", {}).get(name, {})
        cum5 = cum_vals.get("cum5")
        if cum5 is None or cum5 < -1.0 or cum5 > 1.0:   # 股價盤整：5日 -1%~+1%
            continue
        rows.append((name, data, cum_vals, fs))
    # 外資連買越久排越前面；同天數再比今日買超張數
    rows.sort(key=lambda x: (x[3], x[1].get("foreign_net_today", 0)), reverse=True)

    if not rows:
        return ('<div class="chips-section">'
                '<div class="cs-title">外資偷偷買 — 外資連買但股價盤整（5日 -1%~+1%）</div>'
                '<div style="color:var(--subtle);font-size:.8rem;padding:8px 0">'
                '今日沒有族群同時符合「外資連買」且「股價盤整」。</div></div>')

    def _row(name, data, cum_vals, fs) -> str:
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        ts = data.get("trust_streak", 0)
        t_badge = _trust_streak_badge(ts) if ts > 0 else ""
        return (
            f"<tr><td class='ct-name'>{_meta_link(name)}</td>"
            + _pct_cell(cum_vals.get("cum1"))
            + _pct_cell(cum_vals.get("cum3"))
            + _pct_cell(cum_vals.get("cum5"))
            + _pct_cell(cum_vals.get("cum7"))
            + f"<td>{_fmt_net(fn)}</td><td>{_fmt_net(tn)}</td>"
            + f"<td>{_streak_badge(fs)}</td><td>{t_badge}</td></tr>"
        )

    tbody = "".join(_row(*r) for r in rows)
    thead = ("<thead><tr>"
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
  <div class="cs-title">外資偷偷買 — 外資連買但股價盤整（5日 -1%~+1%）</div>
  <table class="ct">{thead}<tbody>{tbody}</tbody></table>
</div>"""


def _build_section4(stock_chips: dict) -> str:
    """Section 4: 融資擴張警示"""
    margin_alerts = stock_chips.get("margin_alerts", [])
    return f"""
<div class="chips-section">
  <div class="cs-title">融資擴張警示（增幅 &gt; 5%）{_section_date_suffix(margin_alerts)}</div>
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
    """相容既有呼叫；百分位算法集中在 screener.institutional。"""
    from screener.institutional import percentile_ranks
    return percentile_ranks(values)


def _composite_sort(candidates: list, streak_key: str) -> list:
    """連買天數跟股價累積漲幅各自轉成百分位排名、加總當綜合分數排序（Composite Score，
    參考量化多因子排名常見做法：percentile rank 加總，而非直接拿其中一個因子當排序）。
    避免像百容（漲幅大但連買天數短）跟長連買但漲幅普通的股票互相排擠掉對方——純用
    漲幅排序，長連買、股價還沒噴出來的個股會被完全擠出榜單；純用連買天數排序，
    絕對股數小的中小型股又會被大型股壓過去（2026-07-09 Cody 討論後採用此法）。"""
    from screener.institutional import rank_continuation_candidates
    return rank_continuation_candidates(candidates, streak_key)


def _build_section6(inst_scan: list) -> tuple[str, str, str]:
    """Section 6: 法人持續買進個股（過濾 ETF/特別股，只留 4 位數純數字代碼）。
    回傳 (強力訊號, 外資持續買進, 投信持續買進) 三塊獨立 html——外資/投信各自要放進
    「外資籌碼」「投信籌碼」獨立 tab，不能再綁成同一個 grid（見 chips.html tab 改版）。"""
    import re as _re
    from screener.institutional import rank_joint_buy_candidates
    def _is_stock(sid: str) -> bool:
        return bool(_re.match(r'^[1-9]\d{3}$', str(sid)))

    # 強力訊號只顯示 App 追蹤的電子科技族群個股：scan_institutional() 讀的是全市場法人
    # 資料（institutional 表），不限於 stock_universe.csv 的 41 個電子科技族群，金融/鋼鐵/
    # 傳產股（從未被收錄進 stock_universe.csv，meta_sector 對它們永遠是空字串）也會混進來，
    # 跟這個 App「電子科技供應鏈掃盤」的追蹤範圍不符（Cody 實測看到兆豐金/東和鋼鐵混在裡面）。
    strong = rank_joint_buy_candidates(
        [x for x in inst_scan if _is_stock(x.get("stock_id", "")) and x.get("meta_sector")],
        limit=30,
    )
    strong_date = max((x.get("date") for x in strong if x.get("date")), default="")
    # 排序改用「連買天數 + 股價累積漲幅」的 Composite Score（見 _composite_sort），不是
    # 單純累積買超股數或單純漲幅：純用絕對股數排名會被大型股/高股本股主宰前段班，把
    # 「外資買超雖然股數不多、但確實推動股價」的中小型股擠出榜單（2026-07-09 實測案例：
    # 百容 2483 外資連買 3 天、10 日內大漲，但用絕對股數排到第 37 名，被擠出前 15）；
    # 純用漲幅排序又會把「連買很久但股價還沒反應」的個股完全埋掉。用 min_price_cum_pct
    # 濾掉外資買超但股價完全沒動的雜訊（可能是被動式資金流入，不是有效訊號）。
    top_foreign = _composite_sort(
        [x for x in inst_scan if x.get("foreign_streak", 0) >= 3 and _is_stock(x.get("stock_id", ""))
         and x.get("meta_sector")
         and (x.get("price_cum_pct") or 0) >= 5],
        "foreign_streak"
    )[:15]
    foreign_date = max((x.get("date") for x in top_foreign if x.get("date")), default="")
    # 投信榜比照外資榜（2026-07-09 Cody 要求一致）：同樣加 price_cum_pct>=5% 篩選、
    # 排序改用 Composite Score。
    top_trust = _composite_sort(
        [x for x in inst_scan if x.get("trust_streak", 0) >= 5 and _is_stock(x.get("stock_id", ""))
         and x.get("meta_sector")
         and (x.get("price_cum_pct") or 0) >= 5],
        "trust_streak"
    )[:15]
    trust_date = max((x.get("date") for x in top_trust if x.get("date")), default="")

    s6a_html = f"""
<div class="chips-section">
  <div class="cs-title">法人同步買超觀察{f' · 資料日 {strong_date}' if strong_date else ''}</div>
  <p class="cs-description">同步連買 &ge;2 日、成交量 &ge;500 張、買超占量 &ge;0.1%、10 日價格不弱於 0%。此為籌碼確認條件，不代表買進建議。</p>
  {_inst_strong_table(strong)}
</div>"""

    s6_foreign_html = f"""
<div class="chips-section">
  <div class="cs-title">外資持續買進 Top 15（連買 &ge;3 日 + 10日漲幅 &ge;5%，綜合排序）{f' · 資料日 {foreign_date}' if foreign_date else ''}</div>
  {_inst_streak_table(top_foreign, 'foreign_streak', 'foreign_net', 'cum_foreign', '外資')}
</div>"""

    s6_trust_html = f"""
<div class="chips-section">
  <div class="cs-title">投信持續買進 Top 15（連買 &ge;5 日 + 10日漲幅 &ge;5%，綜合排序）{f' · 資料日 {trust_date}' if trust_date else ''}</div>
  {_inst_streak_table(top_trust, 'trust_streak', 'trust_net', 'cum_trust', '投信')}
</div>"""
    return s6a_html, s6_foreign_html, s6_trust_html


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
    <div class="cs-title">短線風險：融資增 + 股價跌 {days_label}</div>
    {_margin_divergence_table(bearish, "bearish")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">融資改善：融資減 + 股價漲 {days_label}</div>
    {_margin_divergence_table(bullish, "bullish")}
  </div>
</div>"""


def _build_section8(shareholder_data: list, insider_data: list | None = None) -> tuple[str, str, str]:
    """Section 8: 大戶籌碼（集保 TDCC ≥400張）+ 董監持股。回傳 (大戶籌碼html, 資料日期note, 董監持股html)——
    兩者是不同資料源（TDCC 集保 vs 公開觀測站董監申報），拆成獨立 tab（見 chips.html 改版）。
    董監持股採公開觀測站資料獨立排序，不受 TDCC 名單限制。"""
    insider_data = insider_data or []
    if not shareholder_data:
        empty = "<div class='no-data'>無資料（請執行 python main.py --update-shareholder）</div>"
        s8_html = f"<div class='chips-section'><div class='cs-title'>大戶籌碼</div>{empty}</div>"
        s8_note = ""
        top_increasing, top_decreasing = [], []
    else:
        sh_increasing = [r for r in shareholder_data if (r.get("streak") or 0) > 0]
        sh_decreasing = [r for r in shareholder_data if (r.get("streak") or 0) < 0]
    # 排序 bug 修正：同樣連增/連減週數時，原本比「持倉百分比絕對值」高低，會把外資保管銀行
    # 持股天生就高的股票（例如台積電 87.77%）沖到榜首，即使當週實際變動只有 0.01-0.03%
    # 這種無意義的雜訊。改比「當週實際變動幅度」（|week_chg|）大小，才會優先顯示真正有意義
    # 的籌碼變動，不是絕對持倉位置。
        sh_increasing.sort(key=lambda x: (-(x.get("streak") or 0), -abs(x.get("week_chg") or 0)))
        sh_decreasing.sort(key=lambda x: ((x.get("streak") or 0), -abs(x.get("week_chg") or 0)))
        top_increasing, top_decreasing = sh_increasing[:30], sh_decreasing[:20]

        s8_html = f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">大戶連增倉 Top 30（≥400張，集保）</div>
    {_holder_column_html(top_increasing, direction="inc")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">大戶連減倉 Top 20</div>
    {_holder_column_html(top_decreasing, direction="dec")}
  </div>
</div>"""
        sh_date = shareholder_data[0].get("date", "")
        s8_note = f"<p class='data-note'>集保資料日期：{sh_date}｜共 {len(shareholder_data)} 支股票</p>"

    ranked_insiders = sorted(
        [r for r in insider_data if r.get("company_chg") is not None or r.get("major_holder_chg") is not None],
        key=lambda r: -max(abs(r.get("company_chg") or 0), abs(r.get("major_holder_chg") or 0)),
    )[:50]
    insider_date = max((r.get("report_date") for r in ranked_insiders if r.get("report_date")), default="")
    insider_date_note = f" · 資料日 {insider_date}" if insider_date else ""
    s_insider_html = f"""
<div class="chips-section">
  <div class="cs-title">董監持股變化 Top 50{insider_date_note}</div>
  <p class="cs-description">依公司派或大股東月持股變化絕對值排序，與集保大戶榜獨立計算。</p>
  {_insider_holdings_table(ranked_insiders)}
</div>"""
    return s8_html, s8_note, s_insider_html


def generate(
    trade_date: date,
    meta_chips: dict,
    stock_chips: dict,
    inst_scan: list = None,
    margin_divergence: dict = None,
    cum_data: list = None,
    meta_signals: dict = None,
    shareholder_data: list = None,
    insider_data: list = None,
    output_path: str = "docs/chips.html",
) -> bool:
    """回傳是否實際寫入了 output_path；meta_chips/stock_chips 兩者皆空時不寫檔、回傳 False，
    讓呼叫端可以分辨「真的產生成功」跟「靜默跳過」，不要無條件記成功。"""
    if not meta_chips and not stock_chips:
        return False
    inst_scan = inst_scan or []
    shareholder_data = shareholder_data or []
    insider_data = insider_data or []
    cum_ranks = _make_cum_ranks(cum_data or [])
    margin_divergence = margin_divergence or {}

    exch_js_var, exch_filter_btns = _build_exchange_ui()

    date_str = trade_date.strftime("%Y-%m-%d")
    chips_date = stock_chips.get("chips_date", date_str)
    try:
        chips_weekday = date.fromisoformat(str(chips_date)[:10]).weekday()
    except (TypeError, ValueError):
        chips_weekday = trade_date.weekday()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][chips_weekday]

    s1_html = _build_section1(meta_chips, cum_ranks)
    s2_html = _build_section2(stock_chips)
    s3_html = _build_section3(meta_chips, cum_ranks)
    s35_html = _build_section35(meta_chips, cum_ranks)
    s_stealth_html = _build_section_stealth(meta_chips, cum_ranks)
    s4_html = _build_section4(stock_chips)
    s5_html = _build_section5(meta_chips)
    s6a_html, s6_foreign_html, s6_trust_html = _build_section6(inst_scan)
    s7_html = _build_section7(margin_divergence)
    s8_html, s8_note, s_insider_html = _build_section8(shareholder_data, insider_data)

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
  <a class="skip-link" href="#main-content">跳到籌碼內容</a>
  <div class="app-shell">
  <header class="topbar">
    <div class="brand-lockup">
      <h1>台股電子半導體族群追蹤</h1>
      <span class="page-name">籌碼分析</span>
    </div>
    <nav class="nav-links" aria-label="主要功能">
      <a class="nav-link" href="index.html">族群績效</a>
      <a class="nav-link active" href="chips.html" aria-current="page">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
      <a class="nav-link" href="momentum.html">逆轟策略</a>
    </nav>
    <div class="data-status" aria-label="籌碼資料日期">
      <span>資料日期</span>
      <strong>{chips_date}（週{weekday}）</strong>
    </div>
  </header>
  <div class="workspace">
    <aside class="section-nav" aria-label="籌碼分析視角">
      <div class="section-nav-inner">
        <div class="section-nav-label">分析視角</div>
        <div class="tab-groups" role="tablist" aria-label="籌碼分析分類">
          <div class="tab-group">
            <span class="tab-group-label">法人動向</span>
            <div class="tab-bar">
              <button id="tab-btn-signal" type="button" role="tab" aria-controls="tab-signal" aria-selected="false" class="tab-btn" data-tab="tab-signal" onclick="switchTab('tab-signal')">法人同步觀察</button>
              <button id="tab-btn-foreign" type="button" role="tab" aria-controls="tab-foreign" aria-selected="false" class="tab-btn" data-tab="tab-foreign" onclick="switchTab('tab-foreign')">外資籌碼</button>
              <button id="tab-btn-trust" type="button" role="tab" aria-controls="tab-trust" aria-selected="false" class="tab-btn" data-tab="tab-trust" onclick="switchTab('tab-trust')">投信籌碼</button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">特殊型態</span>
            <div class="tab-bar">
              <button id="tab-btn-dipbuy" type="button" role="tab" aria-controls="tab-dipbuy" aria-selected="false" class="tab-btn" data-tab="tab-dipbuy" onclick="switchTab('tab-dipbuy')">越跌越買</button>
              <button id="tab-btn-stealth" type="button" role="tab" aria-controls="tab-stealth" aria-selected="false" class="tab-btn" data-tab="tab-stealth" onclick="switchTab('tab-stealth')">外資偷偷買</button>
              <button id="tab-btn-margin" type="button" role="tab" aria-controls="tab-margin" aria-selected="false" class="tab-btn" data-tab="tab-margin" onclick="switchTab('tab-margin')">融資警示</button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">持股結構</span>
            <div class="tab-bar">
              <button id="tab-btn-inst" type="button" role="tab" aria-controls="tab-inst" aria-selected="false" class="tab-btn" data-tab="tab-inst" onclick="switchTab('tab-inst')">法人買賣</button>
              <button id="tab-btn-holder" type="button" role="tab" aria-controls="tab-holder" aria-selected="false" class="tab-btn" data-tab="tab-holder" onclick="switchTab('tab-holder')">大戶籌碼</button>
              <button id="tab-btn-insider" type="button" role="tab" aria-controls="tab-insider" aria-selected="false" class="tab-btn" data-tab="tab-insider" onclick="switchTab('tab-insider')">董監持股</button>
            </div>
          </div>
        </div>
        <p class="section-nav-note">可依股票代號或名稱搜尋。所有表格支援欄位排序，資料日期以各區塊標示為準。</p>
      </div>
    </aside>
    <main id="main-content" class="main-content" tabindex="-1">
      {exch_filter_btns}

      <div class="tab-panel" id="tab-signal" role="tabpanel" aria-labelledby="tab-btn-signal">
        {s6a_html}
      </div>

      <div class="tab-panel" id="tab-dipbuy" role="tabpanel" aria-labelledby="tab-btn-dipbuy">
        {s35_html}
      </div>

      <div class="tab-panel" id="tab-stealth" role="tabpanel" aria-labelledby="tab-btn-stealth">
        {s_stealth_html}
      </div>

      <div class="tab-panel" id="tab-inst" role="tabpanel" aria-labelledby="tab-btn-inst">
        {s1_html}
      </div>

      <div class="tab-panel" id="tab-foreign" role="tabpanel" aria-labelledby="tab-btn-foreign">
        {s6_foreign_html}
        {s2_html}
        {s5_html}
      </div>

      <div class="tab-panel" id="tab-trust" role="tabpanel" aria-labelledby="tab-btn-trust">
        {s6_trust_html}
        {s3_html}
      </div>

      <div class="tab-panel" id="tab-margin" role="tabpanel" aria-labelledby="tab-btn-margin">
        {s7_html}
        {s4_html}
      </div>

      <div class="tab-panel" id="tab-holder" role="tabpanel" aria-labelledby="tab-btn-holder">
        {s8_note}
        {s8_html}
      </div>

      <div class="tab-panel" id="tab-insider" role="tabpanel" aria-labelledby="tab-btn-insider">
        {s_insider_html}
      </div>

      <div class="footer">資料來源：TWSE、TPEx 三大法人與融資融券；TDCC 集保持股分散表；公開資訊觀測站內部人持股。資料日期依各區塊標示。</div>
    </main>
  </div>
  </div>
  {_TAB_JS}
  <script>
  {exch_js_var}
  // 在個股代號旁加上市/上櫃 badge
  document.querySelectorAll('span.sid').forEach(function(span){{
    const exch=EXCH[span.textContent.trim()];
    if(exch==='TWSE') span.insertAdjacentHTML('afterend','<span class="market-badge twse">上市</span>');
    else if(exch==='TPEx') span.insertAdjacentHTML('afterend','<span class="market-badge tpex">上櫃</span>');
  }});
  let activeExchange='';
  const expandedTables=new Set();
  const searchInput=document.getElementById('stock-search');
  const mobileMedia=window.matchMedia('(max-width:540px)');
  let searchTimer=0;

  function sortValue(text){{
    const clean=text.trim().replaceAll(',','');
    const match=clean.match(/[+-]?[\\d.]+/);
    if(!match)return clean.toLocaleLowerCase('zh-TW');
    let value=Number(match[0]);
    if(clean.includes('萬張'))value*=10000;
    return value;
  }}

  document.querySelectorAll('table.ct').forEach((table,index)=>{{
    const key='chips-table-'+index;
    table.dataset.tableKey=key;
    const shell=document.createElement('div');
    shell.className='table-shell';
    table.parentNode.insertBefore(shell,table);
    shell.appendChild(table);
    const toggle=document.createElement('button');
    toggle.type='button';toggle.className='table-toggle';toggle.dataset.tableKey=key;
    toggle.addEventListener('click',()=>{{
      if(expandedTables.has(key))expandedTables.delete(key);else expandedTables.add(key);
      applyFilters();
    }});
    shell.insertAdjacentElement('afterend',toggle);

    table.querySelectorAll('thead th').forEach((th,column)=>{{
      const label=th.textContent.trim();
      if(!label)return;
      th.setAttribute('aria-sort','none');
      th.textContent='';
      const button=document.createElement('button');
      button.type='button';button.className='sort-button';button.textContent=label;
      button.setAttribute('aria-label',label+'，點擊排序');
      button.addEventListener('click',()=>{{
        const ascending=th.getAttribute('aria-sort')!=='ascending';
        table.querySelectorAll('th').forEach(h=>h.setAttribute('aria-sort','none'));
        th.setAttribute('aria-sort',ascending?'ascending':'descending');
        const body=table.tBodies[0];
        const rows=[...body.rows];
        rows.sort((a,b)=>{{
          const av=sortValue(a.cells[column]?.textContent||'');
          const bv=sortValue(b.cells[column]?.textContent||'');
          const compared=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'zh-TW');
          return ascending?compared:-compared;
        }}).forEach(row=>body.appendChild(row));
        applyFilters();
      }});
      th.appendChild(button);
    }});
  }});

  function applyFilters(){{
    const query=searchInput.value.trim().toLocaleLowerCase('zh-TW');
    const isMobile=mobileMedia.matches;
    document.querySelectorAll('table.ct').forEach(table=>{{
      const key=table.dataset.tableKey;
      let matched=0;
      table.querySelectorAll('tbody tr').forEach(tr=>{{
        const sid=tr.querySelector('.sid');
        const ex=sid?(EXCH[sid.textContent.trim()]||''):'';
        const searchable=tr.textContent.toLocaleLowerCase('zh-TW');
        const matches=(!activeExchange||!sid||ex===activeExchange)&&(!query||searchable.includes(query));
        const withinPreview=!isMobile||expandedTables.has(key)||matched<5;
        tr.hidden=!(matches&&withinPreview);
        if(matches)matched+=1;
      }});
      const toggle=document.querySelector('.table-toggle[data-table-key="'+key+'"]');
      if(toggle){{
        toggle.hidden=!isMobile||matched<=5;
        toggle.textContent=expandedTables.has(key)?'收合，顯示前 5 筆':'查看全部 '+matched+' 筆';
        toggle.setAttribute('aria-expanded',String(expandedTables.has(key)));
      }}
    }});
    const panel=document.querySelector('.tab-panel.active');
    const matchedKeys=new Set();
    if(panel)panel.querySelectorAll('table.ct tbody tr').forEach(r=>{{
      const sid=r.querySelector('.sid');const sidText=sid?sid.textContent.trim():'';
      const ex=sidText?(EXCH[sidText]||''):'';
      const matches=(!activeExchange||!sid||ex===activeExchange)&&(!query||r.textContent.toLocaleLowerCase('zh-TW').includes(query));
      if(matches){{
        const first=(r.cells[0]?.textContent||r.textContent).trim();
        matchedKeys.add(sidText?'stock:'+sidText:'row:'+first);
      }}
    }});
    document.getElementById('filter-result').textContent='本頁 '+matchedKeys.size+' 筆資料';
  }}

  document.querySelectorAll('.exch-btn').forEach(btn=>btn.addEventListener('click',()=>{{
    activeExchange=btn.dataset.exch;
    document.querySelectorAll('.exch-btn').forEach(b=>{{
      const active=b===btn;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));
    }});
    applyFilters();
  }}));
  searchInput.addEventListener('input',()=>{{
    window.clearTimeout(searchTimer);
    searchTimer=window.setTimeout(applyFilters,120);
  }});
  mobileMedia.addEventListener('change',applyFilters);
  applyFilters();
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return True
