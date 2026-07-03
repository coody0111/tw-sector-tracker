# 族群總覽頁前端重新設計 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `docs/index.html`（族群總覽頁）從 Python 直接產生的靜態 HTML，改成 Python 產生 `docs/data.json` + React/Vite 建置的前端頁面，採響應式雙模式排版（桌機固定明細面板／手機 inline 展開）。

**Architecture:** Python 端新增 `export/data_generator.py`，把既有已算好的族群/個股/訊號資料（含新的週排名邏輯）序列化成 `docs/data.json`。前端是全新的 `frontend/` Vite + React + TypeScript 專案，執行期用 `fetch('./data.json')` 讀資料（不是 build-time 靜態 import），所以每天資料更新只需要 `python main.py`（覆寫 `data.json`）就好，不用重新 `npm run build`；只有改前端程式碼時才需要重建。

**Tech Stack:** Python（既有）、React 18 + TypeScript + Vite、Vitest + @testing-library/react（前端測試）、pytest（既有）

---

## 檔案結構總覽

**Python 端（新增/修改）：**
- 修改：`processors/performance.py` — 新增 `calc_weekly_rank()`
- 新增：`export/data_generator.py` — 產生 `docs/data.json`
- 新增：`tests/test_data_generator.py`
- 修改：`main.py` — 把呼叫 `generate_html(...)` 換成呼叫新的 data generator；`_push_html()` 加入 `docs/data.json`、`docs/assets`

**前端（全新 `frontend/` 目錄）：**
- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`
- `frontend/index.html`（Vite entry，跟輸出到 `docs/index.html` 是不同檔案）
- `frontend/src/types.ts` — 對應 `data.json` 的 TypeScript 型別
- `frontend/src/lib/sort.ts` + `frontend/src/lib/sort.test.ts` — 排行榜排序純函式
- `frontend/src/lib/group.ts` + `frontend/src/lib/group.test.ts` — 子族群分組純函式
- `frontend/src/hooks/useSectorData.ts` — fetch `data.json`
- `frontend/src/hooks/useMediaQuery.ts` — RWD 斷點判斷
- `frontend/src/components/SignalChips.tsx`
- `frontend/src/components/RankList.tsx`
- `frontend/src/components/SectorDetail.tsx`
- `frontend/src/components/StockModal.tsx`
- `frontend/src/components/SearchBar.tsx`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`

---

### Task 1: `calc_weekly_rank()` — 週排名滾動比較邏輯

**Files:**
- Modify: `processors/performance.py`
- Test: `tests/test_processors.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_processors.py`:

```python
import duckdb
from processors.performance import calc_weekly_rank

def _seed_daily_prices(db_path, rows):
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE daily_prices (
            stock_id VARCHAR, date DATE, change_pct DOUBLE,
            close DOUBLE, volume BIGINT, change DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO daily_prices (stock_id, date, change_pct) VALUES (?, ?, ?)",
        rows,
    )
    con.close()

def test_calc_weekly_rank_compares_rolling_5day_windows(tmp_path):
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame(
        [["2330", "A"], ["2317", "B"]],
        columns=["stock_id", "meta_sector"],
    )
    dates = [
        "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    ]
    rows = []
    for i, d in enumerate(dates):
        pct_a = 0.1 if i < 5 else 2.0   # A：上週平淡，這週強
        pct_b = 1.0 if i < 5 else 0.1   # B：上週強，這週平淡
        rows.append(("2330", d, pct_a))
        rows.append(("2317", d, pct_b))
    _seed_daily_prices(db_path, rows)

    result = calc_weekly_rank(universe, db_path=str(db_path))

    assert result["A"]["last_week_rank"] == 2
    assert result["A"]["this_week_rank"] == 1
    assert result["B"]["last_week_rank"] == 1
    assert result["B"]["this_week_rank"] == 2

def test_calc_weekly_rank_returns_empty_when_insufficient_history(tmp_path):
    db_path = tmp_path / "test.db"
    universe = pd.DataFrame([["2330", "A"]], columns=["stock_id", "meta_sector"])
    _seed_daily_prices(db_path, [("2330", "2026-06-26", 1.0)])
    result = calc_weekly_rank(universe, db_path=str(db_path))
    assert result == {}
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_processors.py -k weekly_rank -v`
Expected: FAIL with `ImportError: cannot import name 'calc_weekly_rank'`

- [x] **Step 3: Write minimal implementation**

Add to `processors/performance.py` (near `calc_meta_signals`, same imports already present: `duckdb`, `pandas as pd`, `Dict`, `Any`, `Optional`):

```python
def calc_weekly_rank(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Optional[int]]]:
    """
    比較「上週5日累積報酬排名」vs「本週至今5日累積報酬排名」（滾動比較）。
    今天往前 5 個交易日算一組累積報酬排名，再往前推 5 個交易日算另一組，
    兩組排名互相比較。跟 cum5（5日累積報酬%）概念一致，只是拿排名版本。
    回傳 {meta_name: {"this_week_rank": int|None, "last_week_rank": int|None}}
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        dates_df = con.execute(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 10"
        ).fetchdf()
        prices_df = con.execute(
            "SELECT stock_id, date, change_pct FROM daily_prices"
        ).fetchdf()
        con.close()
    except Exception:
        return {}

    if prices_df.empty or len(dates_df) < 10:
        return {}

    all_dates = sorted(dates_df["date"].tolist())
    universe = universe_df[["stock_id", "meta_sector"]].copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    prices_df["stock_id"] = prices_df["stock_id"].astype(str)

    merged = prices_df.merge(universe, on="stock_id", how="inner")
    merged = merged.dropna(subset=["change_pct", "meta_sector"])

    pivot = (
        merged.groupby(["meta_sector", "date"])["change_pct"].mean()
        .unstack(level="date")
        .reindex(columns=all_dates)
        .fillna(0)
    )

    def _cum_rank(cols) -> Dict[str, int]:
        cum: Dict[str, float] = {}
        for meta_name in pivot.index:
            row = pivot.loc[meta_name]
            f = 1.0
            for c in cols:
                f *= (1 + row[c] / 100)
            cum[meta_name] = (f - 1) * 100
        ranked = sorted(cum.items(), key=lambda x: -x[1])
        return {meta: i + 1 for i, (meta, _) in enumerate(ranked)}

    this_week_rank = _cum_rank(all_dates[-5:])
    last_week_rank = _cum_rank(all_dates[-10:-5])

    return {
        meta_name: {
            "this_week_rank": this_week_rank.get(meta_name),
            "last_week_rank": last_week_rank.get(meta_name),
        }
        for meta_name in pivot.index
    }
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_processors.py -k weekly_rank -v`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add processors/performance.py tests/test_processors.py
git commit -m "feat: add calc_weekly_rank() for rolling 5-day rank comparison"
```

---

### Task 2: `export/data_generator.py` — 產生 `docs/data.json`

**Files:**
- Create: `export/data_generator.py`
- Create: `tests/test_data_generator.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_data_generator.py`:

```python
import json
import pandas as pd
from datetime import date
from export.data_generator import generate

def test_generate_writes_expected_json_shape(tmp_path):
    output_path = tmp_path / "data.json"

    meta_perf = [{
        "meta_name": "先進封裝設備",
        "sub_names": ["半導體製程設備"],
        "avg_change_pct": 4.77,
        "up_count": 9,
        "down_count": 0,
        "flat_count": 0,
        "stock_ids": ["3583"],
    }]
    universe_df = pd.DataFrame([
        {"stock_id": "3583", "stock_name": "辛耘", "meta_sector": "先進封裝設備",
         "sub_sector": "半導體製程設備"},
    ])
    prices_df = pd.DataFrame([
        {"stock_id": "3583", "close": 905.0, "change_pct": 0.11, "volume": 3000},
    ])
    chips_df = pd.DataFrame([
        {"stock_id": "3583", "foreign_net": 336398, "trust_net": -82000,
         "margin_balance": 0, "margin_change": 0},
    ])
    cum_data = [{"meta_name": "先進封裝設備", "cum1": 0.1, "cum3": 12.0, "cum5": 10.9, "cum7": 9.4}]
    meta_signals = {"先進封裝設備": {
        "daily_pct": [0.1, 4.99], "dates": ["6/30", "7/1"],
        "streak": 3, "vol_ratio": 2.5, "yesterday_rank": 10,
    }}
    weekly_rank = {"先進封裝設備": {"this_week_rank": 1, "last_week_rank": 8}}
    stock_sparklines = {"3583": [0.1, 4.99, 4.99, 4.99, 4.99, 4.99]}

    generate(
        trade_date=date(2026, 7, 1),
        meta_perf=meta_perf,
        universe_df=universe_df,
        prices_df=prices_df,
        chips_df=chips_df,
        cum_data=cum_data,
        meta_signals=meta_signals,
        weekly_rank=weekly_rank,
        stock_sparklines=stock_sparklines,
        output_path=str(output_path),
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["date"] == "2026-07-01"
    assert data["market"]["up"] == 9
    meta = data["metaSectors"][0]
    assert meta["name"] == "先進封裝設備"
    assert meta["avgChangePct"] == 4.77
    assert meta["todayRank"] == 1
    assert meta["yesterdayRank"] == 10
    assert meta["thisWeekRank"] == 1
    assert meta["lastWeekRank"] == 8
    assert meta["streak"] == 3
    assert meta["volRatio"] == 2.5
    sub = meta["subGroups"][0]
    assert sub["name"] == "半導體製程設備"
    stock = sub["stocks"][0]
    assert stock["id"] == "3583"
    assert stock["close"] == 905.0
    assert stock["foreignNet"] == 336   # 股 → 張，除以 1000
    assert stock["trustNet"] == -82
    assert stock["sparkline"] == [0.1, 4.99, 4.99, 4.99, 4.99, 4.99]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'export.data_generator'`

- [x] **Step 3: Write minimal implementation**

Create `export/data_generator.py`:

```python
"""
產生 docs/data.json — 供前端 React app 執行期 fetch 讀取的族群總覽資料。
不產生 HTML；HTML 由 frontend/（Vite build）另外產生。
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd


def _weekly_pct(spark: list) -> float:
    """複利計算 sparkline 最後 5 個交易日的週漲跌幅。"""
    if not spark:
        return 0.0
    last5 = spark[-5:]
    result = 1.0
    for p in last5:
        result *= (1 + p / 100)
    return round((result - 1) * 100, 2)


def generate(
    trade_date: date,
    meta_perf: list,
    universe_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    chips_df: pd.DataFrame = None,
    cum_data: list = None,
    meta_signals: dict = None,
    weekly_rank: dict = None,
    stock_sparklines: dict = None,
    output_path: str = "docs/data.json",
) -> None:
    if not meta_perf:
        return

    universe = universe_df.copy()
    universe["stock_id"] = universe["stock_id"].astype(str)
    name_map = dict(zip(universe["stock_id"], universe["stock_name"]))
    sub_map = dict(zip(universe["stock_id"], universe["sub_sector"]))

    prices_map = (
        prices_df.assign(stock_id=prices_df["stock_id"].astype(str)).set_index("stock_id")
        if prices_df is not None and not prices_df.empty else pd.DataFrame()
    )
    chips_map = (
        chips_df.assign(stock_id=chips_df["stock_id"].astype(str)).set_index("stock_id")
        if chips_df is not None and not chips_df.empty else pd.DataFrame()
    )
    cum_map = {r["meta_name"]: r for r in (cum_data or [])}
    meta_signals = meta_signals or {}
    weekly_rank = weekly_rank or {}
    stock_sparklines = stock_sparklines or {}

    sorted_meta = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)

    total = sum(r["up_count"] + r["down_count"] + r["flat_count"] for r in meta_perf)
    up = sum(r["up_count"] for r in meta_perf)
    down = sum(r["down_count"] for r in meta_perf)
    flat = total - up - down
    mkt_avg = round(sum(r["avg_change_pct"] for r in meta_perf) / len(meta_perf), 2) if meta_perf else 0.0

    meta_sectors_json = []
    for today_rank, row in enumerate(sorted_meta, start=1):
        meta_name = row["meta_name"]
        cum = cum_map.get(meta_name, {})
        sig = meta_signals.get(meta_name, {})
        wr = weekly_rank.get(meta_name, {})

        sub_groups: dict = {}
        for sid in row.get("stock_ids", []):
            sid = str(sid)
            sub_name = sub_map.get(sid, "其他")
            stock_name = name_map.get(sid, "")

            close = pct = volume = None
            if sid in prices_map.index:
                p = prices_map.loc[sid]
                close = float(p["close"])
                pct = float(p["change_pct"])
                volume = int(p["volume"])

            fn = tn = mb = mc = 0
            if sid in chips_map.index:
                c = chips_map.loc[sid]
                fn = int(c.get("foreign_net") or 0) // 1000
                tn = int(c.get("trust_net") or 0) // 1000
                mb = int(c.get("margin_balance") or 0)
                mc = int(c.get("margin_change") or 0)

            spark = stock_sparklines.get(sid, [])

            sub_groups.setdefault(sub_name, []).append({
                "id": sid,
                "name": stock_name,
                "close": close,
                "changePct": pct,
                "volume": volume,
                "weeklyPct": _weekly_pct(spark),
                "foreignNet": fn,
                "trustNet": tn,
                "marginBalance": mb,
                "marginChange": mc,
                "sparkline": spark,
            })

        meta_sectors_json.append({
            "name": meta_name,
            "avgChangePct": row["avg_change_pct"],
            "upCount": row["up_count"],
            "downCount": row["down_count"],
            "cum3": cum.get("cum3"),
            "cum5": cum.get("cum5"),
            "cum7": cum.get("cum7"),
            "todayRank": today_rank,
            "yesterdayRank": sig.get("yesterday_rank"),
            "thisWeekRank": wr.get("this_week_rank"),
            "lastWeekRank": wr.get("last_week_rank"),
            "streak": sig.get("streak", 0),
            "volRatio": sig.get("vol_ratio"),
            "subGroups": [
                {"name": name, "stocks": stocks}
                for name, stocks in sub_groups.items()
            ],
        })

    payload = {
        "date": trade_date.isoformat(),
        "market": {"avgPct": mkt_avg, "up": up, "down": down, "flat": flat},
        "metaSectors": meta_sectors_json,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8")
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_generator.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add export/data_generator.py tests/test_data_generator.py
git commit -m "feat: add data_generator.py to produce docs/data.json"
```

---

### Task 3: 接上 `main.py`

**Files:**
- Modify: `main.py:9-22` (imports), `main.py:392-403` (generate_html call site), `main.py:101-116` (`_push_html`)

- [x] **Step 1: Modify imports**

In `main.py`, near the existing generator imports:

```python
from export.html_generator import generate as generate_html
from export.chips_generator import generate as generate_chips_html
```

Add:

```python
from export.data_generator import generate as generate_data_json
from processors.performance import calc_weekly_rank
```

(`calc_weekly_rank` should already be importable from the same `processors.performance` import line that already lists `calc_sector_performance, calc_meta_performance, ...` — add `calc_weekly_rank` to that list instead of a separate import line.)

- [x] **Step 2: Replace the generate_html call site**

Find the block (originally `main.py:392-403`):

```python
        generate_html(trade_date, pd.DataFrame(perf) if perf else pd.DataFrame(),
                      sectors_df=sectors_df,
                      prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                      chips_df=chips_df,
                      meta_perf=meta_perf,
                      universe_df=universe_df,
                      cum_data=cum_data,
                      meta_signals=meta_signals,
                      meta_chips=meta_chips,
                      stock_sparklines=stock_sparklines,
                      vol_turnover=vol_signals)
        logger.info("HTML generated → docs/index.html")
```

Replace with:

```python
        weekly_rank = calc_weekly_rank(universe_df) if universe_df is not None else {}
        generate_data_json(trade_date,
                            meta_perf=meta_perf,
                            universe_df=universe_df,
                            prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                            chips_df=chips_df,
                            cum_data=cum_data,
                            meta_signals=meta_signals,
                            weekly_rank=weekly_rank,
                            stock_sparklines=stock_sparklines)
        logger.info("data.json generated → docs/data.json")
```

Note: `vol_signals`（巨量換手訊號）不再傳進去——這批訊號依規格書移出 index 範圍。`vol_signals` 變數本身在 main.py 後面（`scan_institutional` 那段）可能還有別的用途，不要整段刪掉，只是不再傳給 index 的產生函式。

- [x] **Step 3: Update `_push_html` to include the new build outputs**

Find (`main.py:101-116`):

```python
def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        subprocess.run(["git", "add"] + files_to_add, check=True)
```

Replace with:

```python
def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html", "docs/data.json"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        if os.path.exists("docs/assets"):
            files_to_add.append("docs/assets")
        subprocess.run(["git", "add"] + files_to_add, check=True)
```

`docs/index.html`／`docs/assets` 是 `npm run build` 產生的（見 Task 12），日常跑 `python main.py` 只會更新 `docs/data.json`；`git add` 對沒變化的檔案是no-op，不會多產生 commit。

- [x] **Step 4: Verify main.py still imports cleanly**

Run: `python -c "import main"`
Expected: no output, exit code 0（不用跑 pytest，這步只是語法/import 檢查）

- [x] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: wire main.py to generate docs/data.json instead of index.html"
```

---

### Task 4: Scaffold Vite + React + TypeScript + Vitest

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/App.css`

- [x] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "tw-sector-tracker-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.2",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.4.9",
    "vitest": "^2.1.3"
  }
}
```

- [x] **Step 2: Install dependencies**

Run: `cd frontend && npm install`
Expected: `node_modules/` created, `package-lock.json` generated, exit code 0

- [x] **Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

- [x] **Step 4: Create `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [x] **Step 5: Create `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../docs',
    emptyOutDir: false,
    assetsDir: 'assets',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
```

- [x] **Step 6: Create `frontend/src/setupTests.ts`**

```ts
import '@testing-library/jest-dom'
```

- [x] **Step 7: Create `frontend/index.html`**（Vite entry，跟輸出的 `docs/index.html` 是不同檔案）

```html
<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>台股族群追蹤</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [x] **Step 8: Create `frontend/src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './App.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [x] **Step 9: Create placeholder `frontend/src/App.tsx` and `frontend/src/App.css`**

```tsx
export default function App() {
  return <div>Loading...</div>
}
```

```css
body {
  margin: 0;
  background: #0b0f18;
  color: #e2e8f0;
  font-family: -apple-system, "Segoe UI", sans-serif;
}
```

- [x] **Step 10: Verify build works end-to-end**

Run: `cd frontend && npm run build`
Expected: exit code 0, `docs/index.html` overwritten, `docs/assets/*.js`/`*.css` created, `docs/chips.html` and `docs/patterns.html` untouched (verify with `ls ../docs`)

- [x] **Step 11: Commit**

```bash
git add frontend/ docs/index.html docs/assets
git commit -m "feat: scaffold Vite + React + TypeScript frontend project"
```

---

### Task 5: TypeScript 型別 + `useSectorData` hook

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/hooks/useSectorData.ts`
- Create: `frontend/src/hooks/useSectorData.test.ts`

- [x] **Step 1: Create `frontend/src/types.ts`**

```ts
export interface Stock {
  id: string
  name: string
  close: number | null
  changePct: number | null
  volume: number | null
  weeklyPct: number
  foreignNet: number
  trustNet: number
  marginBalance: number
  marginChange: number
  sparkline: number[]
}

export interface SubGroup {
  name: string
  stocks: Stock[]
}

export interface MetaSector {
  name: string
  avgChangePct: number
  upCount: number
  downCount: number
  cum3: number | null
  cum5: number | null
  cum7: number | null
  todayRank: number
  yesterdayRank: number | null
  thisWeekRank: number | null
  lastWeekRank: number | null
  streak: number
  volRatio: number | null
  subGroups: SubGroup[]
}

export interface SectorData {
  date: string
  market: { avgPct: number; up: number; down: number; flat: number }
  metaSectors: MetaSector[]
}
```

- [x] **Step 2: Write the failing test for the data hook**

Create `frontend/src/hooks/useSectorData.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSectorData } from './useSectorData'
import type { SectorData } from '../types'

const fakeData: SectorData = {
  date: '2026-07-01',
  market: { avgPct: 1.2, up: 300, down: 200, flat: 40 },
  metaSectors: [],
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(fakeData),
    } as Response),
  )
})

describe('useSectorData', () => {
  it('fetches and returns data.json contents', async () => {
    const { result } = renderHook(() => useSectorData())
    expect(result.current.loading).toBe(true)

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toEqual(fakeData)
    expect(result.current.error).toBeNull()
    expect(fetch).toHaveBeenCalledWith('./data.json')
  })

  it('sets error when fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 404 } as Response))
    const { result } = renderHook(() => useSectorData())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toBeNull()
    expect(result.current.error).toContain('404')
  })
})
```

- [x] **Step 2b: Run test to verify it fails**

Run: `cd frontend && npm run test -- useSectorData`
Expected: FAIL — `Cannot find module './useSectorData'`

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/hooks/useSectorData.ts`:

```ts
import { useEffect, useState } from 'react'
import type { SectorData } from '../types'

interface UseSectorDataResult {
  data: SectorData | null
  loading: boolean
  error: string | null
}

export function useSectorData(): UseSectorDataResult {
  const [data, setData] = useState<SectorData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('./data.json')
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load data.json: ${res.status}`)
        }
        return res.json()
      })
      .then((json: SectorData) => {
        setData(json)
        setLoading(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return { data, loading, error }
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- useSectorData`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/hooks/useSectorData.ts frontend/src/hooks/useSectorData.test.ts
git commit -m "feat: add SectorData types and useSectorData fetch hook"
```

---

### Task 6: 排行榜排序純函式

**Files:**
- Create: `frontend/src/lib/sort.ts`
- Create: `frontend/src/lib/sort.test.ts`

- [x] **Step 1: Write the failing test**

Create `frontend/src/lib/sort.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { sortMetaSectors } from './sort'
import type { MetaSector } from '../types'

function makeMeta(name: string, pct: number): MetaSector {
  return {
    name, avgChangePct: pct, upCount: 0, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 0, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
  }
}

describe('sortMetaSectors', () => {
  it('sorts descending by default (gainers first)', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0), makeMeta('C', -2.0)]
    const sorted = sortMetaSectors(input, 'desc')
    expect(sorted.map((m) => m.name)).toEqual(['A', 'B', 'C'])
  })

  it('sorts ascending (losers first) when direction is asc', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0), makeMeta('C', -2.0)]
    const sorted = sortMetaSectors(input, 'asc')
    expect(sorted.map((m) => m.name)).toEqual(['C', 'B', 'A'])
  })

  it('does not mutate the input array', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0)]
    sortMetaSectors(input, 'desc')
    expect(input.map((m) => m.name)).toEqual(['B', 'A'])
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- sort.test`
Expected: FAIL — `Cannot find module './sort'`

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/lib/sort.ts`:

```ts
import type { MetaSector } from '../types'

export type SortDirection = 'asc' | 'desc'

export function sortMetaSectors(
  metaSectors: MetaSector[],
  direction: SortDirection,
): MetaSector[] {
  const sorted = [...metaSectors]
  sorted.sort((a, b) =>
    direction === 'desc'
      ? b.avgChangePct - a.avgChangePct
      : a.avgChangePct - b.avgChangePct,
  )
  return sorted
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- sort.test`
Expected: PASS (3 tests)

- [x] **Step 5: Commit**

```bash
git add frontend/src/lib/sort.ts frontend/src/lib/sort.test.ts
git commit -m "feat: add sortMetaSectors pure function"
```

---

### Task 7: `SignalChips` 元件（日/週排名 + 連漲連跌 + 量能異常）

> 這個元件要給 Task 9 的 `RankList` 用（規格書要求：訊號 chip 要出現在排行榜每一列，不是只出現在明細面板），所以排在 `RankList` 前面實作。

**Files:**
- Create: `frontend/src/components/SignalChips.tsx`
- Create: `frontend/src/components/SignalChips.test.tsx`

- [x] **Step 1: Write the failing test**

Create `frontend/src/components/SignalChips.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SignalChips } from './SignalChips'
import type { MetaSector } from '../types'

function makeMeta(overrides: Partial<MetaSector>): MetaSector {
  return {
    name: 'X', avgChangePct: 1, upCount: 0, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
    ...overrides,
  }
}

describe('SignalChips', () => {
  it('renders nothing when there are no signals', () => {
    const { container } = render(<SignalChips meta={makeMeta({})} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders daily rank chip when rank improved', () => {
    render(<SignalChips meta={makeMeta({ todayRank: 1, yesterdayRank: 10 })} />)
    expect(screen.getByText(/日/)).toBeInTheDocument()
    expect(screen.getByText(/#10→#1/)).toBeInTheDocument()
    expect(screen.getByText(/▲9/)).toBeInTheDocument()
  })

  it('renders weekly rank chip', () => {
    render(<SignalChips meta={makeMeta({ thisWeekRank: 1, lastWeekRank: 8 })} />)
    expect(screen.getByText(/週/)).toBeInTheDocument()
    expect(screen.getByText(/#8→#1/)).toBeInTheDocument()
  })

  it('renders streak chip only when streak >= 2 days', () => {
    const { rerender } = render(<SignalChips meta={makeMeta({ streak: 1 })} />)
    expect(screen.queryByText(/連漲/)).not.toBeInTheDocument()

    rerender(<SignalChips meta={makeMeta({ streak: 3 })} />)
    expect(screen.getByText('連漲3日')).toBeInTheDocument()
  })

  it('renders volume spike chip only when ratio >= 1.5', () => {
    render(<SignalChips meta={makeMeta({ volRatio: 2.5 })} />)
    expect(screen.getByText(/量↑2.5x/)).toBeInTheDocument()
  })

  it('exposes signal intensity via a data attribute for the row color-strip', () => {
    const { container: none } = render(<SignalChips meta={makeMeta({})} />)
    expect(none.firstChild).toBeNull()

    const { container: strong } = render(
      <SignalChips meta={makeMeta({ todayRank: 1, yesterdayRank: 10, streak: 3 })} />,
    )
    expect(strong.firstElementChild).toHaveAttribute('data-intensity', 'strong')

    const { container: weak } = render(<SignalChips meta={makeMeta({ streak: 2 })} />)
    expect(weak.firstElementChild).toHaveAttribute('data-intensity', 'weak')
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- SignalChips`
Expected: FAIL — `Cannot find module './SignalChips'`

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/components/SignalChips.tsx`:

```tsx
import type { MetaSector } from '../types'

interface SignalChipsProps {
  meta: MetaSector
}

export function SignalChips({ meta }: SignalChipsProps) {
  const chips: React.ReactNode[] = []
  let strongSignal = false

  if (meta.yesterdayRank != null) {
    const delta = meta.yesterdayRank - meta.todayRank
    if (delta !== 0) {
      if (Math.abs(delta) >= 5) strongSignal = true
      const arrow = delta > 0 ? '▲' : '▼'
      chips.push(
        <span key="daily-rank" className="chip chip-rank chip-rank-daily">
          <span className="chip-label">日</span> #{meta.yesterdayRank}→#{meta.todayRank}{' '}
          <span className="chip-delta">
            {arrow}
            {Math.abs(delta)}
          </span>
        </span>,
      )
    }
  }

  if (meta.lastWeekRank != null && meta.thisWeekRank != null) {
    const delta = meta.lastWeekRank - meta.thisWeekRank
    if (delta !== 0) {
      if (Math.abs(delta) >= 5) strongSignal = true
      const arrow = delta > 0 ? '▲' : '▼'
      chips.push(
        <span key="weekly-rank" className="chip chip-rank chip-rank-weekly">
          <span className="chip-label">週</span> #{meta.lastWeekRank}→#{meta.thisWeekRank}{' '}
          <span className="chip-delta">
            {arrow}
            {Math.abs(delta)}
          </span>
        </span>,
      )
    }
  }

  if (Math.abs(meta.streak) >= 2) {
    if (Math.abs(meta.streak) >= 3) strongSignal = true
    const label = meta.streak > 0 ? `連漲${meta.streak}日` : `連跌${Math.abs(meta.streak)}日`
    chips.push(
      <span key="streak" className="chip chip-signal">
        🔥 {label}
      </span>,
    )
  }

  if (meta.volRatio != null && meta.volRatio >= 1.5) {
    if (meta.volRatio >= 2) strongSignal = true
    chips.push(
      <span key="vol" className="chip chip-signal">
        📊 量↑{meta.volRatio.toFixed(1)}x
      </span>,
    )
  }

  if (chips.length === 0) {
    return null
  }

  return (
    <div className="signal-chips" data-intensity={strongSignal ? 'strong' : 'weak'}>
      {chips}
    </div>
  )
}
```

`data-intensity` 讓外層（`RankList` 每一列）決定左側色條要粗橘色（`strong`：排名跳動 ≥5 名、連漲連跌 ≥3 日、或量能 ≥2 倍其中之一成立）還是細灰色（`weak`：有訊號但沒那麼強）。沒有任何訊號時整個元件回傳 `null`，外層看不到 `signal-chips` 這個 class，色條也就不會出現（維持乾淨，符合規格書「無變化→無色條」）。

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- SignalChips`
Expected: PASS (6 tests)

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/SignalChips.tsx frontend/src/components/SignalChips.test.tsx
git commit -m "feat: add SignalChips component for daily/weekly rank + streak + volume"
```

---

### Task 8: 子族群分組純函式

**Files:**
- Create: `frontend/src/lib/group.ts`
- Create: `frontend/src/lib/group.test.ts`

- [x] **Step 1: Write the failing test**

Create `frontend/src/lib/group.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { sortStocksWithinGroups } from './group'
import type { SubGroup } from '../types'

function makeStock(id: string, pct: number) {
  return {
    id, name: id, close: 100, changePct: pct, volume: 100,
    weeklyPct: 0, foreignNet: 0, trustNet: 0, marginBalance: 0, marginChange: 0,
    sparkline: [],
  }
}

describe('sortStocksWithinGroups', () => {
  it('sorts stocks within each sub-group descending by changePct', () => {
    const groups: SubGroup[] = [
      { name: '電腦系統業', stocks: [makeStock('B', 1.0), makeStock('A', 5.0)] },
      { name: '伺服器機殼', stocks: [makeStock('C', -1.0)] },
    ]
    const result = sortStocksWithinGroups(groups)
    expect(result[0].stocks.map((s) => s.id)).toEqual(['A', 'B'])
    expect(result[1].stocks.map((s) => s.id)).toEqual(['C'])
  })

  it('does not mutate the input', () => {
    const groups: SubGroup[] = [
      { name: 'g', stocks: [makeStock('B', 1.0), makeStock('A', 5.0)] },
    ]
    sortStocksWithinGroups(groups)
    expect(groups[0].stocks.map((s) => s.id)).toEqual(['B', 'A'])
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- group.test`
Expected: FAIL — `Cannot find module './group'`

- [x] **Step 3: Write minimal implementation**

Create `frontend/src/lib/group.ts`:

```ts
import type { SubGroup } from '../types'

export function sortStocksWithinGroups(subGroups: SubGroup[]): SubGroup[] {
  return subGroups.map((group) => ({
    ...group,
    stocks: [...group.stocks].sort(
      (a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity),
    ),
  }))
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- group.test`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add frontend/src/lib/group.ts frontend/src/lib/group.test.ts
git commit -m "feat: add sortStocksWithinGroups pure function"
```

---

### Task 9: `RankList` 元件（每列含左側訊號色條 + `SignalChips`）

**Files:**
- Create: `frontend/src/components/RankList.tsx`
- Create: `frontend/src/components/RankList.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/RankList.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RankList } from './RankList'
import type { MetaSector } from '../types'

function makeMeta(overrides: Partial<MetaSector> & { name: string; avgChangePct: number }): MetaSector {
  return {
    upCount: 1, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 0, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
    ...overrides,
  }
}

describe('RankList', () => {
  it('renders meta sectors ranked descending by default with rank numbers', () => {
    const metaSectors = [makeMeta({ name: '半導體材料', avgChangePct: 3.28 }), makeMeta({ name: '先進封裝設備', avgChangePct: 4.77 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('先進封裝設備')
    expect(rows[0]).toHaveTextContent('01')
    expect(rows[1]).toHaveTextContent('半導體材料')
  })

  it('calls onSelect with the meta sector name when a row is clicked', () => {
    const onSelect = vi.fn()
    const metaSectors = [makeMeta({ name: '先進封裝設備', avgChangePct: 4.77 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={onSelect} />)

    fireEvent.click(screen.getByText('先進封裝設備'))
    expect(onSelect).toHaveBeenCalledWith('先進封裝設備')
  })

  it('flips sort direction when the toggle is clicked', () => {
    const metaSectors = [makeMeta({ name: 'B', avgChangePct: 1.0 }), makeMeta({ name: 'A', avgChangePct: 5.0 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /切換排序/ }))
    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('B')
  })

  it('renders SignalChips under a row that has signals, and applies a strip class matching intensity', () => {
    const metaSectors = [
      makeMeta({ name: '先進封裝設備', avgChangePct: 4.77, todayRank: 1, yesterdayRank: 10, streak: 3 }),
      makeMeta({ name: '安靜的族群', avgChangePct: 1.0 }),
    ]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('#10→#1')
    expect(rows[0].className).toContain('strip-strong')
    expect(rows[1].className).not.toContain('strip-strong')
    expect(rows[1].className).not.toContain('strip-weak')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- RankList`
Expected: FAIL — `Cannot find module './RankList'`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/RankList.tsx`:

```tsx
import { useState } from 'react'
import type { MetaSector } from '../types'
import { sortMetaSectors, type SortDirection } from '../lib/sort'
import { SignalChips } from './SignalChips'

interface RankListProps {
  metaSectors: MetaSector[]
  selectedName: string | null
  onSelect: (name: string) => void
}

function hasAnySignal(meta: MetaSector): boolean {
  const dailyDelta = meta.yesterdayRank != null ? meta.yesterdayRank - meta.todayRank : 0
  const weeklyDelta =
    meta.lastWeekRank != null && meta.thisWeekRank != null
      ? meta.lastWeekRank - meta.thisWeekRank
      : 0
  return (
    dailyDelta !== 0 ||
    weeklyDelta !== 0 ||
    Math.abs(meta.streak) >= 2 ||
    (meta.volRatio != null && meta.volRatio >= 1.5)
  )
}

function stripIntensityClass(meta: MetaSector): string {
  if (!hasAnySignal(meta)) return ''
  const dailyDelta = meta.yesterdayRank != null ? Math.abs(meta.yesterdayRank - meta.todayRank) : 0
  const weeklyDelta =
    meta.lastWeekRank != null && meta.thisWeekRank != null
      ? Math.abs(meta.lastWeekRank - meta.thisWeekRank)
      : 0
  const strong =
    dailyDelta >= 5 || weeklyDelta >= 5 || Math.abs(meta.streak) >= 3 || (meta.volRatio ?? 0) >= 2
  return strong ? 'strip-strong' : 'strip-weak'
}

export function RankList({ metaSectors, selectedName, onSelect }: RankListProps) {
  const [direction, setDirection] = useState<SortDirection>('desc')
  const sorted = sortMetaSectors(metaSectors, direction)

  return (
    <div className="rank-list">
      <div className="rank-list-header">
        <span>族群排名</span>
        <button
          aria-label="切換排序方向"
          onClick={() => setDirection((d) => (d === 'desc' ? 'asc' : 'desc'))}
        >
          {direction === 'desc' ? '▲' : '▼'}
        </button>
      </div>
      <ul>
        {sorted.map((meta, i) => {
          const sign = meta.avgChangePct >= 0 ? '+' : ''
          const color = meta.avgChangePct >= 0 ? '#f87171' : '#4ade80'
          const stripClass = stripIntensityClass(meta)
          return (
            <li
              key={meta.name}
              role="listitem"
              className={[
                stripClass,
                meta.name === selectedName ? 'active' : '',
              ].filter(Boolean).join(' ')}
              onClick={() => onSelect(meta.name)}
              style={{ cursor: 'pointer' }}
            >
              <div className="rank-row-main">
                <span className="rank-num">{String(i + 1).padStart(2, '0')}</span>
                <span className="rank-name">{meta.name}</span>
                <span className="rank-pct" style={{ color }}>
                  {sign}
                  {meta.avgChangePct.toFixed(2)}%
                </span>
              </div>
              <SignalChips meta={meta} />
            </li>
          )
        })}
      </ul>
    </div>
  )
}
```

`stripIntensityClass` 跟 `SignalChips` 內部的 `data-intensity` 邏輯故意保持一致（daily/weekly rank delta ≥5、連漲連跌 ≥3 日、量能 ≥2 倍任一成立 → `strip-strong`），CSS 會在 Task 14 用 `.strip-strong`/`.strip-weak` 分別畫粗橘色／細灰色左側色條。沒有訊號的列兩個 class 都不會加，維持乾淨（對應規格書「無變化→無色條」）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- RankList`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RankList.tsx frontend/src/components/RankList.test.tsx
git commit -m "feat: add RankList component with per-row SignalChips and color-strip intensity"
```

---

### Task 10: `SectorDetail` 元件（依子族群分組列出個股）

**Files:**
- Create: `frontend/src/components/SectorDetail.tsx`
- Create: `frontend/src/components/SectorDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/SectorDetail.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SectorDetail } from './SectorDetail'
import type { MetaSector } from '../types'

const meta: MetaSector = {
  name: '先進封裝設備', avgChangePct: 4.77, upCount: 1, downCount: 0,
  cum3: null, cum5: null, cum7: null,
  todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
  streak: 0, volRatio: null,
  subGroups: [
    {
      name: '半導體製程設備',
      stocks: [
        { id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
          weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
          marginChange: 0, sparkline: [] },
      ],
    },
  ],
}

describe('SectorDetail', () => {
  it('shows a placeholder when no sector is selected', () => {
    render(<SectorDetail meta={null} />)
    expect(screen.getByText(/請選擇/)).toBeInTheDocument()
  })

  it('renders sub-group label and stock rows', () => {
    render(<SectorDetail meta={meta} />)
    expect(screen.getByText('先進封裝設備')).toBeInTheDocument()
    expect(screen.getByText('半導體製程設備')).toBeInTheDocument()
    expect(screen.getByText('辛耘')).toBeInTheDocument()
    expect(screen.getByText('3583')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- SectorDetail`
Expected: FAIL — `Cannot find module './SectorDetail'`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/SectorDetail.tsx`:

```tsx
import type { MetaSector } from '../types'
import { sortStocksWithinGroups } from '../lib/group'
import { SignalChips } from './SignalChips'

interface SectorDetailProps {
  meta: MetaSector | null
}

export function SectorDetail({ meta }: SectorDetailProps) {
  if (!meta) {
    return <div className="sector-detail-empty">請選擇左側的族群查看個股明細</div>
  }

  const groups = sortStocksWithinGroups(meta.subGroups)
  const sign = meta.avgChangePct >= 0 ? '+' : ''

  return (
    <div className="sector-detail">
      <div className="sector-detail-header">
        <h2>{meta.name}</h2>
        <span>
          {sign}
          {meta.avgChangePct.toFixed(2)}%
        </span>
      </div>
      <SignalChips meta={meta} />
      {groups.map((group) => (
        <div key={group.name} className="sub-group">
          <div className="sub-group-label">{group.name}</div>
          {group.stocks.map((stock) => {
            const pctSign = (stock.changePct ?? 0) >= 0 ? '+' : ''
            return (
              <div key={stock.id} className="stock-row">
                <span className="stock-id">{stock.id}</span>
                <span className="stock-name">{stock.name}</span>
                <span className="stock-close">{stock.close ?? '—'}</span>
                <span className="stock-pct">
                  {stock.changePct != null ? `${pctSign}${stock.changePct.toFixed(2)}%` : '—'}
                </span>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- SectorDetail`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SectorDetail.tsx frontend/src/components/SectorDetail.test.tsx
git commit -m "feat: add SectorDetail component grouping stocks by sub-sector"
```

---

### Task 11: `useMediaQuery` hook + `App` 組裝（響應式雙模式）

**Files:**
- Create: `frontend/src/hooks/useMediaQuery.ts`
- Create: `frontend/src/hooks/useMediaQuery.test.ts`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing test for the hook**

Create `frontend/src/hooks/useMediaQuery.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useMediaQuery } from './useMediaQuery'

function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

describe('useMediaQuery', () => {
  it('returns true when the query matches', () => {
    mockMatchMedia(true)
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(true)
  })

  it('returns false when the query does not match', () => {
    mockMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- useMediaQuery`
Expected: FAIL — `Cannot find module './useMediaQuery'`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/hooks/useMediaQuery.ts`:

```ts
import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)

  useEffect(() => {
    const mql = window.matchMedia(query)
    const listener = () => setMatches(mql.matches)
    listener()
    mql.addEventListener('change', listener)
    return () => mql.removeEventListener('change', listener)
  }, [query])

  return matches
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- useMediaQuery`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing test for `App`**

Create `frontend/src/App.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from './App'
import type { SectorData } from './types'

const fakeData: SectorData = {
  date: '2026-07-01',
  market: { avgPct: 1.2, up: 1, down: 0, flat: 0 },
  metaSectors: [
    {
      name: '先進封裝設備', avgChangePct: 4.77, upCount: 1, downCount: 0,
      cum3: null, cum5: null, cum7: null,
      todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
      streak: 0, volRatio: null,
      subGroups: [
        { name: '半導體製程設備', stocks: [
          { id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
            weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
            marginChange: 0, sparkline: [] },
        ] },
      ],
    },
  ],
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(fakeData) } as Response),
  )
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }))
})

describe('App', () => {
  it('loads data and selecting a rank row shows its detail', async () => {
    render(<App />)

    await waitFor(() => expect(screen.getByText('先進封裝設備')).toBeInTheDocument())

    fireEvent.click(screen.getByText('先進封裝設備'))
    expect(await screen.findByText('辛耘')).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm run test -- App.test`
Expected: FAIL（`App` 目前只回傳 `Loading...`，找不到族群名稱）

- [ ] **Step 7: Write the implementation**

Replace `frontend/src/App.tsx`:

```tsx
import { useState } from 'react'
import { useSectorData } from './hooks/useSectorData'
import { useMediaQuery } from './hooks/useMediaQuery'
import { RankList } from './components/RankList'
import { SectorDetail } from './components/SectorDetail'

export default function App() {
  const { data, loading, error } = useSectorData()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [selectedName, setSelectedName] = useState<string | null>(null)

  if (loading) return <div className="status">載入中...</div>
  if (error) return <div className="status status-error">資料載入失敗：{error}</div>
  if (!data) return null

  const selectedMeta = data.metaSectors.find((m) => m.name === selectedName) ?? null

  return (
    <div className="app">
      <header className="market-header">
        <span>{data.date}</span>
        <span>大盤平均 {data.market.avgPct.toFixed(2)}%</span>
      </header>
      <main className={isDesktop ? 'layout-desktop' : 'layout-mobile'}>
        <RankList
          metaSectors={data.metaSectors}
          selectedName={selectedName}
          onSelect={(name) => setSelectedName(name === selectedName ? null : name)}
        />
        {isDesktop ? (
          <SectorDetail meta={selectedMeta} />
        ) : (
          selectedMeta && <SectorDetail meta={selectedMeta} />
        )}
      </main>
    </div>
  )
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm run test -- App.test`
Expected: PASS

- [ ] **Step 9: Run the full frontend test suite**

Run: `cd frontend && npm run test`
Expected: all test files PASS

- [ ] **Step 10: Commit**

```bash
git add frontend/src/hooks/useMediaQuery.ts frontend/src/hooks/useMediaQuery.test.ts frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: wire up App with responsive layout and rank selection"
```

---

### Task 12: `StockModal` 元件（沿用原本 sparkline + 籌碼明細功能）

**Files:**
- Create: `frontend/src/components/StockModal.tsx`
- Create: `frontend/src/components/StockModal.test.tsx`
- Modify: `frontend/src/components/SectorDetail.tsx`（點個股列開 modal）

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/StockModal.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StockModal } from './StockModal'
import type { Stock } from '../types'

const stock: Stock = {
  id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
  weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
  marginChange: 0, sparkline: [0.1, 4.99, 4.99],
}

describe('StockModal', () => {
  it('renders stock id, name, price and chips info', () => {
    render(<StockModal stock={stock} onClose={() => {}} />)
    expect(screen.getByText('3583')).toBeInTheDocument()
    expect(screen.getByText('辛耘')).toBeInTheDocument()
    expect(screen.getByText('905')).toBeInTheDocument()
    expect(screen.getByText(/336/)).toBeInTheDocument()
    expect(screen.getByText(/-82/)).toBeInTheDocument()
  })

  it('renders one sparkline bar per data point', () => {
    render(<StockModal stock={stock} onClose={() => {}} />)
    expect(screen.getAllByTestId('spark-bar')).toHaveLength(3)
  })

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn()
    render(<StockModal stock={stock} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /關閉/ }))
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- StockModal`
Expected: FAIL — `Cannot find module './StockModal'`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/StockModal.tsx`:

```tsx
import type { Stock } from '../types'

interface StockModalProps {
  stock: Stock
  onClose: () => void
}

export function StockModal({ stock, onClose }: StockModalProps) {
  const maxAbs = Math.max(1, ...stock.sparkline.map((p) => Math.abs(p)))
  const pctSign = (stock.changePct ?? 0) >= 0 ? '+' : ''
  const pctColor = (stock.changePct ?? 0) >= 0 ? '#f87171' : '#4ade80'

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button aria-label="關閉" onClick={onClose}>
          ×
        </button>
        <div className="modal-header">
          <span>{stock.id}</span>
          <span>{stock.name}</span>
        </div>
        <div className="modal-price">
          <span>{stock.close ?? '—'}</span>
          <span style={{ color: pctColor }}>
            {stock.changePct != null ? `${pctSign}${stock.changePct.toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="modal-sparkline">
          {stock.sparkline.map((pct, i) => {
            const up = pct >= 0
            const height = Math.max(3, (Math.abs(pct) / maxAbs) * 32)
            return (
              <div
                key={i}
                data-testid="spark-bar"
                title={`${pct.toFixed(2)}%`}
                style={{
                  height: `${height}px`,
                  width: '8px',
                  background: up ? '#ef4444' : '#22c55e',
                  alignSelf: up ? 'flex-end' : 'flex-start',
                }}
              />
            )
          })}
        </div>
        <div className="modal-chips">
          <div>外資 {stock.foreignNet.toLocaleString()} 張</div>
          <div>投信 {stock.trustNet.toLocaleString()} 張</div>
          <div>
            融資 {stock.marginBalance.toLocaleString()}（{stock.marginChange >= 0 ? '+' : ''}
            {stock.marginChange.toLocaleString()}）
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- StockModal`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire `StockModal` into `SectorDetail`**

Modify `frontend/src/components/SectorDetail.tsx` — add `useState` for the selected stock and open the modal on row click:

```tsx
import { useState } from 'react'
import type { MetaSector, Stock } from '../types'
import { sortStocksWithinGroups } from '../lib/group'
import { SignalChips } from './SignalChips'
import { StockModal } from './StockModal'

interface SectorDetailProps {
  meta: MetaSector | null
}

export function SectorDetail({ meta }: SectorDetailProps) {
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null)

  if (!meta) {
    return <div className="sector-detail-empty">請選擇左側的族群查看個股明細</div>
  }

  const groups = sortStocksWithinGroups(meta.subGroups)
  const sign = meta.avgChangePct >= 0 ? '+' : ''

  return (
    <div className="sector-detail">
      <div className="sector-detail-header">
        <h2>{meta.name}</h2>
        <span>
          {sign}
          {meta.avgChangePct.toFixed(2)}%
        </span>
      </div>
      <SignalChips meta={meta} />
      {groups.map((group) => (
        <div key={group.name} className="sub-group">
          <div className="sub-group-label">{group.name}</div>
          {group.stocks.map((stock) => {
            const pctSign = (stock.changePct ?? 0) >= 0 ? '+' : ''
            return (
              <div
                key={stock.id}
                className="stock-row"
                onClick={() => setSelectedStock(stock)}
                style={{ cursor: 'pointer' }}
              >
                <span className="stock-id">{stock.id}</span>
                <span className="stock-name">{stock.name}</span>
                <span className="stock-close">{stock.close ?? '—'}</span>
                <span className="stock-pct">
                  {stock.changePct != null ? `${pctSign}${stock.changePct.toFixed(2)}%` : '—'}
                </span>
              </div>
            )
          })}
        </div>
      ))}
      {selectedStock && (
        <StockModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  )
}
```

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npm run test`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/StockModal.tsx frontend/src/components/StockModal.test.tsx frontend/src/components/SectorDetail.tsx
git commit -m "feat: add StockModal and wire it into SectorDetail row clicks"
```

---

### Task 13: `SearchBar` 元件

**Files:**
- Create: `frontend/src/components/SearchBar.tsx`
- Create: `frontend/src/components/SearchBar.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/SearchBar.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SearchBar } from './SearchBar'

describe('SearchBar', () => {
  it('calls onSearch with the typed value', () => {
    const onSearch = vi.fn()
    render(<SearchBar onSearch={onSearch} />)
    fireEvent.change(screen.getByPlaceholderText('搜尋族群或股票代號/名稱'), {
      target: { value: '辛耘' },
    })
    expect(onSearch).toHaveBeenCalledWith('辛耘')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- SearchBar`
Expected: FAIL — `Cannot find module './SearchBar'`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/SearchBar.tsx`:

```tsx
interface SearchBarProps {
  onSearch: (query: string) => void
}

export function SearchBar({ onSearch }: SearchBarProps) {
  return (
    <input
      className="search-bar"
      type="text"
      placeholder="搜尋族群或股票代號/名稱"
      onChange={(e) => onSearch(e.target.value)}
    />
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- SearchBar`
Expected: PASS

- [ ] **Step 5: Wire `SearchBar` into `App`** — filter `RankList` by meta-sector name or by any stock id/name inside its sub-groups

Modify `frontend/src/App.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { useSectorData } from './hooks/useSectorData'
import { useMediaQuery } from './hooks/useMediaQuery'
import { RankList } from './components/RankList'
import { SectorDetail } from './components/SectorDetail'
import { SearchBar } from './components/SearchBar'
import type { MetaSector } from './types'

function matchesQuery(meta: MetaSector, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (meta.name.toLowerCase().includes(q)) return true
  return meta.subGroups.some((g) =>
    g.stocks.some(
      (s) => s.id.includes(q) || s.name.toLowerCase().includes(q),
    ),
  )
}

export default function App() {
  const { data, loading, error } = useSectorData()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const filteredMetaSectors = useMemo(() => {
    if (!data) return []
    return data.metaSectors.filter((m) => matchesQuery(m, query))
  }, [data, query])

  if (loading) return <div className="status">載入中...</div>
  if (error) return <div className="status status-error">資料載入失敗：{error}</div>
  if (!data) return null

  const selectedMeta = filteredMetaSectors.find((m) => m.name === selectedName) ?? null

  return (
    <div className="app">
      <header className="market-header">
        <span>{data.date}</span>
        <span>大盤平均 {data.market.avgPct.toFixed(2)}%</span>
        <SearchBar onSearch={setQuery} />
      </header>
      <main className={isDesktop ? 'layout-desktop' : 'layout-mobile'}>
        <RankList
          metaSectors={filteredMetaSectors}
          selectedName={selectedName}
          onSelect={(name) => setSelectedName(name === selectedName ? null : name)}
        />
        {isDesktop ? (
          <SectorDetail meta={selectedMeta} />
        ) : (
          selectedMeta && <SectorDetail meta={selectedMeta} />
        )}
      </main>
    </div>
  )
}
```

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npm run test`
Expected: all PASS（`App.test.tsx` 原本的測試不涉及搜尋，應該還是過；如果失敗，檢查是不是 `matchesQuery` 預設空字串沒有過濾掉任何東西）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/SearchBar.tsx frontend/src/components/SearchBar.test.tsx frontend/src/App.tsx
git commit -m "feat: add SearchBar and wire it into App filtering"
```

---

### Task 14: 最終建置驗證 + CSS 微調

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: 補齊基本版面 CSS**（沿用 DESIGN.md 既有配色，不重新設計視覺風格）

Append to `frontend/src/App.css`:

```css
.app { padding: 12px 20px; }
.market-header { display: flex; gap: 20px; align-items: center; margin-bottom: 16px; }
.layout-desktop { display: flex; gap: 16px; }
.layout-mobile { display: flex; flex-direction: column; }
.rank-list { width: 280px; flex-shrink: 0; }
.layout-mobile .rank-list { width: 100%; }
.rank-list ul { list-style: none; margin: 0; padding: 0; }
.rank-list li { padding: 6px 8px; border-bottom: 1px solid #1e293b; border-left: 3px solid transparent; }
.rank-list li.active { background: rgba(255,255,255,.05); }
.rank-list li.strip-weak { border-left-color: #475569; }
.rank-list li.strip-strong { border-left-color: #f97316; background: rgba(124,45,18,.12); }
.rank-row-main { display: flex; gap: 10px; align-items: baseline; }
.rank-num { font-weight: 800; width: 24px; }
.rank-name { flex: 1; }
.sector-detail { flex: 1; }
.sector-detail-empty { opacity: .5; padding: 20px; }
.sub-group-label { color: #64748b; font-size: .7rem; text-transform: uppercase; margin: 10px 0 4px; border-bottom: 1px solid #1e293b; padding-bottom: 2px; }
.stock-row { display: flex; gap: 10px; padding: 4px 0; }
.signal-chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
.chip { border-radius: 12px; padding: 3px 9px; font-size: .78rem; }
.chip-rank-daily { background: rgba(248,113,113,.15); border: 1px solid rgba(248,113,113,.4); color: #f87171; font-weight: 800; }
.chip-rank-weekly { background: rgba(248,113,113,.1); border: 1px solid rgba(248,113,113,.3); color: #fca5a5; font-weight: 800; }
.chip-signal { background: rgba(251,146,60,.15); border: 1px solid rgba(251,146,60,.35); color: #fdba74; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; }
.modal { background: #0f1624; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; min-width: 280px; }
.modal-sparkline { display: flex; align-items: center; gap: 3px; height: 40px; margin: 10px 0; }
.search-bar { margin-left: auto; background: #0a0e18; border: 1px solid #1e293b; color: #e2e8f0; padding: 4px 8px; border-radius: 6px; }
```

- [ ] **Step 2: 完整建置**

Run: `cd frontend && npm run build`
Expected: exit code 0；確認 `docs/index.html`、`docs/assets/*` 有更新，`docs/chips.html`、`docs/patterns.html`、`docs/data.json` 沒被動到

- [ ] **Step 3: 跑完整前後端測試**

Run: `cd frontend && npm run test && cd .. && pytest tests/test_data_generator.py tests/test_processors.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.css docs/index.html docs/assets
git commit -m "feat: add base CSS styling for redesigned index page"
```

- [ ] **Step 5: 手動驗證（不是自動化步驟，留給 Cody / Debugger）**

跑一次完整流程確認整合正確：
1. `python main.py`（或帶適當 flag，確認會產生新的 `docs/data.json`）
2. `cd frontend && npm run build`
3. 用瀏覽器直接打開 `docs/index.html` 或起一個本機靜態伺服器（例如 `python -m http.server` 在 `docs/` 目錄下），確認：桌機寬度看得到左右分欄、縮小視窗看得到單欄模式、點族群能看到個股、點個股能開 modal、搜尋能過濾

---

## Self-Review checklist（寫完後自查，不用再開一輪）

- [x] 規格書「響應式雙模式」→ Task 11（`useMediaQuery` + App 組裝）
- [x] 規格書「兩層點擊，子族群當分類標籤」→ Task 10（`SectorDetail`）
- [x] 規格書「Top10 移除，排序取代」→ Task 6/9（`sortMetaSectors` + `RankList` 排序切換）
- [x] 規格書「日+週排名 chip」→ Task 1（`calc_weekly_rank`）+ Task 7（`SignalChips`）
- [x] 規格書「訊號統一收進每列左側色條容器，強度反映粗細/顏色」→ Task 9（`RankList` 的 `stripIntensityClass` + `.strip-strong`/`.strip-weak`，跟 `SignalChips` 的 `data-intensity` 邏輯一致），Task 14 補上對應 CSS（修正：原規劃曾誤把 `SignalChips` 只接到 `SectorDetail`，未出現在排行榜列上，已改為 `RankList` 每列都渲染 `SignalChips`）
- [x] 規格書「沿用個股 modal／搜尋／排序」→ Task 12（`StockModal`）、Task 13（`SearchBar`）
- [x] 規格書「巨量換手移出範圍」→ Task 3 明確註明不再傳 `vol_signals` 給新的產生函式
- [x] 規格書「data.json 資料流、不用 GitHub Actions」→ Task 3（`_push_html` 更新）+ Task 4（`vite.config.ts` build 設定，`emptyOutDir: false` 避免砍掉 `chips.html`/`patterns.html`）
- [x] 型別/函式簽名一致性檢查：`MetaSector`/`Stock`/`SubGroup` 型別從 Task 5 定義後，Task 6-13 全部沿用同一份 `types.ts`，沒有另外重複定義
- [x] 依賴順序檢查：Task 9（`RankList`）依賴 Task 7（`SignalChips`），已確認 7 排在 9 前面；Task 10（`SectorDetail`）依賴 Task 7（`SignalChips`）+ Task 8（`group.ts`），兩者都在 10 之前
