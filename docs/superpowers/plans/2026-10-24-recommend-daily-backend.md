# 個股推薦：階段 4 每日後端（訊號、成績單、Telegram）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本專案規矩**（CLAUDE.md）：Developer 不自己跑測試、不跑資料；每個 Task 的「Run」步驟由 Debugger 在交接時執行。每個 Task 只 commit 自己的檔，整批完成後 append `debug-tasks.md` 交接。

**Goal:** 收盤流程每天跑所有策略、把訊號記進成績單、算出推薦頁要用的資料（payload），並用 Telegram 發出規格 E21 的表格訊息。

**Architecture:** 沿用階段 2 的 `recommend/`（features、strategies、exits）。新增 `market.py`（頁首大盤數字）、`cards.py`（卡片欄位與提醒）、`scorecard.py`（DuckDB `recommendations` 表）、`daily.py`（組 payload）、`telegram_format.py`（E21 表格）。`main.py` 收盤模式在籌碼寫入後呼叫 `daily.run_daily()`，payload 存 `data/recommend_payload.json` 並放進 summary；`scripts/run_scheduled.py` 收盤時多發一則推薦訊息。

**Tech Stack:** Python 3.11、pandas、DuckDB、pytest、Telegram Bot API（parse_mode=HTML 的 `<pre>`）。

**規格：** `docs/superpowers/specs/2026-10-22-stock-recommendation-design.md` §10、§15（C14、C16、C18、E21、E22）。

**不在這份計畫內：** 推薦頁與成績單頁 HTML（另一份計畫，先用 ui-ux-pro-max 出設計稿給 Cody 確認）；08:00 開盤前更新排程（頁面上線後再做）；「已漲多」門檻 X（等 C15 回測，先傳 `None` 不顯示）。

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `recommend/ticks.py` | 新增 `limit_down_price` |
| `recommend/market.py` | 頁首：股票池站上 MA20 比例、今日漲停／跌停家數、近 10 日突破失敗率 |
| `recommend/cards.py` | 卡片欄位：收盤、漲幅、MA10 乖離、是否在 MA60 之下、提醒字、族群分組 |
| `recommend/scorecard.py` | `recommendations` 表：寫入訊號、每日重算出場、總覽統計 |
| `recommend/daily.py` | `run_daily()`：載入→特徵→策略→成績單→payload |
| `recommend/telegram_format.py` | E21 表格訊息 |
| `notifications/telegram.py` | `send_telegram_message(..., parse_mode=None)` |
| `main.py` | 收盤模式呼叫 `run_daily()`；summary 加 `recommend` |
| `scripts/run_scheduled.py` | 收盤時有 `recommend` 就多發一則 |

---

### Task 1: 跌停價

**Files:**
- Modify: `recommend/ticks.py`
- Test: `tests/test_recommend_ticks.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_recommend_ticks.py
from recommend.ticks import limit_down_price


@pytest.mark.parametrize("ref,limit", [
    (100.0, 90.0),     # 90 → 50～100 跳 0.1 → 90.0
    (306.5, 276.0),    # 275.85 → 100～500 跳 0.5，無條件進位 → 276.0
    (11.0, 9.9),       # 9.9 → <10 跳 0.01 → 9.9
])
def test_limit_down_price_rounds_up_to_tick_of_result(ref, limit):
    assert limit_down_price(ref) == pytest.approx(limit)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recommend_ticks.py -v`
Expected: FAIL（`ImportError: cannot import name 'limit_down_price'`）

- [ ] **Step 3: Write minimal implementation**

```python
# 追加到 recommend/ticks.py
def limit_down_price(ref: float) -> float:
    """參考價 × 0.90，無條件進位到「該價位」的跳動單位。"""
    raw = ref * 0.90
    tick = tick_size(raw)
    return round(math.ceil(raw / tick - 1e-9) * tick, 2)
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_recommend_ticks.py -v`，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/ticks.py tests/test_recommend_ticks.py
git commit -m "feat(recommend): 跌停價"
```

---

### Task 2: 頁首大盤數字

**Files:**
- Create: `recommend/market.py`
- Test: `tests/test_recommend_market.py`

`market_header(features, signals, day)` 回傳 `{"above_ma20_pct", "limit_up", "limit_down", "fail_rate", "fail_n"}`：
- 站上 MA20 比例：`day` 當天 `liq` 為真的股票中，收盤 > 含當天 20 日均線的比例。
- 漲停／跌停家數：`day` 當天 `limit_up` 數；跌停＝收盤 ≤ `limit_down_price(ref)`。
- 突破失敗率：`day` 之前 10 個交易日（不含 `day`）的訊號，隔天開盤進場後、到 `day` 收盤為止任一天收盤 ≤ 進場 × 0.94 的比例；樣本 < 5 筆回 `None`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_market.py
import pandas as pd
import pytest

from recommend.market import market_header


def _feat():
    d = pd.bdate_range("2026-01-01", periods=25)
    rows = []
    for k, dt in enumerate(d):
        for sid, close in (("A", 100.0 + k), ("B", 100.0 - k), ("C", 50.0)):
            rows.append({"stock_id": sid, "date": dt, "open": close, "close": close, "change": 1.0 if sid == "A" else -1.0,
                         "limit_up": sid == "A" and k == 24, "liq": True})
    f = pd.DataFrame(rows)
    f.loc[(f["stock_id"] == "C") & (f["date"] == d[-1]), ["close", "change"]] = [45.0, -5.0]   # 50→45 跌停
    return f, d


def test_market_header_counts_breadth_and_limits():
    f, d = _feat()
    h = market_header(f, pd.DataFrame(columns=["stock_id", "date"]), d[-1])
    assert h["above_ma20_pct"] == pytest.approx(1 / 3)     # 只有 A 在 MA20 之上
    assert (h["limit_up"], h["limit_down"]) == (1, 1)
    assert h["fail_rate"] is None and h["fail_n"] == 0       # 沒有訊號 → 樣本不足


def test_fail_rate_uses_prior_ten_days_signals():
    f, d = _feat()
    sig = pd.DataFrame({"stock_id": ["A"] * 3 + ["B"] * 3, "date": list(d[15:18]) * 2})
    h = market_header(f, sig, d[-1])
    assert h["fail_n"] == 6 and h["fail_rate"] == pytest.approx(0.5)   # B 一路跌、A 一路漲
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_recommend_market.py -v`，Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/market.py
"""推薦頁頁首的大盤資訊（規格 C18）：只顯示，不擋訊號（13.12）。"""
import pandas as pd

from recommend.exits import STOP
from recommend.ticks import limit_down_price

FAIL_LOOKBACK = 10
FAIL_MIN_N = 5


def market_header(features: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp) -> dict:
    f = features.sort_values(["stock_id", "date"])
    ma20 = f.groupby("stock_id")["close"].transform(lambda s: s.rolling(20).mean())
    today = f[f["date"] == day].assign(ma20=ma20[f["date"] == day])
    pool = today[today["liq"]]
    ref = today["close"] - today["change"].fillna(0)
    down = today["close"] <= ref.map(lambda r: limit_down_price(r) if r > 0 else -1) + 1e-6
    fail_rate, fail_n = _fail_rate(f, signals, day)
    return {
        "above_ma20_pct": float((pool["close"] > pool["ma20"]).mean()) if len(pool) else None,
        "limit_up": int(today["limit_up"].sum()),
        "limit_down": int(down.sum()),
        "fail_rate": fail_rate,
        "fail_n": fail_n,
    }


def _fail_rate(f: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp) -> tuple:
    days = sorted(f.loc[f["date"] < day, "date"].unique())[-FAIL_LOOKBACK:]
    sig = signals[signals["date"].isin(days)]
    fails = []
    for s in sig.itertuples(index=False):
        p = f[(f["stock_id"] == s.stock_id) & (f["date"] > s.date) & (f["date"] <= day)]
        if p.empty:
            continue
        entry = p["open"].iloc[0]
        fails.append(bool((p["close"] <= entry * (1 - STOP)).any()))
    if len(fails) < FAIL_MIN_N:
        return None, len(fails)
    return sum(fails) / len(fails), len(fails)
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_recommend_market.py -v`，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/market.py tests/test_recommend_market.py
git commit -m "feat(recommend): 頁首大盤數字（MA20 比例、漲跌停家數、突破失敗率）"
```

---

### Task 3: 卡片欄位與提醒

**Files:**
- Create: `recommend/cards.py`
- Test: `tests/test_recommend_cards.py`

`build_cards(features, signals, day, rally_pct=None)`：每筆訊號一張卡，欄位 `stock_id, stock_name, meta_sector, strategy, type, routes, n_routes, signal_date, signal_close, close, change_pct, since_signal_pct, bias10, below_ma60, alerts, status`。
- `bias10 = 收盤 ÷ 含當天 MA10 − 1`；`alerts` 依序加入「乖離大」（bias10 ≥ 0.30）、「季線下」（收盤 < MA60）、「已漲多」（rally_pct 不是 None 且 since_signal_pct ≥ rally_pct）。
- `status`：現價 ≤ 推薦日收盤 × 0.94 →「失效」，否則「有效」。
- `group_by_sector(cards)` → `[{"sector", "count", "cards"}]`，依 count 由多到少、同數依族群名稱。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_cards.py
import pandas as pd

from recommend.cards import build_cards, group_by_sector


def _feat(closes, sid="6672", sector="銅箔基板"):
    d = pd.bdate_range("2026-06-01", periods=len(closes))
    return pd.DataFrame({"stock_id": sid, "stock_name": "名稱", "meta_sector": sector, "date": d,
                         "close": closes, "change": [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]})


def _sig(sid, day):
    return pd.DataFrame([{"stock_id": sid, "date": day, "strategy": "突破策略", "type": "整理",
                          "routes": "法人,外資", "n_routes": 2}])


def test_card_alerts_bias_and_below_ma60():
    closes = [200.0] * 60 + [100.0] * 9 + [140.0]           # MA10=104 → 乖離 34.6%；MA60 遠高於 140
    f = _feat(closes)
    day = f["date"].iloc[-1]
    c = build_cards(f, _sig("6672", day), day)[0]
    assert c["alerts"] == ["乖離大", "季線下"]
    assert c["status"] == "有效" and c["since_signal_pct"] == 0.0


def test_card_status_invalid_after_six_percent_drop_and_rally_alert():
    f = _feat([100.0] * 70 + [110.0, 103.0])
    sig_day, today = f["date"].iloc[-2], f["date"].iloc[-1]
    c = build_cards(f, _sig("6672", sig_day), today)[0]
    assert c["status"] == "失效"                                   # 103 ≤ 110 × 0.94
    f2 = _feat([100.0] * 70 + [110.0, 125.0])
    c2 = build_cards(f2, _sig("6672", sig_day), today, rally_pct=0.10)[0]
    assert "已漲多" in c2["alerts"] and c2["status"] == "有效"


def test_group_by_sector_orders_by_count():
    cards = [{"meta_sector": "散熱"}, {"meta_sector": "銅箔基板"}, {"meta_sector": "銅箔基板"}]
    g = group_by_sector(cards)
    assert [(x["sector"], x["count"]) for x in g] == [("銅箔基板", 2), ("散熱", 1)]
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_recommend_cards.py -v`，Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/cards.py
"""推薦卡片欄位與提醒（規格 C16、C18）：提醒只顯示、不擋訊號。"""
import pandas as pd

from recommend.exits import STOP

BIAS_HOT = 0.30   # MA10 乖離 ≥ 30% 顯示「乖離大」（13.10：當規則會變差，只提醒）


def build_cards(features: pd.DataFrame, signals: pd.DataFrame, day: pd.Timestamp, rally_pct: float | None = None) -> list:
    f = features.sort_values(["stock_id", "date"])
    g = f.groupby("stock_id")["close"]
    f = f.assign(ma10=g.transform(lambda s: s.rolling(10).mean()), ma60=g.transform(lambda s: s.rolling(60).mean()))
    today = f[f["date"] == day].set_index("stock_id")
    closes = f.set_index(["stock_id", "date"])["close"]
    cards = []
    for s in signals.itertuples(index=False):
        if s.stock_id not in today.index:
            continue
        t = today.loc[s.stock_id]
        sig_close = float(closes.loc[(s.stock_id, s.date)])
        close = float(t["close"])
        since = close / sig_close - 1
        bias10 = close / t["ma10"] - 1 if pd.notna(t["ma10"]) else None
        below60 = bool(pd.notna(t["ma60"]) and close < t["ma60"])
        alerts = []
        if bias10 is not None and bias10 >= BIAS_HOT:
            alerts.append("乖離大")
        if below60:
            alerts.append("季線下")
        if rally_pct is not None and since >= rally_pct:
            alerts.append("已漲多")
        prev = close - (t["change"] if pd.notna(t["change"]) else 0)
        cards.append({
            "stock_id": s.stock_id, "stock_name": t["stock_name"], "meta_sector": t["meta_sector"],
            "strategy": s.strategy, "type": s.type, "routes": s.routes, "n_routes": int(s.n_routes),
            "signal_date": pd.Timestamp(s.date).date().isoformat(), "signal_close": sig_close,
            "close": close, "change_pct": round((close / prev - 1) * 100, 2) if prev else None,
            "since_signal_pct": round(since * 100, 2), "bias10": None if bias10 is None else round(bias10 * 100, 1),
            "below_ma60": below60, "alerts": alerts,
            "status": "失效" if close <= sig_close * (1 - STOP) else "有效",
        })
    return cards


def group_by_sector(cards: list) -> list:
    groups: dict = {}
    for c in cards:
        groups.setdefault(c["meta_sector"], []).append(c)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"sector": k, "count": len(v), "cards": v} for k, v in ordered]
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_recommend_cards.py -v`，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/cards.py tests/test_recommend_cards.py
git commit -m "feat(recommend): 推薦卡片欄位與提醒（乖離大、季線下、已漲多、失效）"
```

---

### Task 4: 成績單（DuckDB `recommendations` 表）

**Files:**
- Create: `recommend/scorecard.py`
- Test: `tests/test_recommend_scorecard.py`

表結構：`strategy, stock_id, signal_date, type, routes, n_routes, signal_close, entry_date, entry_price, exit_date, exit_price, exit_reason, ret, r_multiple, mfe, hold_days, updated_at`，PK `(strategy, stock_id, signal_date)`。
- `record_signals(con, signals, features)`：新訊號寫入（已存在不重寫），`signal_close` 取當天收盤。
- `refresh(con, features)`：`exit_reason` 是 NULL、「持有中」或「買不到?」的列，用 `simulate_trade` 重算（隔天一字漲停 → `exit_reason='買不到'`，之後不再算）。
- `summary(con, strategy)`：已出場（排除持有中、買不到）的 `n, open_n, win_rate, payoff, pf, mean_r`，以及 `by_type`、`by_month`（list of dict）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_scorecard.py
import duckdb
import pandas as pd

from recommend.scorecard import ensure_table, record_signals, refresh, summary


def _feat(closes, one_word=None):
    d = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"stock_id": "6672", "date": d, "open": closes, "close": closes,
                         "one_word": one_word or [False] * len(closes)})


def _sig(day):
    return pd.DataFrame([{"stock_id": "6672", "date": day, "strategy": "突破策略", "type": "整理",
                          "routes": "法人", "n_routes": 1}])


def test_record_refresh_and_summary_track_until_exit():
    con = duckdb.connect(":memory:")
    ensure_table(con)
    f = _feat([100.0, 100.0, 102.0])
    record_signals(con, _sig(f["date"][0]), f)
    record_signals(con, _sig(f["date"][0]), f)                       # 重複寫入不會多一列
    refresh(con, f)
    row = con.execute("SELECT signal_close, entry_price, exit_reason FROM recommendations").fetchone()
    assert row == (100.0, 100.0, "持有中")
    f2 = _feat([100.0, 100.0, 102.0, 93.0])                          # 隔天資料進來 → 停損
    refresh(con, f2)
    assert con.execute("SELECT exit_reason FROM recommendations").fetchone()[0] == "停損"
    s = summary(con, "突破策略")
    assert s["n"] == 1 and s["open_n"] == 0 and s["win_rate"] == 0.0


def test_unfillable_next_day_one_word_marked_and_excluded():
    con = duckdb.connect(":memory:")
    ensure_table(con)
    f = _feat([100.0, 110.0, 111.0], one_word=[False, True, False])
    record_signals(con, _sig(f["date"][0]), f)
    refresh(con, f)
    assert con.execute("SELECT exit_reason FROM recommendations").fetchone()[0] == "買不到"
    assert summary(con, "突破策略")["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_recommend_scorecard.py -v`，Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/scorecard.py
"""推薦成績單（規格 E22）：每筆推薦依規則追蹤到出場，跟回測期望值並列比較。"""
from datetime import datetime

import pandas as pd

from recommend.backtest import _core
from recommend.exits import simulate_trade

_DDL = """
CREATE TABLE IF NOT EXISTS recommendations (
    strategy VARCHAR, stock_id VARCHAR, signal_date DATE, type VARCHAR, routes VARCHAR, n_routes INTEGER,
    signal_close DOUBLE, entry_date DATE, entry_price DOUBLE, exit_date DATE, exit_price DOUBLE,
    exit_reason VARCHAR, ret DOUBLE, r_multiple DOUBLE, mfe DOUBLE, hold_days INTEGER, updated_at TIMESTAMP,
    PRIMARY KEY (strategy, stock_id, signal_date)
)
"""
_CLOSED_SKIP = ("持有中", "買不到")


def ensure_table(con) -> None:
    con.execute(_DDL)


def record_signals(con, signals: pd.DataFrame, features: pd.DataFrame) -> int:
    closes = features.set_index(["stock_id", "date"])["close"]
    n = 0
    for s in signals.itertuples(index=False):
        if (s.stock_id, s.date) not in closes.index:
            continue
        before = con.execute("SELECT count(*) FROM recommendations WHERE strategy=? AND stock_id=? AND signal_date=?",
                             [s.strategy, s.stock_id, s.date]).fetchone()[0]
        if before:
            continue
        con.execute("INSERT INTO recommendations (strategy, stock_id, signal_date, type, routes, n_routes, signal_close, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [s.strategy, s.stock_id, s.date, s.type, s.routes, int(s.n_routes),
                     float(closes.loc[(s.stock_id, s.date)]), datetime.now()])
        n += 1
    return n


def refresh(con, features: pd.DataFrame) -> int:
    open_rows = con.execute("SELECT strategy, stock_id, signal_date FROM recommendations "
                            "WHERE exit_reason IS NULL OR exit_reason = '持有中'").df()
    paths = {sid: g.reset_index(drop=True) for sid, g in
             features[["stock_id", "date", "open", "close", "one_word"]].sort_values("date").groupby("stock_id")}
    for r in open_rows.itertuples(index=False):
        path = paths.get(r.stock_id)
        if path is None:
            continue
        pos = path.index[path["date"] == pd.Timestamp(r.signal_date)]
        if len(pos) == 0 or pos[0] + 1 >= len(path):
            continue                                   # 還沒有隔天的資料
        t = simulate_trade(path, int(pos[0]))
        key = [r.strategy, r.stock_id, r.signal_date]
        if t is None:
            con.execute("UPDATE recommendations SET exit_reason='買不到', updated_at=? "
                        "WHERE strategy=? AND stock_id=? AND signal_date=?", [datetime.now(), *key])
            continue
        con.execute("UPDATE recommendations SET entry_date=?, entry_price=?, exit_date=?, exit_price=?, exit_reason=?, "
                    "ret=?, r_multiple=?, mfe=?, hold_days=?, updated_at=? WHERE strategy=? AND stock_id=? AND signal_date=?",
                    [t["entry_date"], t["entry_price"], t["exit_date"], t["exit_price"], t["exit_reason"], t["ret"],
                     t["r_multiple"], t["mfe"], t["hold_days"], datetime.now(), *key])
    return len(open_rows)


def summary(con, strategy: str) -> dict:
    df = con.execute("SELECT * FROM recommendations WHERE strategy = ?", [strategy]).df()
    closed = df[df["exit_reason"].notna() & ~df["exit_reason"].isin(_CLOSED_SKIP)]
    out = _core(closed)
    out["open_n"] = int((df["exit_reason"] == "持有中").sum())
    closed = closed.assign(month=pd.to_datetime(closed["signal_date"]).dt.strftime("%Y-%m"))
    out["by_type"] = [{"type": k, **_core(g)} for k, g in closed.groupby("type")]
    out["by_month"] = [{"month": k, **_core(g)} for k, g in closed.groupby("month")]
    return out
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_recommend_scorecard.py -v`，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/scorecard.py tests/test_recommend_scorecard.py
git commit -m "feat(recommend): 成績單 recommendations 表（寫入、每日重算出場、總覽）"
```

---

### Task 5: 每日 payload

**Files:**
- Create: `recommend/daily.py`
- Test: `tests/test_recommend_daily.py`

`build_payload(features, day, keep_days=3, rally_pct=None)`（純函式，給測試與頁面用）：
- 每條策略 `scan` → 訊號；`day` 往前 `keep_days` 個交易日（含 `day`）內的訊號做卡片。
- 卡片加 `day_n`（推薦後第幾天，推薦當天＝1）。
- 回傳 `{"trade_date", "header", "new": group_by_sector(當天、有效), "active": 第 2～3 天有效的卡, "invalid": 失效的卡, "signals": 全部訊號 DataFrame}`。

`run_daily(day=None, db_path=..., keep_days=3)`：用 `load_panel(start=day − 400 日曆天)`（含預熱期）＋特徵＋`build_payload`；寫成績單（同一個 DB、讀寫連線）；回傳 JSON 可序列化的 payload（去掉 `signals`，加上 `scorecard`：每條策略的 `summary()`）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_daily.py
import pandas as pd

from recommend.daily import build_payload


class _FakeStrategy:
    name = "測試策略"

    def __init__(self, hits):
        self.hits = hits

    def scan(self, features):
        rows = [{"stock_id": sid, "date": d, "strategy": self.name, "type": "整理", "routes": "法人", "n_routes": 1}
                for sid, d in self.hits]
        return pd.DataFrame(rows, columns=["stock_id", "date", "strategy", "type", "routes", "n_routes"])


def _feat():
    d = pd.bdate_range("2026-01-01", periods=70)
    rows = []
    for sid, sector, tail in (("A", "銅箔基板", [100, 101, 102]), ("B", "散熱", [100, 90, 90]), ("C", "銅箔基板", [100, 100, 100])):
        closes = [100.0] * 67 + [float(x) for x in tail]
        for dt, c in zip(d, closes):
            rows.append({"stock_id": sid, "stock_name": sid, "meta_sector": sector, "date": dt, "open": c, "close": c,
                         "change": 0.0, "limit_up": False, "liq": True, "one_word": False})
    return pd.DataFrame(rows), d


def test_build_payload_splits_new_active_invalid(monkeypatch):
    f, d = _feat()
    strat = _FakeStrategy([("C", d[-1]), ("A", d[-3]), ("B", d[-3]), ("A", d[-10])])
    monkeypatch.setattr("recommend.daily.ALL_STRATEGIES", [strat])
    p = build_payload(f, d[-1])
    assert [(g["sector"], g["count"]) for g in p["new"]] == [("銅箔基板", 1)]
    assert [(c["stock_id"], c["day_n"]) for c in p["active"]] == [("A", 3)]
    assert [c["stock_id"] for c in p["invalid"]] == ["B"]           # 100 → 90 失效
    assert set(p["header"]) >= {"above_ma20_pct", "limit_up", "limit_down", "fail_rate"}
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_recommend_daily.py -v`，Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/daily.py
"""每日推薦：跑所有策略、記成績單、組推薦頁／Telegram 用的 payload（規格 §10）。"""
import duckdb
import pandas as pd

from recommend.cards import build_cards, group_by_sector
from recommend.data import DB_PATH, load_panel
from recommend.features import add_chip_features, add_price_features
from recommend.market import market_header
from recommend.scorecard import ensure_table, record_signals, refresh, summary
from recommend.strategies import ALL_STRATEGIES

KEEP_DAYS = 3        # C16：推薦在頁面保留 3 個交易日
WARMUP_DAYS = 400    # 日曆天；hi90、MA60、籌碼視窗的預熱


def build_payload(features: pd.DataFrame, day: pd.Timestamp, keep_days: int = KEEP_DAYS, rally_pct=None) -> dict:
    day = pd.Timestamp(day)
    trade_days = sorted(features.loc[features["date"] <= day, "date"].unique())
    window = trade_days[-keep_days:]
    day_n = {pd.Timestamp(d): len(window) - i for i, d in enumerate(window)}
    signals = pd.concat([s.scan(features) for s in ALL_STRATEGIES], ignore_index=True)
    recent = signals[signals["date"].isin(window)]
    cards = build_cards(features, recent, day, rally_pct=rally_pct)
    for c in cards:
        c["day_n"] = day_n[pd.Timestamp(c["signal_date"])]
    valid = [c for c in cards if c["status"] == "有效"]
    return {
        "trade_date": day.date().isoformat(),
        "header": market_header(features, signals, day),
        "new": group_by_sector([c for c in valid if c["day_n"] == 1]),
        "active": sorted([c for c in valid if c["day_n"] > 1], key=lambda c: (c["day_n"], c["stock_id"])),
        "invalid": [c for c in cards if c["status"] == "失效"],
        "signals": signals,
    }


def run_daily(day=None, db_path: str = DB_PATH, keep_days: int = KEEP_DAYS) -> dict:
    start = None
    if day is not None:
        start = (pd.Timestamp(day) - pd.Timedelta(days=WARMUP_DAYS)).date().isoformat()
    feats = add_chip_features(add_price_features(load_panel(db_path=db_path, start=start)))
    day = pd.Timestamp(day) if day is not None else feats["date"].max()
    payload = build_payload(feats, day, keep_days)
    con = duckdb.connect(db_path)
    try:
        ensure_table(con)
        today_sig = payload["signals"][payload["signals"]["date"] == day]
        record_signals(con, today_sig, feats)
        refresh(con, feats)
        payload["scorecard"] = {s.name: summary(con, s.name) for s in ALL_STRATEGIES}
    finally:
        con.close()
    payload.pop("signals")
    return payload
```

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_recommend_daily.py -v`，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/daily.py tests/test_recommend_daily.py
git commit -m "feat(recommend): 每日 payload（新訊號／有效中／失效、頁首、成績單）"
```

---

### Task 6: Telegram 表格訊息（E21）

**Files:**
- Create: `recommend/telegram_format.py`
- Modify: `notifications/telegram.py`（`send_telegram_message` 加 `parse_mode=None`）
- Test: `tests/test_recommend_telegram.py`、`tests/test_telegram_notifier.py`（追加）

格式（E21）：標題「個股推薦 MM/DD 收盤」→ 一行大盤 → `<pre>` 表格（股號 型態 條 收盤 漲幅 提醒 名稱；`[族群 N檔]` 分組；中文放最後）→「新 N 檔｜有效中 N 檔｜失效 N 檔」→ 連結。超過 15 檔寫「另 N 檔見頁面」。全部內容做 HTML 跳脫。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend_telegram.py
from recommend.telegram_format import compose_recommend_message


def _card(sid, sector, alerts=()):
    return {"stock_id": sid, "stock_name": "名<稱>", "meta_sector": sector, "type": "整理", "n_routes": 3,
            "close": 337.5, "change_pct": 10.0, "alerts": list(alerts)}


def _payload(n_new):
    cards = [_card(f"{1000 + k}", "銅箔基板" if k < 2 else "散熱", ["乖離大"] if k == 2 else []) for k in range(n_new)]
    groups = [{"sector": "銅箔基板", "count": 2, "cards": cards[:2]}, {"sector": "散熱", "count": n_new - 2, "cards": cards[2:]}]
    return {"trade_date": "2026-10-22",
            "header": {"above_ma20_pct": 0.61, "fail_rate": 0.33, "limit_up": 18, "limit_down": 3},
            "new": groups, "active": [{}] * 4, "invalid": [{}] * 2}


def test_message_has_table_groups_and_escaping():
    msg = compose_recommend_message(_payload(3), taiex_above_ma20=True, site_url="https://x/recommend.html")
    assert msg.startswith("個股推薦 10/22 收盤")
    assert "MA20上 61%｜失敗率 33%｜加權&gt;MA20｜漲停 18 跌停 3" in msg
    assert "<pre>" in msg and "[銅箔基板 2檔]" in msg and "[散熱 1檔]" in msg
    assert "乖離大" in msg and "名&lt;稱&gt;" in msg
    assert "新 3 檔｜有效中 4 檔｜失效 2 檔" in msg and msg.rstrip().endswith("https://x/recommend.html")
    assert "點火" not in msg


def test_message_truncates_after_fifteen():
    msg = compose_recommend_message(_payload(20), taiex_above_ma20=None, site_url="u")
    assert "另 5 檔見頁面" in msg and "加權" not in msg
```

```python
# 追加到 tests/test_telegram_notifier.py
def test_send_passes_parse_mode_when_given(monkeypatch):
    from unittest.mock import MagicMock
    import notifications.telegram as tg
    post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(tg.requests, "post", post)
    assert tg.send_telegram_message("<pre>x</pre>", token="t", chat_id="c", parse_mode="HTML")
    assert post.call_args.kwargs["data"]["parse_mode"] == "HTML"
    tg.send_telegram_message("x", token="t", chat_id="c")
    assert "parse_mode" not in post.call_args.kwargs["data"]
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_recommend_telegram.py tests/test_telegram_notifier.py -v`，Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# recommend/telegram_format.py
"""Telegram 推薦訊息（規格 E21）：精簡、不用 emoji、等寬表格、中文放每列最後。"""
from html import escape

MAX_ROWS = 15


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def compose_recommend_message(payload: dict, taiex_above_ma20: bool | None, site_url: str) -> str:
    d = payload["trade_date"]
    h = payload["header"]
    market = [f"MA20上 {_pct(h.get('above_ma20_pct'))}", f"失敗率 {_pct(h.get('fail_rate'))}"]
    if taiex_above_ma20 is not None:
        market.append("加權>MA20" if taiex_above_ma20 else "加權<MA20")
    market.append(f"漲停 {h.get('limit_up', 0)} 跌停 {h.get('limit_down', 0)}")
    lines = [f"股號   型態 條  收盤     漲幅    提醒     名稱", "-" * 46]
    shown = total = 0
    for g in payload["new"]:
        total += g["count"]
        if shown >= MAX_ROWS:
            continue
        lines.append(f"[{g['sector']} {g['count']}檔]")
        for c in g["cards"]:
            if shown >= MAX_ROWS:
                break
            alert = "、".join(c["alerts"])
            lines.append(f"{c['stock_id']:<6} {c['type']} {c['n_routes']:>2} {c['close']:>8.1f} "
                         f"{c['change_pct']:>+6.1f}%  {alert:<6} {c['stock_name']}")
            shown += 1
    lines.append("-" * 46)
    if total > shown:
        lines.append(f"另 {total - shown} 檔見頁面")
    table = escape("\n".join(lines))
    head = escape(f"個股推薦 {d[5:7]}/{d[8:10]} 收盤\n{'｜'.join(market)}")
    tail = escape(f"新 {total} 檔｜有效中 {len(payload['active'])} 檔｜失效 {len(payload['invalid'])} 檔\n{site_url}")
    return f"{head}\n\n<pre>{table}</pre>\n{tail}"
```

`notifications/telegram.py` 改 `send_telegram_message` 簽名與 POST：

```python
def send_telegram_message(
    text: str, token: str | None = None, chat_id: str | None = None, parse_mode: str | None = None
) -> bool:
    ...
            data = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                data["parse_mode"] = parse_mode
            resp = requests.post(url, data=data, timeout=_TIMEOUT_SECONDS)
```

> ⚠️ `_split_message` 可能把 `<pre>` 切開；推薦訊息最多 15 列約 1,500 字，不會超過 4,000 上限。測試 `test_message_truncates_after_fifteen` 間接保證長度。

- [ ] **Step 4: Run test to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommend/telegram_format.py notifications/telegram.py tests/test_recommend_telegram.py tests/test_telegram_notifier.py
git commit -m "feat(recommend): Telegram 推薦表格訊息（E21）；send_telegram_message 支援 parse_mode"
```

---

### Task 7: 接進收盤流程與排程通知

**Files:**
- Modify: `main.py`（`run()`：籌碼寫入後、step 7 之前呼叫；`_build_run_summary` 加 `recommend`）
- Modify: `scripts/run_scheduled.py`（close 模式多發一則）
- Test: `tests/test_main.py`、`tests/test_scheduled_runner.py`（追加）

規則：
- 只在收盤模式跑（`realtime=False`）；失敗只記 warning（「個股推薦產生失敗」），不擋其他流程。
- payload 存 `data/recommend_payload.json`（給之後的推薦頁用）。
- summary 加 `recommend`：`{"new": [...卡片...], "header", "active_n", "invalid_n", "trade_date"}`。
- `taiex_above_ma20`：step 7 已抓的 `taiex_history` 最後 20 筆算 MA20；推薦在 step 7 之前跑，所以在 summary 組好時才補進去（`summary["recommend"]["taiex_above_ma20"]`）。
- 排程 close：`summary.get("recommend")` 有值且 `new` 不空才發，`parse_mode="HTML"`；連結＝`SITE_URL` + `recommend.html`。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_main.py
def test_build_run_summary_includes_recommend_only_in_close_mode():
    started = datetime(2026, 10, 22, 15, 0, 0)
    finished = datetime(2026, 10, 22, 15, 5, 0)
    rec = {"trade_date": "2026-10-22", "new": [], "header": {}, "active": [], "invalid": []}
    common = dict(trade_date=date(2026, 10, 22), market_regime=None, margin_div={}, flow_watch=[],
                  html_updated=True, git_pushed=True, started_at=started, finished_at=finished, warnings=[])
    assert _build_run_summary(realtime=False, recommend=rec, **common)["recommend"]["trade_date"] == "2026-10-22"
    assert "recommend" not in _build_run_summary(realtime=True, recommend=rec, **common)


def test_run_calls_recommend_daily_in_close_mode():
    source = inspect.getsource(run)
    assert "_update_recommend(" in source
```

```python
# 追加到 tests/test_scheduled_runner.py
def test_close_sends_recommend_message_when_new_signals(monkeypatch):
    import scripts.run_scheduled as rs
    sent = []
    monkeypatch.setattr(rs, "send_telegram_message", lambda text, **kw: sent.append((text, kw)) or True)
    rec = {"trade_date": "2026-10-22", "header": {}, "new": [{"sector": "散熱", "count": 1, "cards": [
        {"stock_id": "3017", "stock_name": "奇鋐", "type": "續攻", "n_routes": 2, "close": 1.0, "change_pct": 9.9, "alerts": []}]}],
        "active": [], "invalid": [], "taiex_above_ma20": True}
    rs.send_recommend_message({"recommend": rec}, "https://x/")
    assert sent and sent[0][1]["parse_mode"] == "HTML" and "https://x/recommend.html" in sent[0][0]
    sent.clear()
    rs.send_recommend_message({"recommend": {**rec, "new": []}}, "https://x/")
    assert not sent
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_main.py tests/test_scheduled_runner.py -v`，Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`main.py`：

```python
RECOMMEND_PAYLOAD_PATH = Path("data/recommend_payload.json")


def _update_recommend(realtime: bool, trade_date: date, warnings: list | None = None) -> dict | None:
    """收盤後跑個股推薦（規格 §10）：策略訊號、成績單、payload。盤中不跑；失敗不擋其他流程。"""
    if realtime:
        return None
    try:
        from recommend.daily import run_daily
        payload = run_daily(day=trade_date)
        RECOMMEND_PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECOMMEND_PAYLOAD_PATH.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        logger.info("個股推薦：新訊號 %d 檔，有效中 %d、失效 %d",
                    sum(g["count"] for g in payload["new"]), len(payload["active"]), len(payload["invalid"]))
        return payload
    except Exception as exc:
        logger.warning("個股推薦產生失敗（不影響其他產出）：%s", exc)
        if warnings is not None:
            warnings.append("個股推薦產生失敗")
        return None
```

在 `run()` 的 `# 6.3 官方基本面` 那段之後加：

```python
    # 6.4 個股推薦（收盤模式）：籌碼已寫入 DB 才跑
    recommend_payload = _update_recommend(realtime, trade_date, warnings=_run_warnings)
```

`run()` 開頭預設值區（`market_regime = None` 那幾行）加 `recommend_payload = None`；step 7 抓到 `taiex_history` 後補：

```python
            if recommend_payload is not None and len(taiex_history) >= 20:
                closes = [r["close"] for r in taiex_history[-20:]]
                recommend_payload["taiex_above_ma20"] = closes[-1] > sum(closes) / 20
```

`_build_run_summary` 加參數 `recommend: dict | None = None`，在 `if not realtime:` 區塊內：

```python
        if recommend is not None:
            summary["recommend"] = recommend
```

呼叫端加 `recommend=recommend_payload`。

`scripts/run_scheduled.py`：

```python
from recommend.telegram_format import compose_recommend_message  # noqa: E402  （放在既有 notifications import 下）


def send_recommend_message(summary: dict, site_url: str) -> None:
    """收盤後的個股推薦表格（規格 E21）；沒有新訊號就不發。"""
    rec = summary.get("recommend")
    if not rec or not rec.get("new"):
        return
    url = site_url.rstrip("/") + "/recommend.html"
    send_telegram_message(compose_recommend_message(rec, rec.get("taiex_above_ma20"), url), parse_mode="HTML")
```

close 分支 `send_telegram_message(compose_close_message(summary, site_url))` 之後加 `send_recommend_message(summary, site_url)`（同一個 try 內）。

- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_main.py tests/test_scheduled_runner.py -v` 與全套，Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py scripts/run_scheduled.py tests/test_main.py tests/test_scheduled_runner.py
git commit -m "feat(recommend): 收盤流程產生個股推薦與 Telegram 表格通知"
```

---

### Task 8: 交接

- [ ] **Step 1: Append `debug-tasks.md`**

```markdown
## [YYYY-MM-DD] 個股推薦階段 4：每日後端（訊號、成績單、Telegram）

### 改了什麼
- 計畫：docs/superpowers/plans/2026-10-24-recommend-daily-backend.md
- 新增 recommend/market.py、cards.py、scorecard.py、daily.py、telegram_format.py；ticks 加跌停價
- main.py 收盤模式 `_update_recommend()`（step 6.4），summary 加 recommend；排程 close 多發一則（parse_mode=HTML）
- DB 新表 recommendations（第一次跑自動建立）

### 請 Debugger 驗證
- [ ] 新測試與全套
- [ ] 官方行情重建後，唯讀複製 DB 跑一次 `recommend.daily.run_daily(day='2026-09-24', db_path=<複本>)`：
      payload 的 new 含 6672、6213；header 數字合理；成績單有列
- [ ] `compose_recommend_message` 實際長度、對齊（發到測試 chat 或印出來）
- [ ] 收盤流程失敗時只記 warning，不影響 push
```

- [ ] **Step 2: Commit、ff debug、SendMessage**
