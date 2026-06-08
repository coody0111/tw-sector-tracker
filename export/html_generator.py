import pandas as pd
from pathlib import Path
from datetime import date
from config import classify_sector, SECTOR_GROUPS


def _pct_cell(pct: float, size: str = "") -> str:
    sign = "+" if pct >= 0 else ""
    cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    return f'<span class="pct {cls} {size}">{arrow} {sign}{pct:.2f}%</span>'


def _bar(up: int, down: int, flat: int) -> str:
    total = up + down + flat or 1
    w_up = int(up / total * 60)
    w_dn = int(down / total * 60)
    w_fl = max(0, 60 - w_up - w_dn)
    return (
        f'<span class="bar-up" style="width:{w_up}px"></span>'
        f'<span class="bar-dn" style="width:{w_dn}px"></span>'
        f'<span class="bar-fl" style="width:{w_fl}px"></span>'
    )


def _stock_detail_rows(sector_name: str, sectors_df: pd.DataFrame, prices_df: pd.DataFrame) -> str:
    """個股展開列 HTML"""
    if sectors_df is None or prices_df is None:
        return ""

    member_ids = sectors_df[sectors_df["sector_name"] == sector_name]["stock_id"].astype(str).tolist()
    if not member_ids:
        return ""

    prices_map = prices_df.set_index("stock_id") if not prices_df.empty else pd.DataFrame()
    rows = []
    for sid in sorted(member_ids):
        sid_str = str(sid)
        if sid_str in prices_map.index:
            p = prices_map.loc[sid_str]
            name = str(p.get("stock_name", sid_str)) if p.get("stock_name", sid_str) != sid_str else sid_str
            close = float(p["close"])
            change = float(p["change"])
            pct = float(p["change_pct"])
            vol = int(p["volume"])
            rows.append(
                f'<tr class="stock-row">'
                f'<td class="stock-id">{sid_str}</td>'
                f'<td class="stock-name">{name}</td>'
                f'<td class="stock-close">{close:.2f}</td>'
                f'<td>{_pct_cell(pct, "sm")}</td>'
                f'<td class="stock-vol">{vol:,}</td>'
                f'</tr>'
            )
        else:
            rows.append(
                f'<tr class="stock-row no-price">'
                f'<td class="stock-id">{sid_str}</td>'
                f'<td class="stock-name" colspan="4">（無行情資料）</td>'
                f'</tr>'
            )

    inner = "".join(rows)
    return (
        f'<tr class="detail-row" style="display:none">'
        f'<td colspan="4">'
        f'<table class="stock-table">'
        f'<thead><tr><th>代號</th><th>名稱</th><th>收盤</th><th>漲跌幅</th><th>成交量(張)</th></tr></thead>'
        f'<tbody>{inner}</tbody>'
        f'</table>'
        f'</td></tr>'
    )


def _sector_row(row, sectors_df=None, prices_df=None) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_detail_rows(row["sector_name"], sectors_df, prices_df)
    clickable = ' class="clickable-sector" onclick="toggleDetail(this)"' if detail else ""
    arrow_icon = ' <span class="toggle-icon">▶</span>' if detail else ""
    return (
        f'<tr{clickable}>'
        f'<td class="name">{row["sector_name"]}{arrow_icon}</td>'
        f'<td>{_pct_cell(pct)}</td>'
        f'<td><span class="cnt up-txt">▲{up}</span> <span class="cnt dn-txt">▼{down}</span> <span class="cnt fl-txt">─{flat}</span></td>'
        f'<td class="bar-cell">{_bar(up, down, flat)}</td>'
        f'</tr>'
        + detail
    )


def generate(
    trade_date: date,
    perf_df: pd.DataFrame,
    sectors_df: pd.DataFrame = None,
    prices_df: pd.DataFrame = None,
    output_path: str = "docs/index.html",
) -> None:
    if perf_df.empty:
        return

    # 確保 stock_id 都是字串
    if sectors_df is not None and not sectors_df.empty:
        sectors_df = sectors_df.copy()
        sectors_df["stock_id"] = sectors_df["stock_id"].astype(str)
    if prices_df is not None and not prices_df.empty:
        prices_df = prices_df.copy()
        prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    df = perf_df.sort_values("avg_change_pct", ascending=False).reset_index(drop=True)
    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    # ── C 部分：Top10 漲 / 跌 ──
    def top_rows(subset):
        return "".join(_sector_row(r, sectors_df, prices_df) for _, r in subset.iterrows())

    top_html = top_rows(df.head(10))
    bot_html = top_rows(df.tail(10).iloc[::-1])

    # ── B 部分：分組可收合 ──
    df["group"] = df["sector_name"].apply(classify_sector)
    group_order = [g for g, _ in SECTOR_GROUPS]

    groups_html = ""
    for group_name in group_order:
        subset = df[df["group"] == group_name].copy()
        if subset.empty:
            continue

        count = len(subset)
        avg = subset["avg_change_pct"].mean()
        g_cls = "up" if avg > 0 else ("down" if avg < 0 else "flat")
        sign = "+" if avg >= 0 else ""

        preview_rows = "".join(_sector_row(r, sectors_df, prices_df) for _, r in subset.head(3).iterrows())
        rest = subset.iloc[3:]
        rest_rows = "".join(_sector_row(r, sectors_df, prices_df) for _, r in rest.iterrows()) if not rest.empty else ""

        expand_btn = (
            f'<button class="expand-btn" onclick="toggleGroup(this)">展開全部 ({count})</button>'
            if not rest.empty else
            f'<span class="total-badge">{count} 族群</span>'
        )

        groups_html += f"""
  <details class="group-block">
    <summary class="group-header">
      <span class="g-name">{group_name}</span>
      <span class="g-avg pct {g_cls}">{sign}{avg:.2f}%</span>
      <span class="g-count">{count} 族群</span>
    </summary>
    <table class="sector-table">
      <thead><tr><th>族群</th><th>漲跌幅</th><th>漲跌平</th><th>分布</th></tr></thead>
      <tbody class="preview-rows">{preview_rows}</tbody>
      <tbody class="rest-rows" style="display:none">{rest_rows}</tbody>
    </table>
    <div class="group-footer">{expand_btn}</div>
  </details>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>台股電子族群追蹤 {date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,"Segoe UI",sans-serif;background:#0f1117;color:#e2e8f0;padding:20px;max-width:960px;margin:0 auto}}
    h1{{font-size:1.3rem;font-weight:600;color:#f8fafc;margin-bottom:4px}}
    .date{{color:#64748b;font-size:.85rem;margin-bottom:24px}}
    .top-section{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:32px}}
    @media(max-width:600px){{.top-section{{grid-template-columns:1fr}}}}
    .top-card h2{{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #1e293b}}
    .top-card h2.up-title{{color:#f87171}} .top-card h2.down-title{{color:#4ade80}}
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;padding:6px 10px;font-size:.72rem;color:#64748b;text-transform:uppercase;border-bottom:1px solid #1e293b}}
    td{{padding:8px 10px;border-bottom:1px solid #0f1117;font-size:.85rem}}
    tr:hover > td{{background:#1e293b}}
    .name{{font-weight:500;color:#f1f5f9;max-width:180px}}
    .pct{{font-weight:700;font-size:.9rem;white-space:nowrap}}
    .pct.sm{{font-size:.82rem;font-weight:600}}
    .pct.up{{color:#f87171}} .pct.down{{color:#4ade80}} .pct.flat{{color:#94a3b8}}
    .cnt{{font-size:.78rem}} .up-txt{{color:#f87171}} .dn-txt{{color:#4ade80}} .fl-txt{{color:#64748b}}
    .bar-cell{{width:70px}}
    .bar-up,.bar-dn,.bar-fl{{display:inline-block;height:6px;vertical-align:middle}}
    .bar-up{{background:#f87171;border-radius:2px 0 0 2px}}
    .bar-dn{{background:#4ade80}}
    .bar-fl{{background:#1e293b;border-radius:0 2px 2px 0}}
    /* 可點擊族群列 */
    .clickable-sector{{cursor:pointer}}
    .clickable-sector:hover > td{{background:#1a2235 !important}}
    .toggle-icon{{font-size:.65rem;color:#64748b;margin-left:4px;transition:transform .2s}}
    .clickable-sector.open .toggle-icon{{display:inline-block;transform:rotate(90deg)}}
    /* 個股展開列 */
    .detail-row td{{padding:0;background:#0a0f1a}}
    .stock-table{{width:100%;border-collapse:collapse;border-top:1px solid #1e293b}}
    .stock-table th{{padding:5px 12px;font-size:.7rem;background:#0a0f1a;color:#475569}}
    .stock-table td{{padding:6px 12px;font-size:.82rem;border-bottom:1px solid #0f1117;background:#0a0f1a}}
    .stock-table tr:last-child td{{border-bottom:none}}
    .stock-id{{color:#64748b;font-size:.78rem;width:50px}}
    .stock-name{{color:#cbd5e1}}
    .stock-close{{color:#e2e8f0;text-align:right;width:70px}}
    .stock-vol{{color:#64748b;text-align:right;font-size:.78rem}}
    .no-price td{{color:#334155}}
    /* 分組 */
    .section-title{{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:12px;margin-top:8px}}
    .group-block{{border:1px solid #1e293b;border-radius:8px;margin-bottom:8px;overflow:hidden}}
    .group-header{{display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;list-style:none;background:#141820}}
    .group-header:hover{{background:#1e293b}}
    .group-header::-webkit-details-marker{{display:none}}
    details[open] .group-header{{border-bottom:1px solid #1e293b}}
    .g-name{{font-weight:600;color:#f1f5f9;flex:1;font-size:.9rem}}
    .g-avg{{font-weight:700;font-size:.95rem}}
    .g-count{{font-size:.75rem;color:#64748b}}
    .sector-table td,.sector-table th{{padding:7px 14px}}
    .group-footer{{padding:8px 14px;text-align:right}}
    .expand-btn{{background:none;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:.78rem}}
    .expand-btn:hover{{border-color:#64748b;color:#e2e8f0}}
    .total-badge{{font-size:.75rem;color:#475569}}
    .footer{{margin-top:24px;font-size:.72rem;color:#334155;text-align:center}}
  </style>
</head>
<body>
  <h1>台股電子半導體族群追蹤</h1>
  <div class="date">📅 {date_str}（週{weekday}）｜MoneyDJ 族群 × TWSE/TPEx 行情</div>

  <div class="top-section">
    <div class="top-card">
      <h2 class="up-title">▲ 今日漲幅 Top 10</h2>
      <table><thead><tr><th>族群</th><th>漲跌幅</th><th>漲跌平</th></tr></thead>
      <tbody>{top_html}</tbody></table>
    </div>
    <div class="top-card">
      <h2 class="down-title">▼ 今日跌幅 Top 10</h2>
      <table><thead><tr><th>族群</th><th>漲跌幅</th><th>漲跌平</th></tr></thead>
      <tbody>{bot_html}</tbody></table>
    </div>
  </div>

  <div class="section-title">所有族群（依分類）</div>
  {groups_html}

  <div class="footer">點擊族群名稱可展開個股 ｜ 台灣股市漲紅跌綠</div>

  <script>
    function toggleDetail(row) {{
      const detail = row.nextElementSibling;
      if (!detail || !detail.classList.contains('detail-row')) return;
      const open = detail.style.display !== 'none';
      detail.style.display = open ? 'none' : '';
      row.classList.toggle('open', !open);
    }}
    function toggleGroup(btn) {{
      const rest = btn.closest('.group-block').querySelector('.rest-rows');
      const open = rest.style.display !== 'none';
      rest.style.display = open ? 'none' : '';
      btn.textContent = open ? '展開全部' : '收合';
    }}
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
