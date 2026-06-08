import pandas as pd
from pathlib import Path
from datetime import date


def generate(trade_date: date, perf_df: pd.DataFrame, output_path: str = "docs/index.html") -> None:
    if perf_df.empty:
        return

    perf_sorted = perf_df.sort_values("avg_change_pct", ascending=False).reset_index(drop=True)
    date_str = trade_date.strftime("%Y-%m-%d")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][trade_date.weekday()]

    rows_html = ""
    for _, row in perf_sorted.iterrows():
        pct = row["avg_change_pct"]
        up = int(row["up_count"])
        down = int(row["down_count"])
        flat = int(row["flat_count"])
        total = up + down + flat

        sign = "+" if pct >= 0 else ""
        color_class = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "─")

        up_bar = f'<span class="bar-up" style="width:{int(up/total*80) if total else 0}px"></span>'
        down_bar = f'<span class="bar-down" style="width:{int(down/total*80) if total else 0}px"></span>'
        flat_bar = f'<span class="bar-flat" style="width:{int(flat/total*80) if total else 0}px"></span>'

        rows_html += f"""
        <tr class="{color_class}">
          <td class="name">{row["sector_name"]}</td>
          <td class="pct {color_class}">{arrow} {sign}{pct:.2f}%</td>
          <td class="counts">
            <span class="up-txt">▲{up}</span>
            <span class="down-txt">▼{down}</span>
            <span class="flat-txt">─{flat}</span>
          </td>
          <td class="bar-cell">{up_bar}{down_bar}{flat_bar}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>台股電子族群追蹤 {date_str}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, "Segoe UI", sans-serif; background: #0f1117; color: #e2e8f0; padding: 24px; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; color: #f8fafc; margin-bottom: 4px; }}
    .date {{ color: #64748b; font-size: 0.9rem; margin-bottom: 24px; }}
    table {{ width: 100%; max-width: 720px; border-collapse: collapse; }}
    th {{ text-align: left; padding: 8px 12px; font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #1e293b; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }}
    tr:hover td {{ background: #1e293b; }}
    .name {{ font-weight: 500; color: #f1f5f9; }}
    .pct {{ font-weight: 700; font-size: 1rem; min-width: 90px; }}
    .pct.up {{ color: #f87171; }}
    .pct.down {{ color: #4ade80; }}
    .pct.flat {{ color: #94a3b8; }}
    .up-txt {{ color: #f87171; margin-right: 8px; }}
    .down-txt {{ color: #4ade80; margin-right: 8px; }}
    .flat-txt {{ color: #64748b; }}
    .bar-cell {{ width: 90px; }}
    .bar-up {{ display: inline-block; height: 8px; background: #f87171; border-radius: 2px 0 0 2px; vertical-align: middle; }}
    .bar-down {{ display: inline-block; height: 8px; background: #4ade80; vertical-align: middle; }}
    .bar-flat {{ display: inline-block; height: 8px; background: #334155; border-radius: 0 2px 2px 0; vertical-align: middle; }}
    .footer {{ margin-top: 24px; font-size: 0.75rem; color: #334155; }}
  </style>
</head>
<body>
  <h1>台股電子半導體族群追蹤</h1>
  <div class="date">📅 {date_str}（週{weekday}）｜資料來源：MoneyDJ × Yahoo Finance</div>
  <table>
    <thead>
      <tr>
        <th>族群</th>
        <th>平均漲跌幅</th>
        <th>漲跌平</th>
        <th>分布</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  <div class="footer">注意：台灣股市漲為紅、跌為綠</div>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
