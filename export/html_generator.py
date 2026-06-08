import pandas as pd
from pathlib import Path
from datetime import date
from config import classify_sector, SECTOR_GROUPS


def _pct_cell(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")
    return f'<span class="pct {cls}">{arrow} {sign}{pct:.2f}%</span>'


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


def _sector_row(row) -> str:
    pct = row["avg_change_pct"]
    up, down, flat = int(row["up_count"]), int(row["down_count"]), int(row["flat_count"])
    return f"""<tr>
      <td class="name">{row["sector_name"]}</td>
      <td>{_pct_cell(pct)}</td>
      <td><span class="cnt up-txt">▲{up}</span> <span class="cnt dn-txt">▼{down}</span> <span class="cnt fl-txt">─{flat}</span></td>
      <td class="bar-cell">{_bar(up, down, flat)}</td>
    </tr>"""


def generate(trade_date: date, perf_df: pd.DataFrame, output_path: str = "docs/index.html") -> None:
    if perf_df.empty:
        return

    df = perf_df.sort_values("avg_change_pct", ascending=False).reset_index(drop=True)
    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    # ── C 部分：Top10 漲 / 跌 ──
    top10 = df.head(10)
    bot10 = df.tail(10).iloc[::-1]

    def top_rows(subset):
        return "".join(_sector_row(r) for _, r in subset.iterrows())

    top_html = top_rows(top10)
    bot_html = top_rows(bot10)

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
        sign = "+" if avg >= 0 else ""
        g_cls = "up" if avg > 0 else ("down" if avg < 0 else "flat")
        preview = subset.head(3)
        rest = subset.iloc[3:]

        preview_rows = "".join(_sector_row(r) for _, r in preview.iterrows())
        rest_rows = "".join(_sector_row(r) for _, r in rest.iterrows()) if not rest.empty else ""
        expand_btn = f'<button class="expand-btn" onclick="toggleGroup(this)">展開全部 ({count})</button>' if not rest.empty else f'<span class="total-badge">{count} 族群</span>'

        groups_html += f"""
  <details class="group-block">
    <summary class="group-header">
      <span class="g-name">{group_name}</span>
      <span class="g-avg pct {g_cls}">{'+' if avg>=0 else ''}{avg:.2f}%</span>
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

    /* Top 10 section */
    .top-section{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:32px}}
    @media(max-width:600px){{.top-section{{grid-template-columns:1fr}}}}
    .top-card h2{{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #1e293b}}
    .top-card h2.up-title{{color:#f87171}} .top-card h2.down-title{{color:#4ade80}}

    /* Tables */
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;padding:6px 10px;font-size:.72rem;color:#64748b;text-transform:uppercase;border-bottom:1px solid #1e293b}}
    td{{padding:8px 10px;border-bottom:1px solid #0f1117;font-size:.85rem}}
    tr:hover td{{background:#1e293b}}
    .name{{font-weight:500;color:#f1f5f9;max-width:180px}}
    .pct{{font-weight:700;font-size:.9rem;white-space:nowrap}}
    .pct.up{{color:#f87171}} .pct.down{{color:#4ade80}} .pct.flat{{color:#94a3b8}}
    .cnt{{font-size:.78rem}} .up-txt{{color:#f87171}} .dn-txt{{color:#4ade80}} .fl-txt{{color:#64748b}}
    .bar-cell{{width:70px}}
    .bar-up,.bar-dn,.bar-fl{{display:inline-block;height:6px;vertical-align:middle}}
    .bar-up{{background:#f87171;border-radius:2px 0 0 2px}}
    .bar-dn{{background:#4ade80}}
    .bar-fl{{background:#1e293b;border-radius:0 2px 2px 0}}

    /* Group blocks */
    .section-title{{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:12px;margin-top:8px}}
    .group-block{{border:1px solid #1e293b;border-radius:8px;margin-bottom:8px;overflow:hidden}}
    .group-header{{display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;list-style:none;background:#141820}}
    .group-header:hover{{background:#1e293b}}
    .group-header::-webkit-details-marker{{display:none}}
    details[open] .group-header{{border-bottom:1px solid #1e293b}}
    .g-name{{font-weight:600;color:#f1f5f9;flex:1;font-size:.9rem}}
    .g-avg{{font-weight:700;font-size:.95rem}}
    .g-count{{font-size:.75rem;color:#64748b}}
    .sector-table{{margin:0}}
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

  <!-- C: Top 10 漲跌 -->
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

  <!-- B: 分組可收合 -->
  <div class="section-title">所有族群（依分類）</div>
  {groups_html}

  <div class="footer">注意：台灣股市漲紅跌綠</div>

  <script>
    function toggleGroup(btn) {{
      const rest = btn.closest('.group-block').querySelector('.rest-rows');
      if (rest.style.display === 'none') {{
        rest.style.display = '';
        btn.textContent = '收合';
      }} else {{
        rest.style.display = 'none';
        const count = rest.querySelectorAll('tr').length + 3;
        btn.textContent = '展開全部 (' + count + ')';
      }}
    }}
  </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
