"""Shared visual language for the static research pages."""

from html import escape as _html_escape

SHARED_CSS = r"""
:root{--ui-bg:#080B12;--ui-panel:#0F1420;--ui-panel-2:#161D2C;--ui-border:#293346;--ui-border-strong:#37435C;--ui-ink:#DADFE8;--ui-ink-2:#98A0B4;--ui-ink-3:#636B80;--ui-up:#E6432F;--ui-down:#37B25C;--ui-accent:#F0BB55;--ui-radius:6px}
.ui-page-summary{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}.ui-summary-item{min-width:124px;padding:9px 12px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius)}.ui-summary-label{display:block;color:var(--ui-ink-3);font-size:.64rem;letter-spacing:.06em;text-transform:uppercase}.ui-summary-value{display:block;margin-top:2px;color:var(--ui-ink);font-size:1rem;font-weight:750;font-variant-numeric:tabular-nums}.ui-summary-note{display:block;color:var(--ui-ink-2);font-size:.68rem}
.ui-event-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border:1px solid var(--ui-border-strong);border-radius:5px;color:var(--ui-ink-2);font-size:.68rem;font-weight:700;white-space:nowrap}.ui-event-badge[data-direction="up"]{color:var(--ui-up);border-color:rgba(230,67,47,.48);background:rgba(230,67,47,.10)}.ui-event-badge[data-direction="down"]{color:var(--ui-down);border-color:rgba(55,178,92,.48);background:rgba(55,178,92,.10)}.ui-event-badge[data-confidence="draft"]{border-style:dashed;color:var(--ui-ink-3);background:transparent}
.ui-empty{padding:16px 12px;border:1px dashed var(--ui-border-strong);border-radius:var(--ui-radius);color:var(--ui-ink-2);font-size:.76rem;text-align:center}.ui-empty strong{display:block;color:var(--ui-ink);margin-bottom:3px}.ui-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}.ui-compact-card{display:grid;gap:5px;min-width:0;padding:11px 12px;background:var(--ui-panel);border:1px solid var(--ui-border);border-radius:var(--ui-radius);transition:border-color .15s,background .15s,transform .15s}.ui-compact-card:hover{border-color:var(--ui-border-strong);background:var(--ui-panel-2);transform:translateY(-1px)}.ui-card-head{display:flex;align-items:baseline;gap:7px;min-width:0}.ui-card-name{overflow:hidden;color:var(--ui-ink);font-size:.86rem;font-weight:750;text-overflow:ellipsis;white-space:nowrap}.ui-card-id{color:var(--ui-ink-3);font-size:.68rem;font-variant-numeric:tabular-nums}.ui-card-meta{overflow:hidden;color:var(--ui-ink-2);font-size:.7rem;text-overflow:ellipsis;white-space:nowrap}.ui-card-stats{display:flex;flex-wrap:wrap;align-items:center;gap:5px 9px;color:var(--ui-ink-2);font-size:.72rem;font-variant-numeric:tabular-nums}.ui-card-detail{margin-top:3px;padding-top:7px;border-top:1px solid var(--ui-border);color:var(--ui-ink-2);font-size:.72rem}
@media(max-width:640px){.ui-summary-item{flex:1 1 100px;min-width:0}.ui-card-grid{grid-template-columns:1fr}.ui-compact-card{padding:9px 10px}.ui-compact-card:hover{transform:none}}@media(prefers-reduced-motion:reduce){.ui-compact-card{transition:none}.ui-compact-card:hover{transform:none}}
""" + r"""
/* 頁面骨架（2026-10-21 統一）：頁首、頁名、左右留白、內容寬度、字型。各頁 CSS 不要再自訂 body / 頁首。
   2026-10-26 Cody：「這幾個分頁都要整合成一樣的吧 參照族群績效」→ 頁首照 index.html：左邊 TW SECTOR TRACKER 小字＋襯線頁名、
   資料日期靠右、導覽在最右；頁首撐滿寬度、內容寬 1560、左右留白 26（index_generator.py 的 .topbar／.page-shell）。 */
/* --ui-sticky-top：頁內 sticky 元素（分頁籤、工具列）要讓出的高度＝頁首實際高度；render_topbar() 附的 script 會依實際量到的值覆寫（頁首折行時會超過 52px）。 */
:root{--ui-sans:"Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Noto Sans TC","Segoe UI",sans-serif;--ui-mono:ui-monospace,"Cascadia Code","Roboto Mono",monospace;--ui-serif:Georgia,"Iowan Old Style","Source Serif 4","Noto Serif TC",serif;--ui-topbar-h:52px;--ui-sticky-top:var(--ui-topbar-h);--ui-gutter:26px;--ui-max:1612px}
body{margin:0;background:var(--ui-bg);color:var(--ui-ink);font-family:var(--ui-sans);font-size:14px;line-height:1.55}
button,input,select{font-family:inherit}
.ui-topbar{position:sticky;top:0;z-index:20;padding:0 var(--ui-gutter);border-bottom:1px solid var(--ui-border);background:rgba(8,11,18,.94);backdrop-filter:blur(12px)}
.ui-topbar-inner{display:flex;align-items:center;flex-wrap:wrap;gap:6px 14px;min-height:var(--ui-topbar-h);padding:10px 0}
.ui-brand{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.ui-kicker{color:var(--ui-accent);font-size:.62rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase}
.ui-title{margin:0;color:var(--ui-ink);font-family:var(--ui-serif);font-size:1.08rem;font-weight:600;letter-spacing:.01em;line-height:1.3}
.ui-date{margin-left:auto;color:var(--ui-ink-3);font-family:var(--ui-mono);font-size:.68rem;font-variant-numeric:tabular-nums}
.ui-date b{color:var(--ui-accent);font-weight:700}
.ui-nav{display:flex;align-items:center;gap:8px;white-space:nowrap}
.ui-nav-link{display:inline-flex;align-items:center;min-height:32px;padding:5px 14px;border:1px solid var(--ui-border);border-radius:var(--ui-radius);color:var(--ui-ink-2);font-family:var(--ui-sans);font-size:.78rem;font-weight:600;text-decoration:none;transition:color .15s,border-color .15s,background .15s}
.ui-nav-link:hover{color:var(--ui-ink);border-color:var(--ui-border-strong);background:var(--ui-panel)}
.ui-nav-link.active{color:var(--ui-ink);border-color:var(--ui-accent);background:var(--ui-panel-2)}
.ui-nav-link:focus-visible{outline:3px solid var(--ui-accent);outline-offset:2px}
.ui-main{max-width:var(--ui-max);margin:0 auto;padding:20px var(--ui-gutter) 80px}
.ui-sticky-tabs{position:sticky;top:var(--ui-sticky-top);z-index:15;background:var(--ui-bg)}
@media(max-width:1180px){:root{--ui-gutter:18px}}
@media(max-width:760px){
  :root{--ui-gutter:12px;--ui-sticky-top:0px}
  .ui-topbar{position:static}
  .ui-topbar-inner{padding:12px 0}
  .ui-date{margin-left:0}
  .ui-nav{order:3;width:100%;margin-left:0;overflow-x:auto}
  .ui-nav-link{min-height:44px;padding:5px 12px}
}
@media(prefers-reduced-motion:reduce){.ui-nav-link{transition:none}}
"""

# 頁首切頁按鈕：(檔名, 顯示名稱)。順序與名稱跟 index.html 的導覽一致。
NAV_PAGES = (
    ("index.html", "族群績效"),
    ("chips.html", "籌碼分析"),
    ("patterns.html", "形態掃描"),
    ("momentum.html", "逆轟策略"),
    ("recommend.html", "個股推薦"),
    ("watchlist.html", "自選股"),
)


# 量頁首實際高度寫進 --ui-sticky-top；頁首不固定（手機版）時寫 0，頁內分頁籤就黏在最上面。
_STICKY_TOP_JS = (
    "(function(){var t=document.querySelector('.ui-topbar');if(!t)return;"
    "var r=document.documentElement;"
    "function s(){r.style.setProperty('--ui-sticky-top',"
    "(getComputedStyle(t).position==='sticky'?t.offsetHeight:0)+'px')}"
    "s();if(window.ResizeObserver)new ResizeObserver(s).observe(t);"
    "window.addEventListener('resize',s)})();"
)


def render_topbar(title: str, active_href: str, date_html: str = "") -> str:
    """統一頁首：頁名 h1、資料日期、切頁按鈕。date_html 由呼叫端組好（可含 <b>），不做跳脫。"""
    links = "".join(
        f'<a class="ui-nav-link active" href="{href}" aria-current="page">{label}</a>'
        if href == active_href
        else f'<a class="ui-nav-link" href="{href}">{label}</a>'
        for href, label in NAV_PAGES
    )
    date_part = f'<span class="ui-date">{date_html}</span>' if date_html else '<span class="ui-date"></span>'
    return (
        '<header class="ui-topbar"><div class="ui-topbar-inner">'
        f'<div class="ui-brand"><span class="ui-kicker">TW SECTOR TRACKER</span><h1 class="ui-title">{_html_escape(title)}</h1></div>'
        f"{date_part}"
        f'<nav class="ui-nav" aria-label="主要功能">{links}</nav>'
        "</div></header>"
        f"<script>{_STICKY_TOP_JS}</script>"
    )
