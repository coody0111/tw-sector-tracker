"""Generate the user-owned static watchlist workspace."""

from datetime import date
from html import escape
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd


WATCHLIST_KEY = "tw-sector-watchlist-v1"


def _clean(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    return str(value)


def build_watchlist_rows(
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    selected_ids: Iterable[str] = (),
    rolling_returns: Optional[dict] = None,
    chips_df: Optional[pd.DataFrame] = None,
) -> list[dict[str, Any]]:
    """Build only the user-selected rows; keep missing selections visible."""
    selected = [str(stock_id) for stock_id in selected_ids]
    universe = universe_df.copy() if universe_df is not None else pd.DataFrame()
    if not universe.empty:
        universe["stock_id"] = universe["stock_id"].astype(str)
    info = universe.drop_duplicates("stock_id").set_index("stock_id").to_dict("index") if not universe.empty else {}

    prices = prices_df.copy() if prices_df is not None else pd.DataFrame()
    if not prices.empty:
        prices["stock_id"] = prices["stock_id"].astype(str)
        if "date" in prices.columns:
            prices = prices.sort_values("date").drop_duplicates("stock_id", keep="last")
    price_map = prices.set_index("stock_id").to_dict("index") if not prices.empty else {}

    chips = chips_df.copy() if chips_df is not None else pd.DataFrame()
    if not chips.empty:
        chips["stock_id"] = chips["stock_id"].astype(str)
    chips_map = chips.set_index("stock_id").to_dict("index") if not chips.empty else {}
    rolling = rolling_returns or {}

    rows = []
    for stock_id in selected:
        stock = info.get(stock_id, {})
        price = price_map.get(stock_id, {})
        chip = chips_map.get(stock_id, {})
        status = "unknown-stock" if not stock else ("ok" if price else "no-data")
        row = {
            "stock_id": stock_id,
            "stock_name": _clean(stock.get("stock_name")) or "未知股票",
            "meta_sector": _clean(stock.get("meta_sector")) or "",
            "close": price.get("close"),
            "change_pct": price.get("change_pct"),
            "date": _clean(price.get("date")),
            "data_status": status,
            "foreign_net": chip.get("foreign_net"),
            "trust_net": chip.get("trust_net"),
            "dealer_net": chip.get("dealer_net"),
        }
        for period in (5, 7, 10, 14):
            row[f"roll{period}"] = (rolling.get(stock_id) or {}).get(period)
        rows.append(row)
    return rows


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+.2f}%"


def generate(
    trade_date: date,
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    rolling_returns: Optional[dict] = None,
    chips_df: Optional[pd.DataFrame] = None,
    output_path: str = "docs/watchlist.html",
) -> None:
    """Generate a static page; the browser supplies the user's local selection."""
    catalog = []
    if universe_df is not None and not universe_df.empty:
        for _, row in universe_df.drop_duplicates("stock_id").iterrows():
            catalog.append({
                "stock_id": str(row["stock_id"]),
                "stock_name": _clean(row.get("stock_name")) or "未知股票",
                "meta_sector": _clean(row.get("meta_sector")) or "",
            })
    market_rows = build_watchlist_rows(
        universe_df, prices_df, [row["stock_id"] for row in catalog], rolling_returns, chips_df
    )
    market_map = {row["stock_id"]: row for row in market_rows}
    catalog_js = _json(catalog)
    market_js = _json(market_map)
    generated = trade_date.isoformat()

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的自選股 {escape(generated)}</title>
<style>
:root{{--bg:#101315;--panel:#171c1f;--panel-2:#20272a;--ink:#edf1ed;--muted:#9ca9a4;--border:#34403f;--accent:#d4a24e;--up:#4bbd82;--down:#ed756c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,"Noto Sans TC",sans-serif}}
.topbar{{display:flex;align-items:center;gap:18px;padding:16px 24px;border-bottom:1px solid var(--border);flex-wrap:wrap}}
.brand{{margin-right:auto}}.eyebrow{{font:700 .65rem monospace;letter-spacing:.14em;color:var(--accent)}}h1{{margin:5px 0 0;font-size:1.25rem}}
nav{{display:flex;gap:8px}}nav a,.button{{display:inline-flex;align-items:center;min-height:40px;padding:0 12px;border:1px solid var(--border);border-radius:5px;background:var(--panel-2);color:var(--ink);text-decoration:none;font-size:.78rem;cursor:pointer}}
main{{max-width:1400px;margin:0 auto;padding:24px}}.intro{{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:18px;flex-wrap:wrap}}
.intro h2{{margin:5px 0;font-size:1.45rem}}.intro p{{margin:0;color:var(--muted);font-size:.82rem}}.count{{color:var(--accent);font:700 .75rem monospace}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--border);border-radius:7px;padding:16px}}
.card-head{{display:flex;align-items:baseline;gap:8px}}.id{{color:var(--muted);font:700 .75rem monospace}}.name{{font-size:1.05rem;font-weight:700;flex:1}}.meta{{margin:5px 0 14px;color:var(--muted);font-size:.72rem}}
.price{{font:700 1.15rem monospace}}.pct{{margin-left:9px;font:700 .85rem monospace}}.positive{{color:var(--up)}}.negative{{color:var(--down)}}.muted{{color:var(--muted)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:15px 0}}.metric{{padding:8px;background:var(--panel-2);border-radius:4px}}.metric label{{display:block;color:var(--muted);font: .62rem monospace}}.metric strong{{display:block;margin-top:4px;font:700 .8rem monospace}}
.analysis{{border-top:1px solid var(--border);padding-top:12px;color:var(--muted);font-size:.75rem;line-height:1.6}}.analysis b{{color:var(--ink)}}.note{{width:100%;margin-top:12px;min-height:56px;padding:8px;border:1px solid var(--border);border-radius:4px;background:var(--panel-2);color:var(--ink);font: .78rem Arial}}
.card-actions{{display:flex;gap:8px;margin-top:10px}}.empty{{padding:48px 20px;text-align:center;border:1px dashed var(--border);border-radius:7px;color:var(--muted)}}
@media(max-width:600px){{main{{padding:14px}}.topbar{{padding:14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header class="topbar"><div class="brand"><div class="eyebrow">PERSONAL WORKSPACE</div><h1>我的自選股</h1></div>
<nav aria-label="主要功能"><a href="index.html">族群總覽</a><a href="watchlist.html" aria-current="page">自選股</a><a href="patterns.html">形態掃描</a></nav></header>
<main><div class="intro"><div><div class="eyebrow">OLIVER-INSPIRED WATCHLIST</div><h2>只看你挑選的股票</h2><p>週線看背景，日線看週期；資料不足時保留不確定性。</p></div><span class="count" id="count"></span></div>
<section id="watchlist" class="grid" aria-live="polite"></section></main>
<script>
const WATCHLIST_KEY = {json.dumps(WATCHLIST_KEY)};
const STOCK_CATALOG = {catalog_js};
const MARKET_DATA = {market_js};
function esc(s) {{ const d=document.createElement('div'); d.textContent=String(s ?? ''); return d.innerHTML; }}
function readList() {{ try {{ const v=JSON.parse(localStorage.getItem(WATCHLIST_KEY)||'[]'); return Array.isArray(v)?v.map(String):[]; }} catch (_) {{ return []; }} }}
function writeList(ids) {{ try {{ localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...new Set(ids)])); }} catch (_) {{}} }}
function noteKey(id) {{ return WATCHLIST_KEY + ':note:' + id; }}
function readNote(id) {{ try {{ return localStorage.getItem(noteKey(id)) || ''; }} catch (_) {{ return ''; }} }}
function writeNote(id, value) {{ try {{ localStorage.setItem(noteKey(id), value); }} catch (_) {{}} }}
function pct(v) {{ return v === null || v === undefined || !Number.isFinite(Number(v)) ? '—' : (Number(v)>=0?'+':'') + Number(v).toFixed(2) + '%'; }}
function metric(label, value) {{ return `<div class="metric"><label>${{label}}</label><strong>${{esc(pct(value))}}</strong></div>`; }}
function render() {{
  const ids=readList(), wrap=document.getElementById('watchlist');
  document.getElementById('count').textContent=`${{ids.length}} 檔自選`;
  if (!ids.length) {{ wrap.innerHTML='<div class="empty">目前還沒有自選股。請從族群總覽的個股明細加入。</div>'; return; }}
  wrap.innerHTML=ids.map(id=>{{ const s=MARKET_DATA[id] || {{stock_id:id,stock_name:'未知股票',data_status:'unknown-stock'}}; const ch=s.change_pct; const cls=ch>0?'positive':(ch<0?'negative':'muted');
    const status=s.data_status==='ok'?'目前資料':(s.data_status==='no-data'?'目前無行情':'找不到此股票');
    return `<article class="card"><div class="card-head"><span class="id">${{esc(s.stock_id)}}</span><span class="name">${{esc(s.stock_name)}}</span><button class="button" type="button" onclick="removeStock('${{esc(s.stock_id)}}')">移除</button></div><div class="meta">${{esc(s.meta_sector||'')}} · ${{esc(status)}} · ${{esc(s.date||'')}}</div><div><span class="price">${{s.close==null?'—':Number(s.close).toFixed(2)}}</span><span class="pct ${{cls}}">${{esc(pct(ch))}}</span></div><div class="metrics">${{metric('近5日',s.roll5)}}${{metric('近7日',s.roll7)}}${{metric('近10日',s.roll10)}}${{metric('近14日',s.roll14)}}</div><div class="analysis"><div><b>Weekly：</b>待建立週線 Market Structure</div><div><b>Daily：</b>待建立 Price Cycle 判斷</div><div><b>Pivotal Point：</b>待人工標註</div><div><b>Risk：</b>先觀察資料，不自動產生買賣指令</div></div><textarea class="note" aria-label="${{esc(s.stock_id)}} 個人備註" placeholder="寫下你為什麼放進自選…" oninput="writeNote('${{esc(s.stock_id)}}',this.value)">${{esc(readNote(s.stock_id))}}</textarea></article>`;
  }}).join('');
}}
function removeStock(id) {{ writeList(readList().filter(x=>x!==String(id))); render(); }}
window.addEventListener('storage', render); render();
</script></body></html>"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
