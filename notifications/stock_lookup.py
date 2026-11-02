"""Telegram 查股（2026-11-02 Cody）：打股號或名稱回一則精簡個股資訊；另有 /推薦 /一字鎖 /熱度 /報告。
只讀 DB 與 data/recommend_payload.json，不跑任何資料更新。
回覆用 parse_mode=HTML：標題粗體、數字放 <pre> 等寬區塊、標籤依顯示寬度對齊（2026-11-03 Cody：排版太醜）。
所有資料內容都要 escape。"""
import json
import os
from html import escape
from pathlib import Path

import duckdb
import pandas as pd

from recommend.data import DB_PATH, EVENTS_PATH, UNIVERSE_PATH, adj_multiplier, event_factors
from recommend.telegram_format import _pad, _width
from screener.data_integrity import market_day_complete

PAYLOAD_PATH = Path("data/recommend_payload.json")
SITE_URL = os.environ.get("SITE_URL", "https://coody0111.github.io/tw-sector-tracker/").rstrip("/") + "/"
MAX_CANDIDATES = 8
HISTORY_DAYS = 260
WINDOW = 5                 # 法人、融資、外資持股都看 5 個交易日
BUSY = "資料庫正在更新，請 1～2 分鐘後再試。"
HELP = ("查股：直接打股號或名稱，例如 3147、大綜。\n"
        "指令：/推薦 /一字鎖 /熱度 /報告")


def _md(d) -> str:
    s = str(d)[:10]
    return f"{s[5:7]}/{s[8:10]}"


def _pct(v, nd: int = 1, suffix: str = "%") -> str:
    return "—" if v is None or pd.isna(v) else f"{v:+.{nd}f}{suffix}".replace("-", "−")


def _load_payload(path: Path = PAYLOAD_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_stocks(query: str, universe: pd.DataFrame) -> pd.DataFrame:
    """股號完全相同優先；否則名稱完全相同；再來名稱包含（忽略 * 與大小寫）。"""
    q = query.strip()
    hit = universe[universe["stock_id"] == q]
    if len(hit):
        return hit
    names = universe["stock_name"].str.replace("*", "", regex=False).str.lower()
    key = q.replace("*", "").lower()
    exact = universe[names == key]
    return exact if len(exact) else universe[names.str.contains(key, regex=False)]


def _marks(sid: str, sector: str, payload: dict) -> str:
    marks = []
    for g in payload.get("new") or []:
        if any(c["stock_id"] == sid for c in g["cards"]):
            marks.append("今日新訊號")
    for c in payload.get("active") or []:
        if c["stock_id"] == sid:
            marks.append(f"推薦第 {c['day_n']} 天")
    if any(c["stock_id"] == sid for c in payload.get("invalid") or []):
        marks.append("推薦已失效")
    for r in payload.get("one_word") or []:
        if r["stock_id"] == sid:
            marks.append(f"一字鎖 近10日{r['count']}次" + (f"(連{r['streak']})" if r["streak"] > 1 else ""))
    for s in (payload.get("heat") or {}).get("sectors") or []:
        if s["sector"] == sector:
            marks.append(f"族群熱度 #{s['rank']}")
    return "｜".join(marks) or "無"


def _ema(s: pd.Series, n: int) -> float:
    return float(s.ewm(span=n, adjust=False).mean().iloc[-1])


def _adjusted(px: pd.DataFrame, sid: str, events_path: str) -> pd.Series:
    """均線、52 週高、21 日用還原價（除權息的下跳不算跌）；沒有事件表就用原始價。顯示的收盤仍是原始價。"""
    try:
        events = pd.read_csv(events_path, dtype={"stock_id": str})
    except FileNotFoundError:
        return px["close"]
    x = px.assign(stock_id=sid, date=pd.to_datetime(px["date"]))
    return px["close"] * adj_multiplier(x, event_factors(events[events["stock_id"] == sid], x)).to_numpy()


def _days(con, table: str, peers: list, n: int) -> list:
    """籌碼的 n 個交易日窗口（新到舊）：同市場（上市／上櫃）這張表最新的資料日往回數 daily_prices 的交易日。
    表裡只存有變動的日子，不能用 LIMIT n 筆（bug-reports 2026-11-02：8272 跨了 8 個交易日）；窗口內沒資料的日子算 0。"""
    last = con.execute(f"SELECT max(date) FROM {table} WHERE stock_id = ANY(?)", [peers]).fetchone()[0]
    if last is None:
        return []
    return [r[0] for r in con.execute("SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
                                      [last, n]).fetchall()]


def _asof_value(con, col: str, table: str, sid: str, d):
    """sid 在 d（含）之前最後一筆的值；沒有就 None。"""
    r = con.execute(f"SELECT {col} FROM {table} WHERE stock_id = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                    [sid, d]).fetchone()
    return None if r is None else r[0]


LABEL_W = 11        # 標籤欄顯示寬度（中文 2 格）；「11/02 收盤」「離 52 週高」寬 10，留 1 格空白
VALUE_W = 9         # 數值欄靠右
SEP = "-"           # 用半形；「─」在部分手機字型算 2 格寬，線會比內容長


def _line(label: str, value: str, note: str = "", value_w: int = VALUE_W) -> str:
    return (_pad(label, LABEL_W) + _pad(value, value_w, right=True) + (f"  {note}" if note else "")).rstrip()


def _ascii_minus(text: str) -> str:
    """<pre> 裡負號用半形：「−」(U+2212) 在部分手機字型算 2 格寬，數字欄會歪。"""
    return text.replace("−", "-")


def _block(groups: list) -> str:
    """groups：[[(標籤, 數值, 備註), ...], ...]；組跟組之間用分割線（2026-11-03 Cody），整段放 <pre>。
    數值欄寬至少 VALUE_W，大型股（法人 -206,512 張）放不下就依這則最寬的數值加寬；分割線跟最長的一行一樣長。"""
    rows = [r for g in groups for r in g]
    vw = max([VALUE_W] + [_width(r[1]) for r in rows])
    lines = [[_line(*r, value_w=vw) for r in g] for g in groups]
    sep = SEP * max(_width(l) for g in lines for l in g)
    text = f"\n{sep}\n".join("\n".join(g) for g in lines)
    return f"<pre>{escape(_ascii_minus(text))}</pre>"


def _window_note(con, table: str, days: list, peers: set, price_day: str) -> str:
    """5 日窗口的備註：「至 MM/DD」（籌碼跟行情不同天）＋「缺 N 天」（窗口內有幾天整個市場沒到齊，
    那幾天的加總是少算的，不是真的 0；code review 2026-11-03 #6）。"""
    if not days:
        return ""
    gaps = sum(not market_day_complete(con, table, d, peers) for d in days)
    return "  ".join(x for x in (_asof(days[0], price_day), f"缺 {gaps} 天" if gaps else "") if x)


def _lots(n: int) -> str:
    return f"{n:+,}".replace("-", "−") if n else "0"


def _sum_window(con, table: str, col: str, sid: str, days: list):
    if not days:
        return None
    v = con.execute(f"SELECT sum({col}) FROM {table} WHERE stock_id = ? AND date = ANY(?)", [sid, days]).fetchone()[0]
    return v or 0


def stock_card(row: pd.Series, con, payload: dict, events_path: str = EVENTS_PATH,
               universe_ids: dict | None = None) -> str:
    """標題（股號名稱、族群）＋等寬區塊四組：行情、趨勢、籌碼、營收＋系統標記。籌碼日期跟行情不同天時在備註標「至 MM/DD」。"""
    sid = row["stock_id"]
    universe_ids = universe_ids or {}
    title = f"<b>{escape(sid)} {escape(row['stock_name'])}</b>  {escape(row['meta_sector'])}"
    px = con.execute("SELECT date, close, change_pct, volume FROM daily_prices WHERE stock_id = ? "
                     "ORDER BY date DESC LIMIT ?", [sid, HISTORY_DAYS]).df().iloc[::-1].reset_index(drop=True)
    if px.empty:
        return f"{title}\n沒有行情資料。"
    c, last = _adjusted(px, sid, events_path), px.iloc[-1]
    day = _md(last["date"])
    vr = last["volume"] / px["volume"].iloc[-21:-1].mean() if len(px) > 21 else None
    ma60 = c.iloc[-60:].mean() if len(c) >= 60 else None
    quote = [(f"{day} 收盤", f"{last['close']:,.2f}", _pct(last["change_pct"], 2)),
             ("成交量", f"{int(last['volume']):,} 張", "" if vr is None else f"量比 {vr:.1f}")]
    trend = [("距 10EMA", _pct((c.iloc[-1] / _ema(c, 10) - 1) * 100), ""),
             ("距 20EMA", _pct((c.iloc[-1] / _ema(c, 20) - 1) * 100), ""),
             ("季線", "—" if ma60 is None else ("站上" if c.iloc[-1] >= ma60 else "跌破"), ""),
             ("離 52 週高", _pct((c.iloc[-1] / c.iloc[-250:].max() - 1) * 100), ""),
             ("21 日", _pct((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 21 else "—", "")]
    peers = list(universe_ids.get(row.get("exchange"), [sid]))
    inst_days = _days(con, "institutional", peers, WINDOW)
    inst = _sum_window(con, "institutional", "foreign_net + trust_net", sid, inst_days)
    fh_days = _days(con, "foreign_holdings", peers, WINDOW + 1)
    fh = ([_asof_value(con, "foreign_pct", "foreign_holdings", sid, d) for d in (fh_days[0], fh_days[-1])]
          if len(fh_days) == WINDOW + 1 else [None, None])
    mg_days = _days(con, "margin", peers, WINDOW)
    mg = _sum_window(con, "margin", "margin_change", sid, mg_days)
    big = con.execute("SELECT date, week_chg FROM shareholder WHERE stock_id = ? ORDER BY date DESC LIMIT 1", [sid]).df()
    has_big = not big.empty and pd.notna(big["week_chg"].iloc[0])
    peer_set = set(peers)
    chips = [("法人 5 日", "—" if inst is None else f"{_lots(int(inst / 1000))} 張",
              _window_note(con, "institutional", inst_days, peer_set, day)),
             ("外資持股", "—" if None in fh else _pct(fh[0] - fh[1], 2, "pp"), _asof(fh_days[0], day) if fh_days else ""),
             ("大戶週增", _pct(big["week_chg"].iloc[0], 2, "pp") if has_big else "—",
              f"集保 {_md(big['date'].iloc[0])}" if has_big else ""),
             ("融資 5 日", "—" if mg is None else f"{_lots(int(mg))} 張", _window_note(con, "margin", mg_days, peer_set, day))]
    rev = con.execute("SELECT revenue_month, reported_yoy_pct FROM monthly_revenue WHERE stock_id = ? "
                      "ORDER BY revenue_month DESC LIMIT 1", [sid]).df()
    revenue = [("營收年增", "—", "") if rev.empty else
               ("營收年增", _pct(rev["reported_yoy_pct"].iloc[0]), f"{int(str(rev['revenue_month'].iloc[0])[5:7])} 月")]
    body = _block([quote, trend, chips, revenue])          # 負號在 _pct／_lots 就換成 −，分割線保持半形 -
    return f"{title}\n{body}\n標記：{escape(_marks(sid, row['meta_sector'], payload))}"


def _asof(d, price_day: str) -> str:
    return "" if _md(d) == price_day else f"至 {_md(d)}"


def lookup(query: str, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH,
           payload_path: Path = PAYLOAD_PATH) -> str:
    universe = pd.read_csv(universe_path, dtype=str, encoding="utf-8-sig")
    hits = find_stocks(query, universe)
    if hits.empty:
        return f"找不到「{escape(query)}」。\n{HELP}"
    if len(hits) > 1:
        names = "、".join(f"{r.stock_id} {escape(r.stock_name)}" for r in hits.head(MAX_CANDIDATES).itertuples())
        more = f" 等 {len(hits)} 檔" if len(hits) > MAX_CANDIDATES else ""
        return f"有 {len(hits)} 檔符合，請打股號：{names}{more}"
    try:
        con = duckdb.connect(db_path, read_only=True)
    except duckdb.Error:                 # 排程正在寫 DB 時拿不到鎖
        return BUSY
    try:
        ids = universe.groupby("exchange")["stock_id"].apply(list).to_dict() if "exchange" in universe else {}
        return stock_card(hits.iloc[0], con, _load_payload(payload_path), universe_ids=ids)
    finally:
        con.close()


def _table(head: list, rows: list) -> str:
    """head／rows 每格 (文字, 寬度, 靠右)；放 <pre>，中文依顯示寬度對齊。"""
    fmt = lambda cells: " ".join(_pad(t, w, r) for t, w, r in cells).rstrip()
    line = SEP * (sum(w for _, w, _ in head) + len(head) - 1)          # 表頭下面一條分割線
    return "<pre>" + escape(_ascii_minus("\n".join([fmt(head), line] + [fmt(r) for r in rows]))) + "</pre>"


def _name(s: str, w: int) -> str:
    """名稱超過欄寬就截斷，避免把後面的欄位推歪。"""
    out = ""
    for ch in s:
        if _width(out + ch) > w:
            break
        out += ch
    return out


def _cmd_recommend(p: dict) -> str:
    if not p:
        return "還沒有推薦資料。"
    new = [c for g in p.get("new") or [] for c in g["cards"]]
    head = f"<b>{_md(p['trade_date'])} 推薦</b>"
    rows = [[(c["stock_id"], 6, False), (_name(c["stock_name"], 10), 10, False), (_name(c.get("meta_sector") or "", 14), 14, False)]
            for c in new[:15]]
    body = _table([("股號", 6, False), ("名稱", 10, False), ("族群", 14, False)], rows) if new else "今天沒有新訊號"
    tail = f"新訊號 {len(new)}｜仍有效 {len(p.get('active') or [])}｜已失效 {len(p.get('invalid') or [])}"
    return f"{head}\n{body}\n{tail}\n{SITE_URL}recommend.html"


def _cmd_one_word(p: dict) -> str:
    rows = p.get("one_word") or []
    if not rows:
        return "近 10 個交易日沒有一字鎖。"
    body = _table([("股號", 6, False), ("名稱", 8, False), ("最後", 5, False), ("次", 2, True), ("連", 2, True), ("量(張)", 7, True)],
                  [[(r["stock_id"], 6, False), (_name(r["stock_name"], 8), 8, False), (_md(r["last_date"]), 5, False),
                    (str(r["count"]), 2, True), (str(r["streak"]), 2, True), (f"{r['volume']:,}", 7, True)] for r in rows])
    return f"<b>近 10 個交易日一字鎖</b>\n{body}\n{SITE_URL}recommend.html"


def _cmd_heat(p: dict) -> str:
    top = ((p.get("heat") or {}).get("top") or [])[:5]
    if not top:
        return "還沒有熱度資料。"
    body = _table([("#", 2, True), ("族群", 14, False), ("熱度", 4, True), ("21日", 7, True), ("狀態", 6, False)],
                  [[(str(s["rank"]), 2, True), (_name(s["sector"], 14), 14, False), (f"{s['score']:.0f}", 4, True),
                    (_pct(s.get("ret21")), 7, True), (s["status"], 6, False)] for s in top])
    return f"<b>族群熱度前 5</b>\n{body}\n{SITE_URL}index.html#heat"


def _cmd_report(p: dict) -> str:
    return f"每日報告：{SITE_URL}report.html\n每週籌碼：{SITE_URL}weekly.html"


COMMANDS = {"推薦": _cmd_recommend, "一字鎖": _cmd_one_word, "熱度": _cmd_heat, "報告": _cmd_report}


def handle(text: str, db_path: str = DB_PATH, universe_path: str = UNIVERSE_PATH,
           payload_path: Path = PAYLOAD_PATH) -> str:
    """一則訊息 → 回覆文字。/help、/start、空白都回說明。"""
    t = (text or "").strip()
    key = t.lstrip("/").split("@")[0]
    if not key or key.lower() in ("help", "start", "說明"):
        return HELP
    if key in COMMANDS:
        return COMMANDS[key](_load_payload(payload_path))
    return lookup(key, db_path, universe_path, payload_path)
