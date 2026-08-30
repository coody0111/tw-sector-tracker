# 籌碼頁今日焦點 + 大戶持倉卡片化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `docs/chips.html` 加上「今日焦點」headline zone（候選觀察卡片 + 大戶持倉本週焦點迷你面板），側欄9個分頁籤分成3組，大戶籌碼從13欄密集表格改成卡片+週變化發散長條+近5週趨勢SVG走勢圖（維持現行「連增倉/連減倉」兩張獨立清單結構）。

**Architecture:** 沿用專案既有「Python 組資料 → f-string 產生完整HTML」慣例（不引入前端框架）。新增檔案 `export/chips_headline.py` 承載 headline zone 的渲染邏輯（候選觀察卡片、大戶持倉迷你面板），比照 `export/momentum_generator.py`/`export/index_heatmap.py` 自成一檔的既有慣例，避免 `export/chips_generator.py`（目前已 1319 行）繼續變大。大戶持倉卡片化的渲染函式直接改在 `chips_generator.py` 內（就地取代 `_shareholder_table()`，屬性上跟既有 Section 8 邏輯強耦合，不獨立成檔）。資料層新增 `screener/database.py::get_shareholder_trend()`，沿用 `get_shareholder_top()` 已驗證過的 `ROW_NUMBER() OVER(PARTITION BY stock_id ORDER BY date DESC)` pattern，把 `rn` 上限從既有的 2 改成可設定的週數（預設 5）。

**Tech Stack:** Python f-string HTML/CSS/SVG 產生（無前端框架）、DuckDB 視窗函式查詢、pytest。

**設計依據**：`docs/superpowers/mockups/2026-07-23-chips-v3-final.html`（定案版 mockup，已發布 https://claude.ai/code/artifact/c5f948f5-3852-4a39-a385-d3598da65e33）。

---

## Global Constraints

- **候選觀察卡片的資料來源必須是既有 `rank_joint_buy_candidates()` 的真實輸出**（`screener/institutional.py`），不是新造一支排序邏輯——`export/chips_generator.py::_build_section6()` 已經在用這支函式產生「法人同步買超觀察」的完整榜單，headline zone 只是把同一份結果的前3名再抽出來、用更大的視覺呈現，資料源必須完全一致（同一次 `generate()` 呼叫內，不重算兩次）。
- **誠實揭露文案是強制要求，不是可省略的裝飾**：候選觀察卡片區塊必須包含「這是條件篩選出的觀察名單，不是投資建議」+ 排序邏輯尚未完成統計驗證的說明文字（見 mockup `.disclosure` 區塊），理由見 `debug-tasks.md`「桌電待驗：籌碼策略是否真的有增益」條目——回測配對組/bootstrap/樣本外驗證都還沒做完，UI 不能暗示這是已證實有效的訊號。
- **大戶持倉維持「連增倉／連減倉」兩張獨立清單**，不合併成單一混排清單——這是跟現行 production 行為一致的決定（`_build_section8()` 現有邏輯已經拆兩組），只換渲染方式（表格→卡片），不改資料分組邏輯。
- **週變化發散長條、Y軸刻度、X軸日期全部畫在同一個SVG座標系統**，不要用 HTML flex row + padding 去猜對齊（mockup 開發過程中真的踩過這個對不齊的 bug，教訓：兩個獨立排版的元素本來就對不準）。viewBox 座標配置固定用 `0 0 92 32`：Y軸文字留白 x=0~20、圖表繪製區 x=22~92／y=2~18、X軸日期文字 y=29。
- **趨勢走勢圖的實際可用週數不是寫死的5**：`shareholder` 表的實際歷史深度會隨時間增長，`get_shareholder_trend()` 用 `LIMIT` 週數當上限、不強制剛好5筆——某支股票如果只有2、3筆資料就畫2、3個點，不足5筆不是錯誤，是誠實反映資料現況（早期上市股或新纳入追蹤的股票可能歷史較短）。少於2筆（畫不出線）時走勢圖區塊顯示「資料不足」文字，不留空白也不硬湊假數據。
- **側欄分頁分組是純前端HTML重排，不改變9個 `tab-panel` 本身的內容或ID**——`switchTab()` JS 邏輯、`data-tab`/`aria-controls` 屬性、各分頁對應的 section 內容完全不動，只是外層的 `.tab-bar` 容器改成3個帶標籤的分組。

## File Structure

- **Create** `export/chips_headline.py`：headline zone 渲染邏輯——`build_candidate_cards()`（候選觀察，吃 `rank_joint_buy_candidates()` 的輸出）、`build_holder_focus_mini()`（大戶持倉本週焦點迷你面板，吃 `shareholder_data` 前5檔）、`render_headline_zone()`（組裝成完整HTML+CSS區塊）。
- **Modify** `screener/database.py`：新增 `get_shareholder_trend(weeks=5)`，緊接在 `get_shareholder_top()` 後面。
- **Modify** `export/chips_generator.py`：
  - 新增 `_calc_trend_svg()`、`_holder_card_html()`、`_holder_column_html()`（取代 `_shareholder_table()` 在 Section 8 的用途，`_shareholder_table()` 函式本身可以保留但不再被 `_build_section8()` 呼叫，避免動到其他呼叫端——先確認真的沒有其他呼叫點）
  - `_build_section8()` 改呼叫新的卡片渲染函式
  - `generate()` 內側欄 `.tab-bar` 改成3個分組
  - `generate()` 呼叫 `export/chips_headline.py::render_headline_zone()`，把結果插進 `<main>` 最上方
  - CSS（`_CSS` 常數）新增卡片/發散長條/SVG趨勢圖的樣式
- **Modify** `main.py`：呼叫 `get_shareholder_trend()`，把週趨勢資料合併進 `sh_rows`（每筆加一個 `"trend"` 欄位）。
- **Test**：`tests/test_database.py`（新增 `get_shareholder_trend()` 測試，若該檔案不存在則建立，跟 `get_shareholder_top()` 現有測試同檔案）、`tests/test_chips_generator.py`（擴充）、`tests/test_chips_headline.py`（新檔）。

---

### Task 1: `get_shareholder_trend()` — 大戶持倉週趨勢資料查詢

**Files:**
- Modify: `screener/database.py`
- Test: `tests/test_database.py`（若不存在則建立；先 `grep -rn "get_shareholder_top" tests/` 確認既有測試放在哪個檔案，若已有專門測試 `screener/database.py` 的檔案就加在那裡，不要另建重複檔案）

- [ ] **Step 1: 確認既有測試檔案位置**

Run: `grep -rln "get_shareholder_top" tests/`

如果有輸出（例如 `tests/test_database.py`），後續測試加進那個檔案；如果沒有輸出，建立新檔 `tests/test_database.py`。

- [ ] **Step 2: 寫失敗測試**

在確認的檔案裡加入（沿用 `screener/database.py` 既有的 `get_conn()`/DuckDB 慣例，若既有測試檔案已有建 `shareholder` 表的 helper 就重用，否則新增）：

```python
import duckdb

from screener.database import get_shareholder_trend


def _seed_shareholder_trend_db(db_path, rows):
    """rows: list of (stock_id, date, lv12_15_pct)"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE shareholder (
            stock_id VARCHAR, date DATE, lv12_15_pct DOUBLE, lv12_15_cnt BIGINT,
            lv12_15_shares BIGINT, week_chg DOUBLE, streak INTEGER,
            lv12_shares BIGINT, lv12_pct DOUBLE, lv15_shares BIGINT, lv15_pct DOUBLE
        )
    """)
    con.executemany(
        "INSERT INTO shareholder (stock_id, date, lv12_15_pct) VALUES (?, ?, ?)", rows
    )
    con.close()


def test_get_shareholder_trend_returns_last_n_weeks_oldest_to_newest(tmp_path, monkeypatch):
    """5週資料、要5筆，且必須是「舊到新」排序（畫走勢圖要照時間順序），不是DB查詢的
    ORDER BY date DESC那個新到舊順序（那是給get_shareholder_top()用的，這裡要反過來）。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2330", "2026-06-19", 60.0),
        ("2330", "2026-06-26", 61.0),
        ("2330", "2026-07-03", 62.5),
        ("2330", "2026-07-10", 63.0),
        ("2330", "2026-07-17", 64.0),
    ]
    _seed_shareholder_trend_db(db_path, rows)
    monkeypatch.setattr("screener.database.get_conn", lambda: duckdb.connect(str(db_path)))

    result = get_shareholder_trend(weeks=5)

    assert result["2330"] == [
        {"date": "2026-06-19", "lv12_15_pct": 60.0},
        {"date": "2026-06-26", "lv12_15_pct": 61.0},
        {"date": "2026-07-03", "lv12_15_pct": 62.5},
        {"date": "2026-07-10", "lv12_15_pct": 63.0},
        {"date": "2026-07-17", "lv12_15_pct": 64.0},
    ]


def test_get_shareholder_trend_handles_fewer_than_requested_weeks(tmp_path, monkeypatch):
    """只有2筆歷史(新股/新納入追蹤)時，回傳這2筆，不是報錯或補假資料湊到5筆。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("1101", "2026-07-10", 40.0),
        ("1101", "2026-07-17", 41.5),
    ]
    _seed_shareholder_trend_db(db_path, rows)
    monkeypatch.setattr("screener.database.get_conn", lambda: duckdb.connect(str(db_path)))

    result = get_shareholder_trend(weeks=5)

    assert result["1101"] == [
        {"date": "2026-07-10", "lv12_15_pct": 40.0},
        {"date": "2026-07-17", "lv12_15_pct": 41.5},
    ]


def test_get_shareholder_trend_respects_weeks_param(tmp_path, monkeypatch):
    """weeks=3時只回傳最近3筆，不是全部歷史。"""
    db_path = tmp_path / "test.db"
    rows = [
        ("2454", "2026-06-19", 30.0),
        ("2454", "2026-06-26", 31.0),
        ("2454", "2026-07-03", 32.0),
        ("2454", "2026-07-10", 33.0),
        ("2454", "2026-07-17", 34.0),
    ]
    _seed_shareholder_trend_db(db_path, rows)
    monkeypatch.setattr("screener.database.get_conn", lambda: duckdb.connect(str(db_path)))

    result = get_shareholder_trend(weeks=3)

    assert result["2454"] == [
        {"date": "2026-07-03", "lv12_15_pct": 32.0},
        {"date": "2026-07-10", "lv12_15_pct": 33.0},
        {"date": "2026-07-17", "lv12_15_pct": 34.0},
    ]


def test_get_shareholder_trend_excludes_outlier_pct(tmp_path, monkeypatch):
    """跟get_shareholder_top()同一個離群值防護(#2)：>=_MAX_VALID_HOLDER_PCT視為TDCC解析
    異常，整筆排除（不是只排除那個異常值、留其他欄位），避免走勢圖畫出不可能的數字。"""
    from scrapers.shareholder import _MAX_VALID_HOLDER_PCT
    db_path = tmp_path / "test.db"
    rows = [
        ("3008", "2026-07-10", 70.0),
        ("3008", "2026-07-17", _MAX_VALID_HOLDER_PCT),
    ]
    _seed_shareholder_trend_db(db_path, rows)
    monkeypatch.setattr("screener.database.get_conn", lambda: duckdb.connect(str(db_path)))

    result = get_shareholder_trend(weeks=5)

    assert result["3008"] == [{"date": "2026-07-10", "lv12_15_pct": 70.0}]
```

- [ ] **Step 3: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_database.py -k get_shareholder_trend -v`
Expected: FAIL with `ImportError: cannot import name 'get_shareholder_trend'`

- [ ] **Step 4: 實作 `get_shareholder_trend()`**

在 `screener/database.py`，緊接在 `get_shareholder_top()` 函式後面加入：

```python
def get_shareholder_trend(weeks: int = 5) -> dict:
    """每支股票近 N 週的 400張以上大戶%（lv12_15_pct）歷史，舊到新排序，供大戶持倉卡片
    的迷你趨勢走勢圖使用。實際筆數可能少於 weeks（歷史不足時，例如新上市股或剛納入
    追蹤的股票），不強制補齊——回傳筆數就是真實可用的資料點數。

    離群值防護跟 get_shareholder_top() 一致：>=_MAX_VALID_HOLDER_PCT 視為 TDCC 集保
    股權分散表解析異常，整筆排除。

    回傳 {stock_id: [{"date": str, "lv12_15_pct": float}, ...]}（舊到新）。
    """
    from scrapers.shareholder import _MAX_VALID_HOLDER_PCT
    con = get_conn()
    df = con.execute(f"""
        WITH ranked AS (
            SELECT stock_id, date, lv12_15_pct,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
            FROM shareholder
            WHERE lv12_15_pct < {_MAX_VALID_HOLDER_PCT}
        )
        SELECT stock_id, date, lv12_15_pct
        FROM ranked
        WHERE rn <= {weeks}
        ORDER BY stock_id, date ASC
    """).df()
    con.close()

    result: dict = {}
    for _, row in df.iterrows():
        sid = str(row["stock_id"])
        result.setdefault(sid, []).append({
            "date": str(row["date"]),
            "lv12_15_pct": float(row["lv12_15_pct"]),
        })
    return result
```

- [ ] **Step 5: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_database.py -k get_shareholder_trend -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add screener/database.py tests/test_database.py
git commit -m "feat(database): get_shareholder_trend()查詢每股近N週400張以上大戶%歷史"
```

---

### Task 2: `_calc_trend_svg()` — 走勢圖SVG座標計算（純函式，跟main.py資料層解耦）

**Files:**
- Modify: `export/chips_generator.py`
- Test: `tests/test_chips_generator.py`

**這支函式接的是 Task 1 `get_shareholder_trend()` 的輸出格式**（`[{"date":..., "lv12_15_pct":...}, ...]`，舊到新），純計算不碰DB，方便單元測試。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py` 加入：

```python
from export.chips_generator import _calc_trend_svg


def test_calc_trend_svg_returns_none_when_fewer_than_two_points():
    """少於2筆資料畫不出線，回傳None讓呼叫端顯示「資料不足」文字，不是硬畫一個點。"""
    assert _calc_trend_svg([]) is None
    assert _calc_trend_svg([{"date": "2026-07-17", "lv12_15_pct": 60.0}]) is None


def test_calc_trend_svg_scales_points_to_viewbox():
    """viewBox固定0 0 92 32，圖表繪製區x=22~92/y=2~18。5個點應該平均分布在x=22~92，
    y依min-max正規化（最大值在y=2附近，最小值在y=18附近）。"""
    trend = [
        {"date": "2026-06-19", "lv12_15_pct": 60.0},
        {"date": "2026-06-26", "lv12_15_pct": 61.0},
        {"date": "2026-07-03", "lv12_15_pct": 62.5},
        {"date": "2026-07-10", "lv12_15_pct": 63.0},
        {"date": "2026-07-17", "lv12_15_pct": 64.0},
    ]
    result = _calc_trend_svg(trend)

    assert result["y_max_label"] == "64.0"
    assert result["y_min_label"] == "60.0"
    assert result["x_labels"] == ["06/19", "06/26", "07/03", "07/10", "07/17"]
    # 5個點：x座標從22到92平均分布
    points = result["line_points"]
    assert points[0].startswith("22.0,")
    assert points[-1].startswith("92.0,")
    # 最新一筆(64.0，最大值)應該在y=2(圖表頂部)
    assert points[-1] == "92.0,2.0"
    # 最舊一筆(60.0，最小值)應該在y=18(圖表底部)
    assert points[0] == "22.0,18.0"


def test_calc_trend_svg_handles_fewer_than_five_points():
    """只有2筆資料(新股/剛納入追蹤)時，2個點應該落在x=22跟x=92(圖表兩端)，不是
    擠在左邊或用固定5等分的間距（間距要照實際筆數動態算，不是寫死5）。"""
    trend = [
        {"date": "2026-07-10", "lv12_15_pct": 40.0},
        {"date": "2026-07-17", "lv12_15_pct": 41.5},
    ]
    result = _calc_trend_svg(trend)

    assert len(result["line_points"]) == 2
    assert result["line_points"][0].startswith("22.0,")
    assert result["line_points"][1].startswith("92.0,")
    assert result["x_labels"] == ["07/10", "07/17"]


def test_calc_trend_svg_handles_flat_series_without_division_by_zero():
    """所有值都相同時(min==max)，range=0會除零——必須有防呆，不能crash，這種情況所有點
    應該畫在垂直置中(y=10，圖表區y=2~18的中點)。"""
    trend = [
        {"date": "2026-07-10", "lv12_15_pct": 50.0},
        {"date": "2026-07-17", "lv12_15_pct": 50.0},
    ]
    result = _calc_trend_svg(trend)

    assert result["line_points"][0] == "22.0,10.0"
    assert result["line_points"][1] == "92.0,10.0"
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_generator.py -k calc_trend_svg -v`
Expected: FAIL with `ImportError: cannot import name '_calc_trend_svg'`

- [ ] **Step 3: 實作 `_calc_trend_svg()`**

在 `export/chips_generator.py`，找到 `_shareholder_table()` 函式（約第406行）前面加入：

```python
def _calc_trend_svg(trend: list) -> dict | None:
    """把 get_shareholder_trend() 的輸出（舊到新的 [{date, lv12_15_pct}, ...]）換算成
    SVG viewBox座標。固定 viewBox "0 0 92 32"：Y軸文字留白 x=0~20、圖表繪製區
    x=22~92/y=2~18、X軸日期文字 y=29。

    回傳 None 時代表資料點不足2筆畫不出線，呼叫端要顯示「資料不足」文字。
    """
    if len(trend) < 2:
        return None

    values = [t["lv12_15_pct"] for t in trend]
    lo, hi = min(values), max(values)
    rng = hi - lo

    n = len(trend)
    plot_left, plot_right = 22.0, 92.0
    plot_top, plot_bottom = 2.0, 18.0

    line_points = []
    for i, t in enumerate(trend):
        x = plot_left + (plot_right - plot_left) * i / (n - 1)
        if rng == 0:
            y = (plot_top + plot_bottom) / 2  # 防除零：全部持平畫在垂直置中
        else:
            y = plot_bottom - (t["lv12_15_pct"] - lo) / rng * (plot_bottom - plot_top)
        line_points.append(f"{x:.1f},{y:.1f}")

    area_points = line_points + [f"{plot_right:.1f},20.0", f"{plot_left:.1f},20.0"]

    x_labels = []
    for t in trend:
        # "2026-07-17" -> "07/17"
        parts = t["date"].split("-")
        x_labels.append(f"{parts[1]}/{parts[2]}")

    return {
        "line_points": line_points,
        "area_points": area_points,
        "x_labels": x_labels,
        "y_max_label": f"{hi:.1f}",
        "y_min_label": f"{lo:.1f}",
        "end_point": line_points[-1],
    }
```

- [ ] **Step 4: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_generator.py -k calc_trend_svg -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips-generator): _calc_trend_svg()把週趨勢資料換算成SVG viewBox座標"
```

---

### Task 3: 大戶持倉卡片渲染（`_holder_card_html()` + `_holder_column_html()`）

**Files:**
- Modify: `export/chips_generator.py`
- Test: `tests/test_chips_generator.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py` 加入：

```python
from export.chips_generator import _holder_card_html, _holder_column_html


def test_holder_card_html_renders_divergent_bar_matching_direction():
    """週變化為正時發散長條該用up方向(css class)，負時用down。"""
    row = {
        "stock_id": "5347", "stock_name": "世界先進", "meta_sector": "晶圓代工",
        "close": 128.5, "change_pct": 1.2,
        "lv12_15_pct": 68.4, "week_chg": 2.1, "streak": 6,
        "share_chg": 412000, "lv15_pct": 22.6,
        "trend": [
            {"date": "2026-06-19", "lv12_15_pct": 63.0},
            {"date": "2026-07-17", "lv12_15_pct": 68.4},
        ],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert "世界先進" in html
    assert "5347" in html
    assert 'class="hc-divbar"' in html
    assert '<span class="up"' in html
    assert "連增6週" in html
    assert "68.4" in html  # 絕對水位


def test_holder_card_html_negative_week_chg_uses_down_direction():
    row = {
        "stock_id": "8261", "stock_name": "富鼎", "meta_sector": "功率半導體",
        "close": 312.5, "change_pct": -0.5,
        "lv12_15_pct": 59.3, "week_chg": -0.8, "streak": -2,
        "share_chg": -96000, "lv15_pct": 18.1,
        "trend": [
            {"date": "2026-07-10", "lv12_15_pct": 60.1},
            {"date": "2026-07-17", "lv12_15_pct": 59.3},
        ],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert '<span class="down"' in html
    assert "連減2週" in html


def test_holder_card_html_shows_insufficient_data_when_trend_missing():
    """trend筆數<2(新股/剛納入追蹤)時，卡片要顯示「資料不足」文字，不能crash、
    不能留空白區塊裝作沒事。"""
    row = {
        "stock_id": "1101", "stock_name": "測試股", "meta_sector": "水泥",
        "close": 40.0, "change_pct": 0.5,
        "lv12_15_pct": 41.5, "week_chg": 1.5, "streak": 1,
        "share_chg": 1000, "lv15_pct": 5.0,
        "trend": [{"date": "2026-07-17", "lv12_15_pct": 41.5}],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=2.1)

    assert "資料不足" in html


def test_holder_card_html_escapes_malicious_stock_name():
    row = {
        "stock_id": "9999", "stock_name": "<script>alert(1)</script>", "meta_sector": "測試",
        "close": 10.0, "change_pct": 0.0,
        "lv12_15_pct": 50.0, "week_chg": 0.0, "streak": 0,
        "share_chg": 0, "lv15_pct": 0.0,
        "trend": [],
    }
    html = _holder_card_html(row, rank=1, max_abs_week_chg=1.0)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_holder_column_html_scales_divergent_bar_to_column_max():
    """發散長條寬度依「這一欄實際出現的最大週變化幅度」動態縮放，不是固定量尺——
    這一欄最大變化的那檔應該長條寬度撐滿(接近50%的一半寬)，其他檔案按比例縮小。"""
    rows = [
        {"stock_id": "A", "stock_name": "甲", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 60.0, "week_chg": 4.0, "streak": 3,
         "share_chg": 0, "lv15_pct": 0.0, "trend": []},
        {"stock_id": "B", "stock_name": "乙", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 55.0, "week_chg": 2.0, "streak": 2,
         "share_chg": 0, "lv15_pct": 0.0, "trend": []},
    ]
    html = _holder_column_html(rows, direction="inc")

    assert "width:50.0%" in html  # 甲(4.0)是最大值，長條撐滿50%(發散長條半邊寬度上限)
    assert "width:25.0%" in html  # 乙(2.0)是甲的一半，長條寬度也是一半


def test_holder_column_html_empty_list_shows_no_data_message():
    html = _holder_column_html([], direction="dec")
    assert "無資料" in html
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_generator.py -k "holder_card_html or holder_column_html" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 實作 `_holder_card_html()` 與 `_holder_column_html()`**

在 `export/chips_generator.py`，緊接在 Task 2 加入的 `_calc_trend_svg()` 後面加入：

```python
def _holder_card_html(row: dict, rank: int, max_abs_week_chg: float) -> str:
    """單張大戶持倉卡片：排名/名稱/收盤、週變化發散長條(依max_abs_week_chg動態縮放)、
    次要指標(連增減週數/張數變化/1000張以上)一行小字、近N週趨勢SVG走勢圖。"""
    week_chg = row.get("week_chg") or 0.0
    direction = "up" if week_chg >= 0 else "down"
    bar_pct = abs(week_chg) / max_abs_week_chg * 50 if max_abs_week_chg > 0 else 0
    streak = row.get("streak") or 0
    streak_txt = f"連增{streak}週" if streak > 0 else (f"連減{abs(streak)}週" if streak < 0 else "")
    streak_pill = (
        f'<span class="hc-streak-pill {direction}">{streak_txt}</span>' if streak_txt else ""
    )

    price_cls = "up" if (row.get("change_pct") or 0) >= 0 else "down"
    price_pct = row.get("change_pct")
    price_pct_str = f"{price_pct:+.1f}%" if price_pct is not None else "─"

    share_chg = row.get("share_chg")
    share_chg_lots = round(share_chg / 1000) if share_chg is not None else None
    share_chg_str = f"{share_chg_lots:+,}張" if share_chg_lots is not None else "─"
    share_chg_color = "var(--up)" if (share_chg_lots or 0) >= 0 else "var(--down)"

    trend = _calc_trend_svg(row.get("trend") or [])
    if trend is None:
        trend_html = '<div class="hc-trend-empty">近期資料不足，尚無法繪製趨勢</div>'
    else:
        line = " ".join(trend["line_points"])
        area = " ".join(trend["area_points"])
        end_x, end_y = trend["end_point"].split(",")
        x_label_els = []
        n_labels = len(trend["x_labels"])
        for i, lbl in enumerate(trend["x_labels"]):
            x = 22.0 + (92.0 - 22.0) * i / (n_labels - 1) if n_labels > 1 else 22.0
            anchor = "start" if i == 0 else ("end" if i == n_labels - 1 else "middle")
            x_label_els.append(f'<text x="{x:.1f}" y="29" text-anchor="{anchor}">{_esc(lbl)}</text>')
        trend_dir_cls = " down" if direction == "down" else ""
        trend_html = f"""<div class="hc-trend{trend_dir_cls}">
  <svg viewBox="0 0 92 32">
    <line class="trend-grid" x1="22" y1="18" x2="92" y2="18"/>
    <polyline class="trend-area" points="{area}"/>
    <polyline class="trend-line" points="{line}"/>
    <circle class="trend-end" cx="{end_x}" cy="{end_y}" r="2"/>
    <text class="axis-label" x="20" y="6">{trend['y_max_label']}</text>
    <text class="axis-label" x="20" y="19">{trend['y_min_label']}</text>
    {''.join(x_label_els)}
  </svg>
</div>"""

    return f"""<div class="holder-card">
  <div class="hc-top">
    <span class="hc-rank">#{rank}</span>
    <span class="hc-name">{_esc(row.get('stock_name', ''))}</span><span class="hc-sid">{_esc(row['stock_id'])}</span>
    <span class="hc-price {price_cls}">{row.get('close', '─')} <span style="font-size:.62rem">{price_pct_str}</span></span>
  </div>
  <div class="hc-meta">{_esc(row.get('meta_sector', ''))}</div>
  <div class="hc-bar-row">
    <div class="hc-divbar"><span class="{direction}" style="width:{bar_pct:.1f}%"></span></div>
    <span class="hc-week {direction}">{week_chg:+.1f}%</span>
    <span class="hc-abs">{row.get('lv12_15_pct', 0):.1f}%</span>
  </div>
  <div class="hc-badges">
    {streak_pill}
    <span>張數變化 <b style="color:{share_chg_color}">{share_chg_str}</b></span>
    <span>1000張以上 <b>{row.get('lv15_pct') or 0:.1f}%</b></span>
  </div>
  {trend_html}
</div>"""


def _holder_column_html(rows: list, direction: str) -> str:
    """一整欄（連增倉或連減倉）的卡片grid。direction只影響空狀態文案，實際每張卡的
    up/down是各自依自己的week_chg正負決定（連減倉欄位裡理論上week_chg都是負的，但
    這裡不假設，用各自實際符號渲染，比較穩健）。"""
    if not rows:
        return "<div class='no-data'>無資料</div>"
    max_abs_week_chg = max((abs(r.get("week_chg") or 0) for r in rows), default=0) or 1.0
    cards = "".join(
        _holder_card_html(row, i + 1, max_abs_week_chg) for i, row in enumerate(rows)
    )
    return f'<div class="holder-grid">{cards}</div>'
```

- [ ] **Step 4: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_generator.py -k "holder_card_html or holder_column_html" -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips-generator): _holder_card_html()/_holder_column_html()大戶持倉卡片化渲染"
```

---

### Task 4: `_build_section8()` 改接卡片渲染 + CSS

**Files:**
- Modify: `export/chips_generator.py`
- Test: `tests/test_chips_generator.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py` 加入：

```python
def test_build_section8_uses_card_rendering_not_old_table():
    """Section 8改用卡片渲染後，舊的13欄表格結構(<table class='ct'>那種)不該再出現在
    大戶持倉區塊，改成.holder-grid卡片。"""
    from export.chips_generator import _build_section8
    shareholder_data = [
        {"stock_id": "5347", "stock_name": "世界先進", "meta_sector": "晶圓代工",
         "close": 128.5, "change_pct": 1.2, "lv12_15_pct": 68.4, "week_chg": 2.1,
         "streak": 6, "share_chg": 412000, "lv15_pct": 22.6, "date": "2026-07-17",
         "trend": [{"date": "2026-07-10", "lv12_15_pct": 66.3},
                   {"date": "2026-07-17", "lv12_15_pct": 68.4}]},
    ]
    s8_html, s8_note, _ = _build_section8(shareholder_data, [])

    assert "holder-grid" in s8_html
    assert "holder-card" in s8_html
    assert "大戶連增倉" in s8_html


def test_build_section8_splits_increasing_and_decreasing_columns():
    """streak>0進連增倉欄、streak<0進連減倉欄，這個既有分組邏輯不能因為改卡片渲染
    就跑掉。"""
    from export.chips_generator import _build_section8
    shareholder_data = [
        {"stock_id": "A", "stock_name": "增股", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 60.0, "week_chg": 1.0, "streak": 2,
         "share_chg": 0, "lv15_pct": 0.0, "date": "2026-07-17", "trend": []},
        {"stock_id": "B", "stock_name": "減股", "meta_sector": "測試", "close": 10.0,
         "change_pct": 0.0, "lv12_15_pct": 40.0, "week_chg": -1.0, "streak": -2,
         "share_chg": 0, "lv15_pct": 0.0, "date": "2026-07-17", "trend": []},
    ]
    s8_html, _, _ = _build_section8(shareholder_data, [])

    inc_pos = s8_html.index("增股")
    dec_pos = s8_html.index("減股")
    inc_title_pos = s8_html.index("大戶連增倉")
    dec_title_pos = s8_html.index("大戶連減倉")
    assert inc_title_pos < inc_pos < dec_title_pos < dec_pos
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_generator.py -k "build_section8_uses_card or build_section8_splits" -v`
Expected: FAIL（目前還是輸出舊表格）

- [ ] **Step 3: 修改 `_build_section8()`**

把 `export/chips_generator.py` 裡 `_build_section8()` 函式內組 `s8_html` 的段落（原本呼叫
`_shareholder_table(top_increasing)`/`_shareholder_table(top_decreasing)` 那段）改成：

```python
        s8_html = f"""
<div class="chips-grid">
  <div class="chips-section-half">
    <div class="cs-title">大戶連增倉 Top 30（≥400張，集保）</div>
    {_holder_column_html(top_increasing, direction="inc")}
  </div>
  <div class="chips-section-half">
    <div class="cs-title">大戶連減倉 Top 20</div>
    {_holder_column_html(top_decreasing, direction="dec")}
  </div>
</div>"""
```

（只換 `_shareholder_table(...)` 呼叫成 `_holder_column_html(..., direction=...)`，其餘
`_build_section8()` 邏輯——`sh_increasing`/`sh_decreasing` 篩選排序、`top_increasing`/
`top_decreasing` 切片——完全不動）

- [ ] **Step 4: 新增CSS**

在 `export/chips_generator.py` 的 `_CSS` 常數（`:root{...}` 那個大字串常數）結尾前加入
（沿用既有 `--surface`/`--border`/`--up`/`--down`/`--accent` 等既有token，不新增變數）：

```css
.holder-grid{display:grid;grid-template-columns:1fr;gap:8px}
@media(min-width:640px){.holder-grid{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}}
.holder-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:11px 13px}
.hc-top{display:flex;align-items:baseline;gap:6px}
.hc-rank{font-family:ui-monospace,monospace;font-size:.62rem;color:var(--subtle);flex-shrink:0}
.hc-name{font-weight:700;font-size:.88rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hc-sid{font-family:ui-monospace,monospace;color:var(--subtle);font-size:.64rem}
.hc-meta{font-size:.64rem;color:var(--subtle);margin-top:1px}
.hc-price{font-family:ui-monospace,monospace;font-weight:700;font-size:.8rem;flex-shrink:0}
.hc-price.up{color:var(--up)}.hc-price.down{color:var(--down)}
.hc-bar-row{display:flex;align-items:center;gap:8px;margin-top:9px}
.hc-divbar{flex:1;height:7px;background:var(--surface-2);border-radius:3px;position:relative;overflow:hidden}
.hc-divbar::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--border-strong)}
.hc-divbar span{position:absolute;top:0;bottom:0;border-radius:2px}
.hc-divbar span.up{left:50%;background:var(--up)}
.hc-divbar span.down{right:50%;background:var(--down)}
.hc-week{font-family:ui-monospace,monospace;font-weight:800;font-size:.66rem;flex-shrink:0;width:46px;
  text-align:center;padding:3px 0;border-radius:8px;border:1px solid}
.hc-week.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
.hc-week.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
.hc-abs{font-family:ui-monospace,monospace;font-size:.64rem;color:var(--subtle);flex-shrink:0;width:38px;text-align:right}
.hc-badges{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap;font-family:ui-monospace,monospace;font-size:.64rem;color:var(--subtle)}
.hc-badges b{color:var(--text);font-weight:700}
.hc-streak-pill{padding:2px 7px;border-radius:8px;font-weight:800;font-size:.62rem;border:1px solid}
.hc-streak-pill.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
.hc-streak-pill.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
.hc-trend{margin-top:8px}
.hc-trend svg{display:block;width:100%;height:auto}
.hc-trend text{font-family:ui-monospace,monospace;font-size:4.2px;fill:var(--subtle)}
.hc-trend .axis-label{text-anchor:end}
.hc-trend .trend-line{fill:none;stroke:var(--muted);stroke-width:1.4}
.hc-trend .trend-area{fill:var(--muted);opacity:.08}
.hc-trend .trend-end{fill:var(--accent)}
.hc-trend.down .trend-line{stroke:var(--down)}
.hc-trend.down .trend-area{fill:var(--down)}
.hc-trend.down .trend-end{fill:var(--down)}
.hc-trend .trend-grid{stroke:var(--border);stroke-width:1;stroke-dasharray:2,2}
.hc-trend-empty{font-size:.68rem;color:var(--subtle);padding:6px 0;font-style:italic}
```

**注意**：先確認 `--surface-2`/`--border-strong`/`--muted`/`--text` 這些 token 在既有 `_CSS`
的 `:root{...}` 裡都已經定義過（前面已經 grep 確認過 `chips_generator.py:542` 那行 `:root{...}`
已經有 `--surface-2`/`--border-strong`/`--muted`/`--text` 等變數），不要重複定義。

- [ ] **Step 5: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_generator.py -v`
Expected: 全部通過（含既有測試——注意 `test_shareholder_table_*` 系列既有測試是測
`_shareholder_table()` 這支函式本身，函式沒被刪除，只是不再被 `_build_section8()`
呼叫，這些既有測試應該繼續 PASS，不需要改）

- [ ] **Step 6: Commit**

```bash
git add export/chips_generator.py
git commit -m "feat(chips-generator): Section8大戶籌碼改用卡片渲染取代13欄表格+補CSS"
```

---

### Task 5: 側欄分頁分組（9個tab分成3組）

**Files:**
- Modify: `export/chips_generator.py`
- Test: `tests/test_chips_generator.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py` 加入：

```python
def test_generate_groups_sidebar_tabs_into_three_clusters(tmp_path):
    """9個tab-btn分成3組(法人動向/特殊型態/持股結構)，既有tab-panel的id/data-tab/
    aria-controls不能因為分組而改變(switchTab() JS邏輯依賴這些屬性)。"""
    output_path = tmp_path / "chips.html"
    generate(
        trade_date=date(2026, 7, 29),
        meta_chips={"外資連買": {}}, stock_chips={"chips_date": "2026-07-29"},
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    assert "法人動向" in html
    assert "特殊型態" in html
    assert "持股結構" in html
    # 既有9個tab按鈕的id/data-tab屬性必須都還在，分組不能動到這些(JS依賴)
    for tab_id in ["signal", "dipbuy", "stealth", "inst", "foreign", "trust", "margin", "holder", "insider"]:
        assert f'id="tab-btn-{tab_id}"' in html
        assert f'data-tab="tab-{tab_id}"' in html
        assert f'aria-controls="tab-{tab_id}"' in html
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_generator.py -k groups_sidebar_tabs -v`
Expected: FAIL（目前還是9個按鈕平排，沒有分組標籤文字）

- [ ] **Step 3: 修改側欄 `.tab-bar` 區塊**

在 `export/chips_generator.py::generate()` 內，把原本：

```python
        <div class="tab-bar" role="tablist" aria-label="籌碼分析分類">
          <button id="tab-btn-signal" type="button" role="tab" aria-controls="tab-signal" aria-selected="false" class="tab-btn" data-tab="tab-signal" onclick="switchTab('tab-signal')">法人同步觀察</button>
          <button id="tab-btn-dipbuy" type="button" role="tab" aria-controls="tab-dipbuy" aria-selected="false" class="tab-btn" data-tab="tab-dipbuy" onclick="switchTab('tab-dipbuy')">越跌越買</button>
          <button id="tab-btn-stealth" type="button" role="tab" aria-controls="tab-stealth" aria-selected="false" class="tab-btn" data-tab="tab-stealth" onclick="switchTab('tab-stealth')">外資偷偷買</button>
          <button id="tab-btn-inst" type="button" role="tab" aria-controls="tab-inst" aria-selected="false" class="tab-btn" data-tab="tab-inst" onclick="switchTab('tab-inst')">法人買賣</button>
          <button id="tab-btn-foreign" type="button" role="tab" aria-controls="tab-foreign" aria-selected="false" class="tab-btn" data-tab="tab-foreign" onclick="switchTab('tab-foreign')">外資籌碼</button>
          <button id="tab-btn-trust" type="button" role="tab" aria-controls="tab-trust" aria-selected="false" class="tab-btn" data-tab="tab-trust" onclick="switchTab('tab-trust')">投信籌碼</button>
          <button id="tab-btn-margin" type="button" role="tab" aria-controls="tab-margin" aria-selected="false" class="tab-btn" data-tab="tab-margin" onclick="switchTab('tab-margin')">融資警示</button>
          <button id="tab-btn-holder" type="button" role="tab" aria-controls="tab-holder" aria-selected="false" class="tab-btn" data-tab="tab-holder" onclick="switchTab('tab-holder')">大戶籌碼</button>
          <button id="tab-btn-insider" type="button" role="tab" aria-controls="tab-insider" aria-selected="false" class="tab-btn" data-tab="tab-insider" onclick="switchTab('tab-insider')">董監持股</button>
        </div>
```

改成（`role="tablist"` 從外層 `.tab-bar` 移到最外層 `.tab-groups` 容器，維持整體只有一個
tablist landmark；每個按鈕的 `id`/`data-tab`/`aria-controls`/`onclick` 完全不動）：

```python
        <div class="tab-groups" role="tablist" aria-label="籌碼分析分類">
          <div class="tab-group">
            <span class="tab-group-label">法人動向</span>
            <div class="tab-bar">
              <button id="tab-btn-signal" type="button" role="tab" aria-controls="tab-signal" aria-selected="false" class="tab-btn" data-tab="tab-signal" onclick="switchTab('tab-signal')">法人同步觀察</button>
              <button id="tab-btn-foreign" type="button" role="tab" aria-controls="tab-foreign" aria-selected="false" class="tab-btn" data-tab="tab-foreign" onclick="switchTab('tab-foreign')">外資籌碼</button>
              <button id="tab-btn-trust" type="button" role="tab" aria-controls="tab-trust" aria-selected="false" class="tab-btn" data-tab="tab-trust" onclick="switchTab('tab-trust')">投信籌碼</button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">特殊型態</span>
            <div class="tab-bar">
              <button id="tab-btn-dipbuy" type="button" role="tab" aria-controls="tab-dipbuy" aria-selected="false" class="tab-btn" data-tab="tab-dipbuy" onclick="switchTab('tab-dipbuy')">越跌越買</button>
              <button id="tab-btn-stealth" type="button" role="tab" aria-controls="tab-stealth" aria-selected="false" class="tab-btn" data-tab="tab-stealth" onclick="switchTab('tab-stealth')">外資偷偷買</button>
              <button id="tab-btn-margin" type="button" role="tab" aria-controls="tab-margin" aria-selected="false" class="tab-btn" data-tab="tab-margin" onclick="switchTab('tab-margin')">融資警示</button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">持股結構</span>
            <div class="tab-bar">
              <button id="tab-btn-inst" type="button" role="tab" aria-controls="tab-inst" aria-selected="false" class="tab-btn" data-tab="tab-inst" onclick="switchTab('tab-inst')">法人買賣</button>
              <button id="tab-btn-holder" type="button" role="tab" aria-controls="tab-holder" aria-selected="false" class="tab-btn" data-tab="tab-holder" onclick="switchTab('tab-holder')">大戶籌碼</button>
              <button id="tab-btn-insider" type="button" role="tab" aria-controls="tab-insider" aria-selected="false" class="tab-btn" data-tab="tab-insider" onclick="switchTab('tab-insider')">董監持股</button>
            </div>
          </div>
        </div>
```

**注意**：「法人買賣」（`tab-inst`）從原本邏輯上比較接近「法人動向」的位置，這裡歸進
「持股結構」組——維持跟 mockup 定案版一致的分組（mockup 的3組是：法人動向=法人同步觀察/
外資籌碼/投信籌碼，特殊型態=越跌越買/外資偷偷買/融資警示，持股結構=法人買賣/大戶籌碼/
董監持股），照抄不要自己重新分類。

在 `_CSS` 常數加入分組樣式：

```css
.tab-groups{display:flex;flex-direction:column;gap:14px}
.tab-group{display:flex;flex-direction:column;gap:4px}
.tab-group-label{font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;color:var(--subtle);padding-left:2px}
```

- [ ] **Step 4: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_generator.py -v`
Expected: 全部通過

- [ ] **Step 5: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips-generator): 側欄9個分頁分成3組(法人動向/特殊型態/持股結構)"
```

---

### Task 6: `export/chips_headline.py` — 候選觀察卡片

**Files:**
- Create: `export/chips_headline.py`
- Test: `tests/test_chips_headline.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_chips_headline.py`：

```python
from export.chips_headline import build_candidate_cards, render_headline_zone


def test_build_candidate_cards_uses_rank_joint_buy_candidates_output():
    """候選觀察卡片必須是rank_joint_buy_candidates()的輸出前3名，不是重新排序。"""
    from screener.institutional import rank_joint_buy_candidates
    inst_scan = [
        {"stock_id": "2317", "stock_name": "鴻海", "meta_sector": "AI伺服器",
         "close": 257.0, "change_pct": 2.4, "foreign_streak": 5, "trust_streak": 3,
         "both_streak": 3, "foreign_net": 24000000, "trust_net": 559000,
         "total_net": 25000000, "institutional_flow_ratio_pct": 39.3,
         "price_cum_pct": 8.5, "volume": 50000},
        {"stock_id": "8114", "stock_name": "振樺電", "meta_sector": "工業電腦",
         "close": 232.0, "change_pct": 5.0, "foreign_streak": 4, "trust_streak": 2,
         "both_streak": 2, "foreign_net": 390000, "trust_net": 108000,
         "total_net": 497000, "institutional_flow_ratio_pct": 12.4,
         "price_cum_pct": 6.2, "volume": 8000},
    ]
    expected = rank_joint_buy_candidates(inst_scan, limit=3)

    cards = build_candidate_cards(inst_scan, limit=3)

    assert [c["stock_id"] for c in cards] == [r["stock_id"] for r in expected]


def test_build_candidate_cards_returns_empty_list_when_no_candidates():
    assert build_candidate_cards([], limit=3) == []


def test_render_headline_zone_includes_disclosure_text():
    """誠實揭露文案是強制要求(Global Constraints)，不能被省略。"""
    html = render_headline_zone(candidate_cards=[], holder_focus=[])
    assert "不是投資建議" in html
    assert "尚未完成" in html or "未完成" in html


def test_render_headline_zone_shows_empty_state_when_no_candidates():
    """今天沒有符合條件的候選時，顯示誠實的空狀態文字，不是留空白區塊。"""
    html = render_headline_zone(candidate_cards=[], holder_focus=[])
    assert "無符合條件" in html or "今日無" in html


def test_render_headline_zone_escapes_malicious_stock_name():
    html = render_headline_zone(
        candidate_cards=[{
            "stock_id": "9999", "stock_name": "<script>alert(1)</script>",
            "meta_sector": "測試", "close": 10.0, "change_pct": 1.0,
            "both_streak": 3, "institutional_flow_ratio_pct": 5.0,
            "price_cum_pct": 3.0, "total_net": 1000,
        }],
        holder_focus=[],
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_headline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'export.chips_headline'`

- [ ] **Step 3: 建立 `export/chips_headline.py`**

```python
"""
籌碼頁（docs/chips.html）今日焦點 headline zone
設計依據：docs/superpowers/mockups/2026-07-23-chips-v3-final.html（定案版）
實作計畫：docs/superpowers/plans/2026-07-29-chips-headline-and-holder-redesign.md

候選觀察卡片資料源是既有 screener/institutional.py::rank_joint_buy_candidates()（跟
export/chips_generator.py::_build_section6() 的「法人同步買超觀察」完整榜單同一份資料，
只是這裡只取前3名、用更大的視覺呈現），不是重新設計一套排序邏輯。

⚠️ 誠實揭露原則：候選觀察是條件篩選出的觀察名單，籌碼策略的配對組/bootstrap/樣本外驗證
（見 debug-tasks.md「桌電待驗：籌碼策略是否真的有增益」）都還沒做完，UI 文案不能暗示這是
已證實有效的投資建議。render_headline_zone() 的揭露文字是強制項，修改時不要拿掉。
"""
from html import escape as _html_escape
from typing import Any, Dict, List

from screener.institutional import rank_joint_buy_candidates


def _esc(value) -> str:
    return _html_escape(str(value)) if value else ""


def build_candidate_cards(inst_scan: List[dict], limit: int = 3) -> List[dict]:
    """候選觀察卡片資料，直接沿用 rank_joint_buy_candidates() 的排序結果，只是限制筆數
    給headline zone用（完整榜單仍在「法人同步觀察」分頁）。"""
    return rank_joint_buy_candidates(inst_scan, limit=limit)


def _candidate_card_html(row: dict, rank: int) -> str:
    price_pct = row.get("change_pct")
    price_pct_str = f"{price_pct:+.1f}%" if price_pct is not None else "─"
    flow_ratio = row.get("institutional_flow_ratio_pct")
    flow_str = f"{flow_ratio:.2f}%" if flow_ratio is not None else "─"
    price_cum = row.get("price_cum_pct")
    price_cum_str = f"{price_cum:+.1f}%" if price_cum is not None else "─"
    both_streak = row.get("both_streak") or 0
    total_net = row.get("total_net") or 0
    total_net_lots = round(total_net / 1000)

    cls = "primary" if rank == 1 else ""
    return f"""<div class="pick-row {cls}">
  <span class="pr-rank">{rank}</span>
  <div>
    <span class="pr-name">{_esc(row.get('stock_name', ''))}<span class="pr-sid">{_esc(row['stock_id'])}</span></span>
    <div class="pr-evidence">{_esc(row.get('meta_sector', ''))} · 連買{both_streak}日 · 淨買{total_net_lots:+,}張 · 買超占量{flow_str}</div>
  </div>
  <div class="pr-pct">{price_cum_str}<span class="lbl">10日</span></div>
</div>"""


def render_headline_zone(candidate_cards: List[dict], holder_focus: List[dict]) -> str:
    """組裝完整的「今日焦點」headline zone：候選觀察 + 大戶持倉本週焦點，兩欄並排。"""
    if not candidate_cards:
        candidate_html = '<div class="detail-empty">今日無符合條件的候選（篩選條件：連買≥2日、成交量≥500張、買超占量≥0.1%、10日價格不弱於0%）</div>'
    else:
        candidate_html = "".join(
            _candidate_card_html(row, i + 1) for i, row in enumerate(candidate_cards)
        )

    if not holder_focus:
        holder_html = '<div class="detail-empty">今日無資料</div>'
    else:
        rows_html = []
        for row in holder_focus[:5]:
            week_chg = row.get("week_chg") or 0.0
            direction = "up" if week_chg >= 0 else "down"
            max_abs = max((abs(r.get("week_chg") or 0) for r in holder_focus[:5]), default=1.0) or 1.0
            bar_pct = abs(week_chg) / max_abs * 50
            rows_html.append(f"""<div class="holder-mini-row">
  <span class="hm-name">{_esc(row.get('stock_name', ''))}</span>
  <div class="hm-divbar"><span class="{direction}" style="width:{bar_pct:.1f}%"></span></div>
  <span class="hm-delta {direction}">{week_chg:+.1f}%</span>
  <span class="hm-abs">{row.get('lv12_15_pct', 0):.1f}%</span>
</div>""")
        holder_html = "".join(rows_html)

    return f"""<div class="hero">
  <div class="hero-panel">
    <div class="hero-head"><h2>候選觀察</h2><span class="count">法人同步觀察 · {len(candidate_cards)}檔</span></div>
    <div class="disclosure"><span><b>條件篩選觀察名單，非投資建議。</b>排序邏輯尚未完成配對組／統計顯著性驗證，命中率無法保證優於隨機選股。</span></div>
    {candidate_html}
    <div class="hero-footnote">篩選條件：連買≥2日、成交量≥500張、買超占量≥0.1%、10日價格不弱於0%。完整榜單見「法人同步觀察」分頁。</div>
  </div>
  <div class="hero-panel">
    <div class="hero-head"><h2>大戶持倉本週焦點</h2><span class="count">400張以上大戶% 週變化 Top5</span></div>
    {holder_html}
    <div class="hero-footnote">完整增倉/減倉榜單見「大戶籌碼」分頁。</div>
  </div>
</div>"""
```

- [ ] **Step 4: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_headline.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add export/chips_headline.py tests/test_chips_headline.py
git commit -m "feat(chips-headline): 新建export/chips_headline.py，候選觀察卡片沿用rank_joint_buy_candidates()真實資料"
```

---

### Task 7: 接線進 `chips_generator.py::generate()` + CSS

**Files:**
- Modify: `export/chips_generator.py`
- Test: `tests/test_chips_generator.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_chips_generator.py` 加入：

```python
def test_generate_includes_headline_zone(tmp_path):
    output_path = tmp_path / "chips.html"
    inst_scan = [{
        "stock_id": "2317", "stock_name": "鴻海", "meta_sector": "AI伺服器",
        "close": 257.0, "change_pct": 2.4, "foreign_streak": 5, "trust_streak": 3,
        "both_streak": 3, "foreign_net": 24000000, "trust_net": 559000,
        "total_net": 25000000, "institutional_flow_ratio_pct": 39.3,
        "price_cum_pct": 8.5, "volume": 50000,
    }]
    generate(
        trade_date=date(2026, 7, 29),
        meta_chips={"外資連買": {}}, stock_chips={"chips_date": "2026-07-29"},
        inst_scan=inst_scan, output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    assert "候選觀察" in html
    assert "大戶持倉本週焦點" in html
    assert "鴻海" in html
    assert "不是投資建議" in html


def test_generate_headline_zone_uses_shareholder_data_for_holder_focus(tmp_path):
    output_path = tmp_path / "chips.html"
    shareholder_data = [{
        "stock_id": "5347", "stock_name": "世界先進", "meta_sector": "晶圓代工",
        "close": 128.5, "change_pct": 1.2, "lv12_15_pct": 68.4, "week_chg": 2.1,
        "streak": 6, "share_chg": 412000, "lv15_pct": 22.6, "date": "2026-07-29",
        "trend": [],
    }]
    generate(
        trade_date=date(2026, 7, 29),
        meta_chips={"外資連買": {}}, stock_chips={"chips_date": "2026-07-29"},
        shareholder_data=shareholder_data, output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    hero_idx = html.index("大戶持倉本週焦點")
    tab_holder_idx = html.index('id="tab-holder"')
    stock_positions = [m for m in range(len(html)) if html.startswith("世界先進", m)]
    assert any(hero_idx < p < tab_holder_idx for p in stock_positions), \
        "大戶持倉本週焦點應該顯示shareholder_data裡的股票，且要出現在hero zone(tab-holder之前)"
```

- [ ] **Step 2: 執行測試，確認 FAIL**

Run: `python -m pytest tests/test_chips_generator.py -k "headline_zone" -v`
Expected: FAIL（目前 `<main>` 裡沒有 headline zone）

- [ ] **Step 3: 接線**

在 `export/chips_generator.py` 檔案頂部 import 區塊加入：

```python
from export.chips_headline import build_candidate_cards, render_headline_zone
```

在 `generate()` 函式內，找到組 `s6a_html, s6_foreign_html, s6_trust_html = _build_section6(inst_scan)`
那一行後面加入：

```python
    candidate_cards = build_candidate_cards(inst_scan, limit=3)
    holder_focus_sorted = sorted(
        shareholder_data, key=lambda r: -abs(r.get("week_chg") or 0)
    )[:5]
    headline_html = render_headline_zone(candidate_cards, holder_focus_sorted)
```

在 `<main id="main-content" ...>` 開始標籤後、`{exch_filter_btns}` 前面插入 `{headline_html}`：

原本：
```python
    <main id="main-content" class="main-content" tabindex="-1">
      {exch_filter_btns}
```

改成：
```python
    <main id="main-content" class="main-content" tabindex="-1">
      {headline_html}
      {exch_filter_btns}
```

- [ ] **Step 4: 新增headline zone的CSS**

在 `_CSS` 常數加入（沿用既有 `--surface`/`--border`/`--border-strong`/`--accent`/
`--accent-soft`/`--caution`/`--caution-soft`/`--up`/`--down`/`--text`/`--muted`/`--subtle`
token，這些應該在既有 `:root{...}` 都已定義；`--caution`/`--caution-soft` 若尚未定義
需要一併加進 `:root{...}`，值用 `--caution:#6E8CB0;--caution-soft:rgba(110,140,176,.16)`）：

```css
.hero{display:grid;grid-template-columns:1.2fr 1fr;gap:14px;padding:16px 20px;margin-bottom:8px}
@media(max-width:980px){.hero{grid-template-columns:1fr}}
.hero-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
.hero-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px}
.hero-head h2{font-size:.92rem;font-weight:700;margin:0}
.hero-head .count{font-size:.66rem;color:var(--subtle);font-family:ui-monospace,monospace}
.disclosure{display:flex;gap:7px;padding:8px 0 12px;font-size:.7rem;color:var(--muted);border-bottom:1px solid var(--border);margin-bottom:10px}
.disclosure b{color:var(--caution);font-weight:700}
.pick-row{display:grid;grid-template-columns:16px 1fr auto;gap:10px;align-items:center;padding:9px 0 9px 8px;border-left:2px solid transparent;border-bottom:1px solid var(--border)}
.pick-row:last-child{border-bottom:none}
.pick-row.primary{border-left-color:var(--accent);background:var(--accent-soft)}
.pr-rank{font-family:ui-monospace,monospace;font-size:.66rem;color:var(--subtle)}
.pr-name{font-weight:700;font-size:.86rem}
.pr-sid{font-family:ui-monospace,monospace;color:var(--subtle);font-size:.68rem;margin-left:5px;font-weight:400}
.pr-evidence{font-size:.68rem;color:var(--subtle);font-family:ui-monospace,monospace;margin-top:2px}
.pr-pct{font-family:ui-monospace,monospace;font-weight:700;font-size:.88rem;color:var(--up);text-align:right}
.pr-pct .lbl{display:block;font-size:.58rem;color:var(--subtle);font-weight:400}
.hero-footnote{padding-top:12px;font-size:.66rem;color:var(--subtle)}
.holder-mini-row{display:grid;grid-template-columns:76px 1fr 46px 50px;gap:8px;align-items:center;padding:6px 0}
.hm-name{font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hm-divbar{height:6px;background:var(--surface-2);border-radius:2px;position:relative;overflow:hidden}
.hm-divbar span{position:absolute;top:0;bottom:0;border-radius:2px}
.hm-divbar span.up{left:50%;background:var(--up)}
.hm-divbar span.down{right:50%;background:var(--down)}
.hm-delta{font-family:ui-monospace,monospace;font-weight:700;font-size:.7rem;text-align:center;padding:2px 0;border-radius:8px;border:1px solid}
.hm-delta.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
.hm-delta.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
.hm-abs{font-family:ui-monospace,monospace;font-size:.66rem;color:var(--subtle);text-align:right}
.detail-empty{color:var(--subtle);font-size:.8rem;padding:16px 0;font-style:italic}
```

- [ ] **Step 5: 執行測試，確認 PASS**

Run: `python -m pytest tests/test_chips_generator.py tests/test_chips_headline.py -v`
Expected: 全部通過

- [ ] **Step 6: Commit**

```bash
git add export/chips_generator.py
git commit -m "feat(chips-generator): 接線headline zone進generate()，插在main開頭"
```

---

### Task 8: `main.py` 接線 — 傳入週趨勢資料

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 呼叫 `get_shareholder_trend()` 並合併進 `sh_rows`**

在 `main.py`，找到 `sh_rows = []` 那段迴圈組裝邏輯（約第836-882行，`for _, row in sh_df.iterrows(): ... sh_rows.append({...})`）之前加入：

```python
                try:
                    from screener.database import get_shareholder_trend
                    _trend_map = get_shareholder_trend(weeks=5)
                except Exception:
                    _trend_map = {}
```

在 `sh_rows.append({...})` 那個 dict 字面值裡（緊接在既有 `"lv15_chg": ...,` 那一行後面）
加入一個新欄位：

```python
                        "trend": _trend_map.get(sid, []),
```

- [ ] **Step 2: 語法檢查**

Run: `python -c "import main"`
Expected: 無錯誤

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(main): 呼叫get_shareholder_trend()，把近5週趨勢資料合併進sh_rows供卡片走勢圖使用"
```

---

### Task 9: 全套件驗證 + 死碼確認

**Files:** 無新增/修改檔案，純驗證步驟

- [ ] **Step 1: 確認 `_shareholder_table()` 是否變成死碼**

Run: `grep -n "_shareholder_table(" export/chips_generator.py`

Expected：只剩函式自己的定義那一行，`_build_section8()` 內的呼叫已經在 Task 4 換成
`_holder_column_html()`。**不要刪除 `_shareholder_table()` 函式本身**——`tests/test_chips_generator.py`
既有的 `test_shareholder_table_*` 系列測試還在測這支函式，直接刪除函式會讓那些測試失敗；
這次任務範圍是「新增卡片渲染路徑」，不是「刪除舊表格渲染函式」，死碼清理是獨立的後續任務。

- [ ] **Step 2: 全專案測試套件**

Run: `python -m pytest -q`
Expected: 這個 debug worktree 應該全數 PASS，除了既有已知限制
`test_scan_patterns_returns_list`（需要本機 `data/screener.db`）。

- [ ] **Step 3: 交給 Debugger 的真實資料複查清單**

因為這個 debug worktree 沒有 `data/screener.db`，以下項目需要 Cody 桌電跑一次
`python main.py` 後才能真的複查：

1. `docs/chips.html` headline zone 是否正確顯示今日真實的候選觀察（跟「法人同步觀察」
   分頁的完整榜單前3名比對，應該一致）
2. 大戶持倉本週焦點迷你面板的5檔是否正確（依 `|week_chg|` 降冪排序前5名）
3. 大戶籌碼分頁的卡片化渲染：連增倉/連減倉兩欄是否正確、發散長條方向跟數字對得起來、
   近5週趨勢走勢圖的Y軸/X軸文字是否對齊（不要只看程式碼，實際瀏覽器縮放看一次）
4. 側欄9個分頁分成3組後，點擊切換分頁功能是否正常（分組是純視覺重排，理論上不影響
   `switchTab()` 邏輯，但要實際點過確認）
5. 誠實揭露文案「這是條件篩選出的觀察名單，不是投資建議」是否清楚可見，不會被其他
   元素遮住或不小心被使用者忽略

- [ ] **Step 4: 更新 `debug-tasks.md`**

在檔案最上面新增一則條目，說明這次完成的範圍（headline zone、側欄分組、大戶持倉卡片化）
以及上面第3步的複查清單，附上 mockup 連結供對照。

- [ ] **Step 5: Commit**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 記錄籌碼頁今日焦點+大戶持倉卡片化完成，附桌電真實資料複查清單"
```

---

## Self-Review（against mockup v3-final）

- ✅ 候選觀察 headline zone + 誠實揭露文案（Task 6/7）——資料源確認沿用既有
  `rank_joint_buy_candidates()`，不是重新設計排序
- ✅ 大戶持倉本週焦點迷你面板（Task 6/7）——沿用 `shareholder_data`，依 `|week_chg|`
  排序取前5
- ✅ 側欄9個分頁分3組（Task 5）——確認3組分類跟 mockup 定案版一致（法人動向/特殊型態/
  持股結構），既有 `tab-panel` id/`switchTab()` 邏輯不變
- ✅ 大戶持倉卡片化：發散長條(週變化%非絕對水位)+pill標籤+近5週趨勢SVG（Task 2/3/4）——
  viewBox座標配置照 mockup 修過對齊bug後的最終版本（單一SVG座標系統，不用HTML flex row
  猜對齊）
- ✅ 維持「連增倉/連減倉」兩張獨立清單，不混排（Task 4）——跟現行 production 結構一致
- ✅ 趨勢圖資料筆數誠實反映實際歷史深度，不寫死5筆（Task 1/2）——`get_shareholder_trend()`
  用 `weeks` 當上限不是硬性要求，`_calc_trend_svg()` 依實際筆數動態算x座標間距

沒有發現遺漏 mockup 條目，也沒發現函式簽章跨 Task 不一致（`_calc_trend_svg()` 回傳的
`dict` 欄位名稱 `line_points`/`area_points`/`x_labels`/`y_max_label`/`y_min_label`/
`end_point` 在 Task 2 定義、Task 3 `_holder_card_html()` 引用，欄位名稱一致）。
