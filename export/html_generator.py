import pandas as pd
from pathlib import Path
from datetime import date
from config import classify_sector, SECTOR_GROUPS


def _pct_color(pct: float) -> str:
    """漲跌幅強弱對應不同深淺顏色（台灣：漲紅跌綠）"""
    abs_pct = abs(pct)
    if pct > 0:
        if abs_pct >= 7:   return "#ff2d2d"
        if abs_pct >= 5:   return "#f54040"
        if abs_pct >= 3:   return "#e85555"
        if abs_pct >= 1.5: return "#d97070"
        return "#c49090"
    elif pct < 0:
        if abs_pct >= 7:   return "#00d966"
        if abs_pct >= 5:   return "#00c255"
        if abs_pct >= 3:   return "#00aa44"
        if abs_pct >= 1.5: return "#009933"
        return "#007722"
    return "#64748b"


def _pct_cell(pct: float, large: bool = False) -> str:
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    color = _pct_color(pct)
    size = "font-size:1.5rem;font-weight:800" if large else "font-size:.9rem;font-weight:700"
    return f'<span style="color:{color};{size};white-space:nowrap">{arrow} {sign}{pct:.2f}%</span>'


def _bar(up: int, down: int, flat: int) -> str:
    total = up + down + flat or 1
    w_up = int(up / total * 60)
    w_dn = int(down / total * 60)
    w_fl = max(0, 60 - w_up - w_dn)
    return (
        f'<span style="display:inline-block;height:6px;width:{w_up}px;background:#d97070;border-radius:2px 0 0 2px;vertical-align:middle"></span>'
        f'<span style="display:inline-block;height:6px;width:{w_dn}px;background:#009933;vertical-align:middle"></span>'
        f'<span style="display:inline-block;height:6px;width:{w_fl}px;background:#1e293b;border-radius:0 2px 2px 0;vertical-align:middle"></span>'
    )


def _fmt_price(val: float) -> str:
    if val >= 100 and val == int(val):
        return f"{int(val):,}"
    return f"{val:.2f}"


def _stock_cards(sector_name: str, sectors_df: pd.DataFrame, prices_df: pd.DataFrame) -> str:
    if sectors_df is None or prices_df is None:
        return ""
    sector_stocks = sectors_df[sectors_df["sector_name"] == sector_name]
    if sector_stocks.empty:
        return ""

    name_map = dict(zip(
        sector_stocks["stock_id"].astype(str),
        sector_stocks["stock_name"].astype(str)
    ))
    prices_map = prices_df.set_index("stock_id") if not prices_df.empty else pd.DataFrame()

    cards = []
    for sid in sorted(name_map.keys()):
        stock_name = name_map[sid]
        if sid in prices_map.index:
            p = prices_map.loc[sid]
            close = float(p["close"])
            pct = float(p["change_pct"])
            vol = int(p["volume"])
            color = _pct_color(pct)
            sign = "+" if pct >= 0 else ""
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
            cards.append(
                f'<div class="stock-card" style="border-color:{color}33">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body">'
                f'<span class="sc-price">{_fmt_price(close)}</span>'
                f'<span class="sc-pct" style="color:{color}">{arrow} {sign}{pct:.2f}%</span>'
                f'</div>'
                f'<div class="sc-vol">{vol:,} 張</div>'
                f'</div>'
            )
        else:
            cards.append(
                f'<div class="stock-card no-data">'
                f'<div class="sc-header">'
                f'<span class="sc-id">{sid}</span>'
                f'<span class="sc-name">{stock_name}</span>'
                f'</div>'
                f'<div class="sc-body"><span class="sc-price" style="color:#334155">無行情</span></div>'
                f'</div>'
            )

    return (
        f'<tr class="detail-row" style="display:none">'
        f'<td colspan="4">'
        f'<div class="stock-cards-wrap">{"".join(cards)}</div>'
        f'</td></tr>'
    )


def _sector_row(row, sectors_df=None, prices_df=None, compact=False) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_cards(row["sector_name"], sectors_df, prices_df)
    has_detail = bool(detail)

    chevron = '<span class="chevron">›</span>' if has_detail else ""
    clickable = ' class="clickable-sector"' if has_detail else ""
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""

    return (
        f'<tr{clickable}{onclick}>'
        f'<td class="name">{row["sector_name"]}{chevron}</td>'
        f'<td>{_pct_cell(pct)}</td>'
        f'<td><span class="cnt" style="color:#f87171">▲{up}</span> '
        f'<span class="cnt" style="color:#4ade80">▼{down}</span> '
        f'<span class="cnt" style="color:#475569">─{flat}</span></td>'
        f'<td class="bar-cell">{_bar(up, down, flat)}</td>'
        f'</tr>'
        + detail
    )


def _top10_card(row, rank: int, sectors_df=None, prices_df=None) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    detail = _stock_cards(row["sector_name"], sectors_df, prices_df)
    has_detail = bool(detail)
    onclick = ' onclick="toggleDetail(this)"' if has_detail else ""
    chevron = '<span class="chevron">›</span>' if has_detail else ""
    color = _pct_color(pct)

    return (
        f'<tr class="top-row clickable-sector"{onclick}>'
        f'<td class="top-rank" style="color:{color}">{rank}</td>'
        f'<td class="top-name">{row["sector_name"]}{chevron}</td>'
        f'<td class="top-pct">{_pct_cell(pct, large=True)}</td>'
        f'<td class="top-counts">'
        f'<span style="color:#f87171">▲{up}</span> '
        f'<span style="color:#4ade80">▼{down}</span>'
        f'</td>'
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

    if sectors_df is not None and not sectors_df.empty:
        sectors_df = sectors_df.copy()
        sectors_df["stock_id"] = sectors_df["stock_id"].astype(str)
    if prices_df is not None and not prices_df.empty:
        prices_df = prices_df.copy()
        prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    df = perf_df.sort_values("avg_change_pct", ascending=False).reset_index(drop=True)
    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    total = len(df)
    up_cnt = int((df["avg_change_pct"] > 0).sum())
    dn_cnt = int((df["avg_change_pct"] < 0).sum())
    flat_cnt = total - up_cnt - dn_cnt
    mkt_avg = df["avg_change_pct"].mean()
    mkt_color = _pct_color(mkt_avg)
    mkt_sign = "+" if mkt_avg >= 0 else ""

    # Top 10
    top10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df) for i, (_, r) in enumerate(df.head(10).iterrows()))
    bot10_html = "".join(_top10_card(r, i+1, sectors_df, prices_df) for i, (_, r) in enumerate(df.tail(10).iloc[::-1].iterrows()))

    # Groups
    df["group"] = df["sector_name"].apply(classify_sector)
    groups_html = ""
    for group_name, _ in SECTOR_GROUPS:
        subset = df[df["group"] == group_name].copy()
        if subset.empty:
            continue
        count = len(subset)
        avg = subset["avg_change_pct"].mean()
        g_color = _pct_color(avg)
        sign = "+" if avg >= 0 else ""

        preview_rows = "".join(_sector_row(r, sectors_df, prices_df) for _, r in subset.head(3).iterrows())
        rest = subset.iloc[3:]
        rest_rows = "".join(_sector_row(r, sectors_df, prices_df) for _, r in rest.iterrows()) if not rest.empty else ""
        expand_btn = (
            f'<button class="expand-btn" onclick="toggleGroup(this)">展開全部（{count}）<span style="font-size:.8rem">⌄</span></button>'
            if not rest.empty else ""
        )

        groups_html += f"""
<details class="group-block">
  <summary class="group-header">
    <span class="g-chevron">›</span>
    <span class="g-name">{group_name}</span>
    <span class="g-avg" style="color:{g_color}">{sign}{avg:.2f}%</span>
    <span class="g-count">{count} 族群</span>
  </summary>
  <table class="sector-table">
    <thead><tr><th>族群</th><th>漲跌幅</th><th>漲跌平</th><th>分布</th></tr></thead>
    <tbody class="preview-rows">{preview_rows}</tbody>
    <tbody class="rest-rows" style="display:none">{rest_rows}</tbody>
  </table>
  {f'<div class="group-footer">{expand_btn}</div>' if expand_btn else ''}
</details>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>台股電子族群 {date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,"Segoe UI",sans-serif;background:#0b0f18;color:#e2e8f0;padding:20px;max-width:1000px;margin:0 auto}}

    /* Header */
    .header{{margin-bottom:24px}}
    h1{{font-size:1.1rem;font-weight:600;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}}
    .mkt-bar{{display:flex;align-items:center;gap:20px;margin-top:8px;padding:12px 16px;background:#141c2e;border-radius:10px;flex-wrap:wrap}}
    .mkt-date{{font-size:1rem;font-weight:600;color:#f1f5f9}}
    .mkt-avg{{font-size:1.3rem;font-weight:800;color:{mkt_color}}}
    .mkt-stat{{font-size:.82rem;color:#64748b}}
    .mkt-stat span{{font-weight:600}}

    /* Top 10 */
    .top-section{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:32px}}
    @media(max-width:600px){{.top-section{{grid-template-columns:1fr}}}}
    .top-card{{background:#0f1624;border:1px solid #1e293b;border-radius:12px;overflow:hidden}}
    .top-card-title{{padding:10px 16px;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #1e293b}}
    .up-title{{color:#d97070}} .down-title{{color:#009933}}
    .top-row{{cursor:pointer}}
    .top-row:hover > td{{background:#1a2235}}
    .top-rank{{width:28px;padding:10px 0 10px 14px;font-size:.75rem;font-weight:700;color:#334155;text-align:center}}
    .top-name{{padding:10px 8px;font-size:.88rem;font-weight:500;color:#cbd5e1;max-width:120px}}
    .top-pct{{padding:10px 8px;text-align:right}}
    .top-counts{{padding:10px 14px 10px 4px;font-size:.75rem;white-space:nowrap;color:#64748b;text-align:right}}

    /* Chevron */
    .chevron{{font-size:1rem;color:#334155;margin-left:4px;display:inline-block;transition:transform .2s;vertical-align:middle}}
    .clickable-sector.open .chevron{{transform:rotate(90deg)}}
    .g-chevron{{font-size:1.1rem;color:#475569;margin-right:2px;transition:transform .2s;display:inline-block}}
    details[open] .g-chevron{{transform:rotate(90deg)}}

    /* Sector table */
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;padding:6px 12px;font-size:.7rem;color:#475569;text-transform:uppercase;border-bottom:1px solid #1e293b}}
    td{{padding:9px 12px;border-bottom:1px solid #0b0f18;font-size:.85rem}}
    .name{{font-weight:500;color:#e2e8f0;max-width:160px}}
    .cnt{{font-size:.78rem;margin-right:4px}}
    .bar-cell{{width:70px}}
    .clickable-sector{{cursor:pointer}}
    .clickable-sector:hover > td{{background:#141c2e}}

    /* Stock cards */
    .detail-row > td{{padding:12px 16px;background:#070b12}}
    .stock-cards-wrap{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
    .stock-card{{background:#0f1624;border:1px solid #1e293b;border-radius:8px;padding:10px 12px;transition:border-color .15s}}
    .stock-card:hover{{border-color:#334155}}
    .no-data{{opacity:.5}}
    .sc-header{{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}}
    .sc-id{{font-size:.72rem;color:#475569;font-weight:600}}
    .sc-name{{font-size:.82rem;color:#94a3b8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .sc-body{{display:flex;align-items:baseline;justify-content:space-between;gap:6px;margin-bottom:4px}}
    .sc-price{{font-size:1rem;font-weight:700;color:#f1f5f9}}
    .sc-pct{{font-size:.82rem;font-weight:700}}
    .sc-vol{{font-size:.7rem;color:#334155}}

    /* Groups */
    .section-bar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
    .section-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#475569}}
    .collapse-all-btn{{background:none;border:1px solid #1e293b;color:#475569;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:.75rem;transition:all .15s}}
    .collapse-all-btn:hover{{border-color:#334155;color:#94a3b8}}
    .group-block{{border:1px solid #1e293b;border-radius:10px;margin-bottom:8px;overflow:hidden}}
    .group-header{{display:flex;align-items:center;gap:10px;padding:11px 16px;cursor:pointer;list-style:none;background:#0f1624;user-select:none}}
    .group-header:hover{{background:#141c2e}}
    .group-header::-webkit-details-marker{{display:none}}
    details[open] > .group-header{{border-bottom:1px solid #1e293b}}
    .g-name{{font-weight:600;color:#e2e8f0;flex:1;font-size:.9rem}}
    .g-avg{{font-weight:800;font-size:1rem}}
    .g-count{{font-size:.72rem;color:#334155}}
    .sector-table td,.sector-table th{{padding:8px 16px}}
    .group-footer{{padding:8px 16px;text-align:right;background:#0b0f18}}
    .expand-btn{{background:none;border:1px solid #1e293b;color:#475569;padding:5px 14px;border-radius:6px;cursor:pointer;font-size:.78rem;transition:all .15s}}
    .expand-btn:hover{{border-color:#334155;color:#94a3b8}}

    .footer{{margin-top:28px;font-size:.7rem;color:#1e293b;text-align:center;padding-bottom:20px}}
  </style>
</head>
<body>
  <div class="header">
    <h1>台股電子半導體族群追蹤</h1>
    <div class="mkt-bar">
      <span class="mkt-date">📅 {date_str}（週{weekday}）</span>
      <span class="mkt-avg">{mkt_sign}{mkt_avg:.2f}%</span>
      <span class="mkt-stat">上漲 <span style="color:#d97070">{up_cnt}</span></span>
      <span class="mkt-stat">下跌 <span style="color:#009933">{dn_cnt}</span></span>
      <span class="mkt-stat">平盤 <span style="color:#475569">{flat_cnt}</span></span>
      <span class="mkt-stat" style="margin-left:auto;color:#334155">MoneyDJ × TWSE/TPEx</span>
    </div>
  </div>

  <div class="top-section">
    <div class="top-card">
      <div class="top-card-title up-title">▲ 今日漲幅 Top 10</div>
      <table><tbody>{top10_html}</tbody></table>
    </div>
    <div class="top-card">
      <div class="top-card-title down-title">▼ 今日跌幅 Top 10</div>
      <table><tbody>{bot10_html}</tbody></table>
    </div>
  </div>

  <div class="section-bar">
    <span class="section-title">所有族群 / 依分類</span>
    <button class="collapse-all-btn" onclick="collapseAll()">⊟ 全部收合</button>
  </div>
  {groups_html}

  <div class="footer">點擊族群名稱可展開個股 ｜ 台灣：漲紅跌綠</div>

  <script>
    function toggleDetail(row) {{
      const next = row.nextElementSibling;
      if (!next || !next.classList.contains('detail-row')) return;
      const open = next.style.display !== 'none';
      next.style.display = open ? 'none' : '';
      row.classList.toggle('open', !open);
    }}
    function toggleGroup(btn) {{
      const rest = btn.closest('.group-block').querySelector('.rest-rows');
      const open = rest.style.display !== 'none';
      rest.style.display = open ? 'none' : '';
      btn.innerHTML = open ? '展開全部 <span style="font-size:.8rem">⌄</span>' : '收合 <span style="font-size:.8rem">⌃</span>';
    }}
    function collapseAll() {{
      // 收合所有 <details> 分組
      document.querySelectorAll('details.group-block').forEach(d => d.open = false);
      // 收合所有展開的個股
      document.querySelectorAll('.detail-row').forEach(r => r.style.display = 'none');
      document.querySelectorAll('.clickable-sector.open').forEach(r => r.classList.remove('open'));
      // 重置展開按鈕文字
      document.querySelectorAll('.expand-btn').forEach(btn => {{
        btn.innerHTML = btn.innerHTML.replace('收合', '展開全部').replace('⌃', '⌄');
      }});
    }}
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
