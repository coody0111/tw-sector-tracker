# 大盤分級儀表板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**狀態：✅ Phase 1 已完成**（2026-07-10 事後確認）。`scrapers/taiex.py`、
`export/html_generator.py::_market_regime_section()`、`market_regime` 參數都已在 code 裡確認
存在，且 Debugger 已在 `bug-reports.md`（2026-07-09 驗證條目，148 passed）驗證通過核心邏輯。
下方 checkbox 未逐項補勾，非待辦。門檻回測與真實頁面目視仍是開放項（見 bug-reports 該條目）。

**Goal:** 在 `docs/index.html` 最上方新增大盤分級儀表板，兩條獨立軸線：(1) 五級大盤方向（指數漲跌 + 個股廣度綜合判斷）(2) 資金集中度診斷（權值股 vs 非權值股漲跌落差），並把筆記（`notes/動能派學習筆記.md`）裡對應每一級的操作提示顯示出來。

**Architecture:** 新增 TAIEX 指數 scraper（比照 `scrapers/twse.py` 既有的 `TWSEBlockedError` 封鎖偵測模式）；`processors/performance.py` 新增廣度/集中度計算函式；`config.py` 新增固定的權值股清單常數；`main.py` 串接呼叫並傳給 `export/html_generator.py` 渲染新區塊。全部沿用既有的「Python 直接產生 HTML」架構，不涉及前端框架。

**設計文件：** `docs/superpowers/specs/2026-07-09-market-regime-dashboard-design.md`（門檻數字、兩軸設計理由、筆記對應表都在裡面，這裡不重複）

---

## 檔案結構總覽

- 新增：`scrapers/taiex.py` — 抓 TWSE 官方加權指數
- 修改：`config.py` — 新增 `TAIEX_HEAVYWEIGHTS`（權值股清單常數）
- 修改：`processors/performance.py` — 新增 `calc_market_breadth()`、`calc_capital_concentration()`、`classify_market_regime()`
- 修改：`main.py` — 串接呼叫，傳給 `generate_html()`
- 修改：`export/html_generator.py` — 新增儀表板區塊渲染函式
- 新增：`tests/test_taiex.py`、對應測試加進 `tests/test_processors.py`、`tests/test_html_generator.py`

---

### Task 1: `scrapers/taiex.py` — 抓 TWSE 加權指數

**Files:**
- New: `scrapers/taiex.py`
- Test: `tests/test_taiex.py`

**要做的事：**
- `fetch_taiex_index(trade_date: date) -> dict`，回傳 `{date, close, change, change_pct}`
- 查證 TWSE 官方每日大盤指數的公開 API endpoint（`www.twse.com.tw` 底下，比照 `STOCK_DAY_ALL`／`T86` 的風格，應該有對應大盤指數的 endpoint，實作前先用瀏覽器 F12 確認實際 URL 跟回應格式）
- 比照 `scrapers/twse.py::fetch_daily_prices()` 的封鎖偵測：用 `from scrapers.chips import TWSEBlockedError`，content-type 不是預期格式／解析失敗一律當擋頁處理，不要吞掉錯誤

**Step 1: Write the failing test**

```python
# tests/test_taiex.py
from datetime import date
from scrapers.taiex import _parse_taiex_response  # 純解析函式，不含網路

def test_parse_taiex_response_extracts_close_and_change():
    # 用實際查到的回應格式建構 fixture（實作時先手動打一次 API 確認格式再補這個測試）
    ...

def test_parse_taiex_response_raises_on_block_page():
    from scrapers.chips import TWSEBlockedError
    import pytest
    with pytest.raises(TWSEBlockedError):
        _parse_taiex_response("<html>因為安全性考量...</html>", content_type="text/html")
```

- [x] Step 1: 先用瀏覽器/`curl`/`requests` 手動打一次 TWSE 大盤指數 API，確認實際 endpoint 跟回應格式（json 還是 csv，欄位長怎樣）
- [x] Step 2: 依照實測結果寫 `_parse_taiex_response()` 的測試（含正常回應跟擋頁兩種情境）
- [x] Step 3: 跑測試確認 FAIL
- [x] Step 4: 實作 `fetch_taiex_index()` + `_parse_taiex_response()`
- [x] Step 5: 跑測試確認 PASS
- [x] Step 6: 對真實 API 手動測一次，確認資料抓得到、格式跟預期一致

---

### Task 2: `config.py` — 權值股清單常數

**Files:**
- Modify: `config.py`

- [x] Step 1: 新增 `TAIEX_HEAVYWEIGHTS: list[str]`，TAIEX 市值前 10-20 大成分股的 `stock_id`（台積電 2330、鴻海 2317、聯發科 2454、台達電 2308...等，實作時查證正確清單跟排序，不要憑記憶亂填）
- [x] Step 2: 加註解說明這份清單需要定期（建議半年）review 更新，因為市值排名會變動

---

### Task 3: `processors/performance.py` — 廣度與集中度計算

**Files:**
- Modify: `processors/performance.py`
- Test: `tests/test_processors.py`

**函式簽名：**
```python
def calc_market_breadth(prices_df: pd.DataFrame) -> dict:
    """回傳 {up_count, down_count, flat_count, total, breadth_ratio}
    breadth_ratio = up_count / total，對『個股』計算，不是族群平均。"""

def calc_capital_concentration(
    prices_df: pd.DataFrame,
    heavyweight_ids: list[str],
) -> dict:
    """回傳 {heavyweight_avg_pct, broad_avg_pct, divergence}
    divergence = heavyweight_avg_pct - broad_avg_pct（可正可負）。"""

def classify_market_regime(
    taiex_change_pct: float,
    breadth_ratio: float,
    divergence: float,
    concentration_threshold: float = 2.0,
) -> dict:
    """回傳 {tier, is_concentrated, concentration_direction}
    tier ∈ {"大漲","小漲","持平","小跌","大跌"}
    concentration_direction ∈ {None, "權值股撐盤", "中小型輪動"}"""
```

**Step 1: Write the failing tests**（對照設計文件的門檻表寫測試，涵蓋：五級各自的邊界值、指數與廣度矛盾時退回持平、集中度診斷兩個方向都要測）

- [x] Step 1: 寫 `calc_market_breadth` 測試（含 0 檔/全漲/全跌邊界情況）
- [x] Step 2: 寫 `calc_capital_concentration` 測試（權值股領漲、非權值股領漲兩種情境都要）
- [x] Step 3: 寫 `classify_market_regime` 測試（五級邊界值各測一次；指數落在「小漲」但廣度 <50% 時應該退回「持平」；集中度超過門檻時 `is_concentrated=True`）
- [x] Step 4: 跑測試確認全部 FAIL
- [x] Step 5: 實作三個函式
- [x] Step 6: 跑測試確認全部 PASS

---

### Task 4: `main.py` 串接

**Files:**
- Modify: `main.py`

- [x] Step 1: `run()` 裡呼叫 `fetch_taiex_index()`（比照現有 TWSE 呼叫的 try/except 模式：`TWSEBlockedError` 個別處理、當天無資料時 fallback 前一交易日，不要讓大盤指數抓取失敗擋掉整個每日流程）
- [x] Step 2: 呼叫 `calc_market_breadth()`、`calc_capital_concentration()`、`classify_market_regime()`，組成 `market_regime` dict
- [x] Step 3: 傳給 `generate_html(...)` 多一個 `market_regime=market_regime` 參數
- [x] Step 4: 抓取失敗時的 fallback：`market_regime=None`，`html_generator.py` 那邊要處理這個區塊完全不顯示的情況（不要讓缺這個資料就讓整頁 crash）

---

### Task 5: `export/html_generator.py` 渲染儀表板區塊

**Files:**
- Modify: `export/html_generator.py`
- Test: `tests/test_html_generator.py`

**Step 1: Write the failing test**
```python
def test_market_regime_section_renders_tier_and_concentration():
    html = _market_regime_section({
        "tier": "小漲", "taiex_change_pct": 0.6,
        "breadth_ratio": 0.48, "is_concentrated": True,
        "concentration_direction": "權值股撐盤",
        "heavyweight_avg_pct": 2.1, "broad_avg_pct": -0.8,
    })
    assert "小漲" in html
    assert "權值股撐盤" in html
    # _esc() 跳脫要套用（比照 2026-07-05 那次 XSS 修復的慣例，這裡雖然是內部算出來的
    # 數值/固定字串、不是外部字串，但維持一致的呼叫慣例，之後要是有動態文字比較不會漏改）

def test_market_regime_section_handles_none_gracefully():
    html = _market_regime_section(None)
    assert html == "" or "無資料" in html  # 抓取失敗時不能讓整頁掛掉
```

- [x] Step 1: 寫測試（含 `market_regime=None` 的防呆情境）
- [x] Step 2: 跑測試確認 FAIL
- [x] Step 3: 實作 `_market_regime_section()`，包含：五級標籤 + 對應顏色、集中度診斷（權值股/非權值股數字並排顯示）、對應筆記操作提示文字（設計文件裡的對照表）
- [x] Step 4: 接進 `generate()` 主函式，放在最上方（族群排行榜之上）
- [x] Step 5: 跑測試確認 PASS
- [x] Step 6: 用合成資料跑一次 `generate()`，肉眼確認渲染出來的 HTML 視覺上合理

---

### Task 6: 端到端驗證

- [x] Step 1: 全專案測試都過
- [x] Step 2: 用真實 `data/screener.db` 跑一次 `python main.py`，確認 `docs/index.html` 正確產出新區塊，數字合理（可以跟當天財經新聞報的大盤漲跌對一下，抓明顯抓錯的情況）
- [x] Step 3: 刻意製造 TAIEX 抓取失敗的情境（例如暫時改錯 URL），確認整頁不會 crash，只是這個區塊不顯示
- [x] Step 4: 交給 Debugger 依 `debug-tasks.md` 慣例驗證：門檻數字合理性、`_esc()` 有沒有漏用、`main.py` 的 fallback 邏輯

---

## 特別注意

- 門檻數字（五級切點、集中度門檻 2.0 個百分點）全部是設計階段的草案，**沒有回測過**，Task 6 端到端驗證時如果發現某天分類結果明顯不合理（例如財經新聞說大跌但這裡顯示小跌），要回頭調整門檻，不要照抄設計文件的數字當成標準答案
- `TAIEX_HEAVYWEIGHTS` 清單需要人工查證，不要用 AI 記憶裡的市值排名亂填，要跟實際的 TAIEX 成分股權重資料核對
- Phase 2（個股五級強弱分類）不在這個 plan 範圍內，等 Phase 1 上線後另外開新的 spec/plan
