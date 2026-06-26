"""
生成 docs/chips.html — 獨立籌碼分頁
資料來源：meta_chips (calc_meta_chips_signals) + stock_chips (get_stock_chips_ranking)
"""
from datetime import date
from pathlib import Path


def _net_color(n: int) -> str:
    return "#f87171" if n > 0 else ("#4ade80" if n < 0 else "#64748b")


def _fmt_net(n: int) -> str:
    if n == 0:
        return "<span style='color:#475569'>─</span>"
    k = n // 1000
    sign = "+" if n > 0 else ""
    color = _net_color(n)
    return f"<span style='color:{color};font-weight:700'>{sign}{k:,}K</span>"


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
        html += f"<tr><td class='ct-name'>{name}</td><td>{_fmt_net(f_net)}</td><td>{_fmt_net(t_net)}</td><td>{badge}</td></tr>"
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
        html += f"<tr><td class='ct-name'>{name}</td><td>{_fmt_net(t_net)}</td><td>{_fmt_net(f_net)}</td><td>{badge}</td></tr>"
    html += "</tbody></table>"
    return html


def _stock_rank_table(stocks: list, header: str, net_key: str = "foreign_net") -> str:
    if not stocks:
        return "<div class='no-data'>無資料</div>"
    html = f"<table class='ct'><thead><tr><th>#</th><th>股票</th><th>族群</th><th>{header}</th><th>投信</th></tr></thead><tbody>"
    for i, s in enumerate(stocks, 1):
        net = s.get(net_key, 0)
        trust = s.get("trust_net", 0)
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{s['stock_id']}</span> {s['stock_name']}</td>"
            f"<td class='ct-meta'>{s['meta_sector']}</td>"
            f"<td>{_fmt_net(net)}</td>"
            f"<td>{_fmt_net(trust)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _inst_strong_table(rows: list) -> str:
    if not rows:
        return "<div class='no-data'>無符合條件個股</div>"
    html = (
        "<table class='ct'><thead><tr>"
        "<th>#</th><th>股票</th><th>外資</th><th>投信</th>"
        "<th>外資今日</th><th>投信今日</th><th>合計</th><th>漲跌</th>"
        "</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        chg = s.get("change_pct")
        chg_html = (
            f"<span style='color:#f87171;font-weight:700'>+{chg}%</span>" if chg and chg > 0
            else f"<span style='color:#4ade80;font-weight:700'>{chg}%</span>" if chg and chg < 0
            else "<span style='color:#475569'>─</span>"
        )
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{s['stock_id']}</span> {s.get('stock_name','')}</td>"
            f"<td>{_streak_badge(s['foreign_streak'], '外資')}</td>"
            f"<td>{_trust_streak_badge(s['trust_streak'])}</td>"
            f"<td>{_fmt_net(s.get('foreign_net') or 0)}</td>"
            f"<td>{_fmt_net(s.get('trust_net') or 0)}</td>"
            f"<td>{_fmt_net(s.get('total_net') or 0)}</td>"
            f"<td>{chg_html}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _inst_streak_table(rows: list, streak_key: str, net_key: str, cum_key: str, label: str) -> str:
    if not rows:
        return "<div class='no-data'>無資料</div>"
    html = (
        f"<table class='ct'><thead><tr>"
        f"<th>#</th><th>股票</th><th>連買</th>"
        f"<th>{label}今日</th><th>{label}累計</th><th>漲跌</th>"
        f"</tr></thead><tbody>"
    )
    for i, s in enumerate(rows, 1):
        streak = s.get(streak_key, 0)
        net = s.get(net_key) or 0
        cum = s.get(cum_key) or 0
        chg = s.get("change_pct")
        chg_html = (
            f"<span style='color:#f87171;font-weight:700'>+{chg}%</span>" if chg and chg > 0
            else f"<span style='color:#4ade80;font-weight:700'>{chg}%</span>" if chg and chg < 0
            else "<span style='color:#475569'>─</span>"
        )
        badge = _streak_badge(streak, '外資') if streak_key == 'foreign_streak' else _trust_streak_badge(streak)
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{s['stock_id']}</span> {s.get('stock_name','')}</td>"
            f"<td>{badge}</td>"
            f"<td>{_fmt_net(net)}</td>"
            f"<td>{_fmt_net(cum)}</td>"
            f"<td>{chg_html}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


def _margin_alert_table(alerts: list) -> str:
    if not alerts:
        return "<div class='no-data'>無融資擴張警示</div>"
    html = "<table class='ct'><thead><tr><th>#</th><th>股票</th><th>族群</th><th>融資餘額</th><th>增加量</th><th>增幅</th></tr></thead><tbody>"
    for i, s in enumerate(alerts, 1):
        pct = s["alert_pct"]
        color = "#fb923c" if pct >= 10 else "#fbbf24"
        html += (
            f"<tr>"
            f"<td class='ct-rank'>{i}</td>"
            f"<td><span class='sid'>{s['stock_id']}</span> {s['stock_name']}</td>"
            f"<td class='ct-meta'>{s['meta_sector']}</td>"
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
        thead = "<thead><tr><th>#</th><th>股票</th><th>族群</th><th>融資增幅</th><th>股價跌幅</th><th>天數</th></tr></thead>"
    else:
        thead = "<thead><tr><th>#</th><th>股票</th><th>族群</th><th>融資減幅</th><th>股價漲幅</th><th>天數</th></tr></thead>"
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
            f"<td><span class='sid'>{s['stock_id']}</span> {s['stock_name']}</td>"
            f"<td class='ct-meta'>{s['meta_sector']}</td>"
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

    html = "<table class='ct'><thead><tr><th>族群</th><th>外資買超比例</th><th>買超/總股數</th><th>外資今日</th></tr></thead><tbody>"
    for name, ratio, data in rows:
        buy_count = data.get("foreign_buy_count", 0)
        total = data.get("total_stocks", 1)
        f_net = data.get("foreign_net_today", 0)
        bar = _ratio_bar(ratio)
        html += (
            f"<tr>"
            f"<td class='ct-name'>{name}</td>"
            f"<td style='min-width:140px'>{bar}</td>"
            f"<td style='color:#64748b;font-size:.75rem'>{buy_count}/{total}</td>"
            f"<td>{_fmt_net(f_net)}</td>"
            f"</tr>"
        )
    html += "</tbody></table>"
    return html


_CSS = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"Segoe UI",sans-serif;background:#0b0f18;color:#e2e8f0;padding:12px 20px}
  .header{margin-bottom:24px}
  h1{font-size:1.1rem;font-weight:600;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}
  .mkt-bar{display:flex;align-items:center;gap:16px;margin-top:8px;padding:12px 16px;background:#141c2e;border-radius:10px;flex-wrap:wrap}
  .mkt-date{font-size:1rem;font-weight:600;color:#f1f5f9}
  .nav-links{display:flex;gap:8px;margin-top:10px}
  .nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid #1e293b;color:#64748b;text-decoration:none;transition:all .15s}
  .nav-link:hover{border-color:#475569;color:#94a3b8}
  .nav-link.active{border-color:#475569;color:#e2e8f0;background:#141c2e}
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
  .ct-meta{color:#475569;font-size:.72rem}
  .ct-rank{color:#334155;font-size:.72rem;font-weight:700;text-align:center;width:24px}
  .sid{color:#475569;font-size:.72rem;font-weight:600}
  .no-data{color:#334155;font-size:.8rem;padding:12px 0;text-align:center}
  .footer{margin-top:28px;font-size:.7rem;color:#1e293b;text-align:center;padding-bottom:20px}
  @media(max-width:540px){body{padding:12px}.chips-grid{grid-template-columns:1fr}}
"""


def generate(
    trade_date: date,
    meta_chips: dict,
    stock_chips: dict,
    inst_scan: list = None,
    margin_divergence: dict = None,
    output_path: str = "docs/chips.html",
) -> None:
    if not meta_chips and not stock_chips:
        return
    inst_scan = inst_scan or []
    margin_divergence = margin_divergence or {}

    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]
    chips_date = stock_chips.get("chips_date", date_str)

    # Section 1: META 外資連買/連賣排行
    buy_streak_rows = [(n, d) for n, d in meta_chips.items() if d.get("foreign_streak", 0) > 0]
    buy_streak_rows.sort(key=lambda x: x[1]["foreign_streak"], reverse=True)
    sell_streak_rows = [(n, d) for n, d in meta_chips.items() if d.get("foreign_streak", 0) < 0]
    sell_streak_rows.sort(key=lambda x: x[1]["foreign_streak"])

    def _streak_row(name: str, data: dict) -> str:
        fs = data.get("foreign_streak", 0)
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        badge = _streak_badge(fs)
        return f"<tr><td class='ct-name'>{name}</td><td>{_fmt_net(fn)}</td><td>{_fmt_net(tn)}</td><td>{badge}</td></tr>"

    buy_tbody = "".join(_streak_row(n, d) for n, d in buy_streak_rows) or "<tr><td colspan='4' class='no-data'>無連買族群</td></tr>"
    sell_tbody = "".join(_streak_row(n, d) for n, d in sell_streak_rows) or "<tr><td colspan='4' class='no-data'>無連賣族群</td></tr>"

    thead = "<thead><tr><th>族群</th><th>外資今日</th><th>投信今日</th><th>狀態</th></tr></thead>"
    s1_html = f"""
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

    # Section 2: 外資大買/大賣個股 Top10
    buy_stocks = stock_chips.get("foreign_top_buy", [])
    sell_stocks = stock_chips.get("foreign_top_sell", [])
    s2_html = f"""
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

    # Section 3: META 投信加碼彙總
    trust_rows = [(n, d.get("trust_streak", 0), d) for n, d in meta_chips.items() if d.get("trust_streak", 0) != 0]
    trust_rows.sort(key=lambda x: x[1], reverse=True)

    def _trust_row(name: str, streak: int, data: dict) -> str:
        fn = data.get("foreign_net_today", 0)
        tn = data.get("trust_net_today", 0)
        badge = _trust_streak_badge(streak)
        return f"<tr><td class='ct-name'>{name}</td><td>{_fmt_net(tn)}</td><td>{_fmt_net(fn)}</td><td>{badge}</td></tr>"

    trust_tbody = "".join(_trust_row(n, s, d) for n, s, d in trust_rows) or "<tr><td colspan='4' class='no-data'>無資料</td></tr>"
    s3_html = f"""
<div class="chips-section">
  <div class="cs-title">投信加碼 META 彙總</div>
  <table class="ct"><thead><tr><th>族群</th><th>投信今日</th><th>外資今日</th><th>狀態</th></tr></thead>
  <tbody>{trust_tbody}</tbody></table>
</div>"""

    # Section 4: 融資擴張警示
    margin_alerts = stock_chips.get("margin_alerts", [])
    s4_html = f"""
<div class="chips-section">
  <div class="cs-title">融資擴張警示（增幅 &gt; 5%）</div>
  {_margin_alert_table(margin_alerts)}
</div>"""

    # Section 5: META 法人籌碼集中度
    s5_html = f"""
<div class="chips-section">
  <div class="cs-title">META 外資籌碼集中度（買超股數 / 總股數）</div>
  {_concentration_table(meta_chips)}
</div>"""

    # Section 6: 法人持續買進個股
    lookback_days = 40
    strong = sorted(
        [x for x in inst_scan if x.get("both_streak", 0) >= 2],
        key=lambda x: -x["both_streak"]
    )
    top_foreign = sorted(
        [x for x in inst_scan if x.get("foreign_streak", 0) >= 3],
        key=lambda x: -(x.get("cum_foreign") or 0)
    )[:15]
    top_trust = sorted(
        [x for x in inst_scan if x.get("trust_streak", 0) >= 5],
        key=lambda x: -(x.get("trust_net") or 0)
    )[:15]

    s6_html = f"""
<div class="chips-section">
  <div class="cs-title">🔥 強力訊號 — 外資+投信同步連買 &ge;2 日</div>
  {_inst_strong_table(strong)}
</div>
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">外資持續買進 Top 15（連買 &ge;3 日，排累計）</div>
    {_inst_streak_table(top_foreign, 'foreign_streak', 'foreign_net', 'cum_foreign', '外資')}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">投信持續買進 Top 15（連買 &ge;5 日，排今日金額）</div>
    {_inst_streak_table(top_trust, 'trust_streak', 'trust_net', 'cum_trust', '投信')}
  </div>
</div>"""

    # Section 7: 融資背離警示
    days_used = margin_divergence.get("days_used", 0)
    bearish = margin_divergence.get("bearish", [])
    bullish = margin_divergence.get("bullish", [])
    if days_used >= 2:
        days_label = f"（近 {days_used} 個交易日）"
        s7_html = f"""
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
    else:
        s7_html = """
<div class="chips-section">
  <div class="cs-title">融資背離警示</div>
  <div class="no-data">融資資料不足（需至少 2 個交易日），請先執行 --backfill-marg</div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
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
    </div>
  </div>

  {s6_html}
  {s7_html}
  {s1_html}
  {s2_html}
  {s3_html}
  {s4_html}
  {s5_html}

  <div class="footer">資料來源：TWSE 三大法人 ｜ 台灣：漲紅跌綠 ｜ 外資正值=買超</div>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
