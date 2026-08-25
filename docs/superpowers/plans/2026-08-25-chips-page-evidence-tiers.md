# 籌碼頁證據分級改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `docs/chips.html` 9 個 tab 依「訊號有沒有 edge」的回測證據重新分級呈現——加證據徽章、
組內依證據強度重排、拿掉沒有證據支持的「候選觀察」開頁 hero、每個 tab 面板頂部加證據卡/警示
banner。純資訊架構與視覺調整，不改變任何底層資料計算邏輯。

**Architecture:** 全部改動集中在 `export/chips_generator.py` 一個檔案（CSS 字串 `_CSS`、tab nav
靜態 HTML 區塊、`_TAB_JS` 裡的 `_tabs` 陣列、`generate()` 主流程），新增 2 個小型純函式
（`_evidence_card()`/`_evidence_banner()`）產生固定文案的證據卡/banner，數字直接寫死抄自 spec
總表（不是即時計算，回測結果本來就是離線跑 `python main.py --backtest-chips` 才會更新，不隨
每日資料變動）。同步移除不再使用的 `chips_headline` hero 呼叫（模組本身保留，只是不在
`generate()` 主流程呼叫）。

**Tech Stack:** Python 3.11、純字串樣板產生 HTML/CSS/JS（無前端框架，跟專案既有 `chips_generator.py`
風格一致）、pytest。

**Spec:** `docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md`

## Global Constraints

- **不換色票字型系統**：四級證據徽章全部用 `_CSS` 既有 CSS 變數組出（`--accent`/`--muted`+
  `--surface-3`/`--caution`/`--subtle`），不新增任何色相（spec「視覺／資訊架構設計」節）
- **不改變底層資料計算邏輯**：這次只動 HTML/CSS/JS 樣板產生，不碰 `screener/`、`processors/`
  任何計算函式（spec 非目標）
- **證據卡/banner 文案是靜態字串**：數字抄自 spec 總表，不要接資料庫即時查詢——這是回測結果的
  展示，不是頁面日常資料的一部分
- **徽章一律「文字+顏色」雙重編碼**：不能只靠顏色分辨等級（ui-ux-pro-max accessibility
  Color-Only 規則，spec 已載明）
- **tab 分組結構不變**：法人動向／特殊型態／持股結構三組維持，只調整組內順序

---

## File Structure

- Modify: `export/chips_generator.py`
  - `_CSS`（約 670-822 行）：新增證據徽章/證據卡/banner 樣式，改 `.tab-btn` 為 flex 佈局
  - tab nav 靜態 HTML（約 1334-1365 行）：每個 `tab-btn` 加證據徽章 `<span>`，組內重排
  - `_TAB_JS`（約 822-851 行）：`_tabs` 陣列重排、預設 fallback tab 從 `'tab-signal'` 改
    `'tab-margin'`
  - 新增 2 個函式：`_evidence_card()`、`_evidence_banner()`（放在既有 `_section()` helper
    函式群附近，約 131 行後）
  - `generate()`（1254 行起）：8 個 tab 面板插入對應證據卡/banner；移除候選觀察 hero 呼叫
    （`headline_html`/`candidate_cards`/`holder_focus_sorted` 三行區域變數與 import）
- Modify: `tests/test_chips_generator.py`：新增對應斷言

---

### Task 1: CSS — 證據徽章／證據卡／banner 樣式

**Files:**
- Modify: `export/chips_generator.py:699-702`（`.tab-btn` 規則）
- Test: `tests/test_chips_generator.py`

**Interfaces:**
- Produces：CSS class 名稱 `.evid`、`.evid-verified`、`.evid-observe`、`.evid-unproven`、
  `.evid-weak`、`.evid-card`、`.caution-banner`、`.weak-banner`——後續 Task 2/4 直接用這些
  class 名稱，名稱必須完全一致

- [ ] **Step 1: 寫失敗測試，確認新 CSS class 還沒出現在輸出裡**

```python
def test_generate_includes_evidence_tier_css_classes(tmp_path):
    """證據分級的 CSS class 要出現在 <style> 裡，四級徽章+證據卡+兩種banner。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    for cls in (".evid-verified", ".evid-observe", ".evid-unproven", ".evid-weak",
                ".evid-card", ".caution-banner", ".weak-banner"):
        assert cls in html, f"{cls} 應該出現在 <style> 裡"
```

加在 `tests/test_chips_generator.py` 的 `test_generate_uses_actual_chips_date_weekday` 之後。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_chips_generator.py::test_generate_includes_evidence_tier_css_classes -v`
Expected: FAIL（找不到 `.evid-verified` 等 class）

- [ ] **Step 3: 修改 `.tab-btn` 規則為 flex 佈局，容納徽章**

把 `export/chips_generator.py` 第 699 行：

```python
  .tab-btn{width:100%;min-height:44px;padding:9px 11px;border:0;border-left:3px solid transparent;border-radius:6px;background:transparent;color:var(--muted);text-align:left;cursor:pointer;font-size:.8125rem;font-weight:680;transition:background .16s,color .16s,border-color .16s}
```

改成：

```python
  .tab-btn{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;min-height:44px;padding:9px 11px;border:0;border-left:3px solid transparent;border-radius:6px;background:transparent;color:var(--muted);text-align:left;cursor:pointer;font-size:.8125rem;font-weight:680;transition:background .16s,color .16s,border-color .16s}
```

- [ ] **Step 4: 在 `.tab-btn.active` 規則（第 702 行）後面插入新樣式區塊**

```python
  .tab-btn.active{color:var(--text);border-left-color:var(--accent);background:var(--accent-soft)}
  .evid{display:inline-flex;align-items:center;padding:1px 7px;border-radius:9px;font-size:.6rem;font-weight:750;letter-spacing:.02em;white-space:nowrap;flex-shrink:0}
  .evid-verified{background:var(--accent-soft);color:var(--accent);border:1px solid rgba(240,187,85,.35)}
  .evid-observe{background:var(--surface-3);color:var(--muted);border:1px solid var(--border-strong)}
  .evid-unproven{background:var(--caution-soft);color:var(--caution);border:1px solid rgba(110,140,176,.35)}
  .evid-weak{background:transparent;color:var(--subtle);border:1px dashed var(--border)}
  .evid-card{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;margin-bottom:14px;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:6px;font-size:.75rem;color:var(--muted)}
  .evid-card b{color:var(--text);font-variant-numeric:tabular-nums}
  .evid-card .src{margin-left:auto;color:var(--subtle);font-size:.6875rem}
  .caution-banner{margin-bottom:14px;padding:11px 14px;background:var(--caution-soft);border:1px solid rgba(110,140,176,.4);border-radius:6px;color:var(--text);font-size:.75rem}
  .caution-banner b{color:var(--caution)}
  .weak-banner{margin-bottom:14px;padding:11px 14px;background:transparent;border:1px dashed var(--border-strong);border-radius:6px;color:var(--muted);font-size:.75rem}
  .weak-banner b{color:var(--subtle)}
```

（沿用 `docs/superpowers/mockups/2026-08-25-chips-page-evidence-tiers-mockup.html` 已經驗證過
外觀的樣式，直接複製過來，數值不用重新調）

- [ ] **Step 5: 執行測試確認通過**

Run: `pytest tests/test_chips_generator.py::test_generate_includes_evidence_tier_css_classes -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips): 新增證據分級CSS(徽章/證據卡/banner)"
```

---

### Task 2: Tab nav — 加證據徽章、組內依證據強度重排、預設分頁改

**Files:**
- Modify: `export/chips_generator.py:1338-1362`（tab-groups 靜態 HTML）
- Modify: `export/chips_generator.py:840,850`（`_TAB_JS` 的 `_tabs` 陣列與 fallback）
- Test: `tests/test_chips_generator.py`

**Interfaces:**
- Consumes：Task 1 產出的 `.evid-verified`/`.evid-observe`/`.evid-unproven`/`.evid-weak` class
- Produces：無（純樣板），後續 Task 沒有依賴這裡的具體順序，只需維持 tab id 不變
  （`tab-signal`/`tab-foreign`/`tab-trust`/`tab-dipbuy`/`tab-stealth`/`tab-margin`/`tab-inst`/
  `tab-holder`/`tab-insider`——這 9 個 id 完全不動，只動按鈕排列順序跟按鈕內文字）

四級對應（依 spec 總表；「法人買賣」tab 未單獨回測，但跟「外資籌碼」共用同一個外資連買訊號、
只是換成族群層級彙總，故比照「外資籌碼」歸類為 🟡 觀察用——這是本次新做的分類延伸，決策記錄在
這裡）：

| tab id | 顯示文字 | 徽章 class | 徽章文字 |
|---|---|---|---|
| tab-margin | 融資警示 | evid-verified | 已驗證 |
| tab-stealth | 外資偷偷買 | evid-observe | 觀察用 |
| tab-dipbuy | 越跌越買 | evid-weak | 證據偏弱 |
| tab-foreign | 外資籌碼 | evid-observe | 觀察用 |
| tab-trust | 投信籌碼 | evid-observe | 觀察用 |
| tab-signal | 法人同步觀察 | evid-observe | 觀察用 |
| tab-inst | 法人買賣 | evid-observe | 觀察用 |
| tab-holder | 大戶籌碼 | evid-observe | 觀察用 |
| tab-insider | 董監持股 | evid-unproven | 待驗證 |

- [ ] **Step 1: 寫失敗測試，確認新排列順序跟徽章還沒出現**

```python
def test_generate_tab_nav_orders_by_evidence_strength_with_badges(tmp_path):
    """特殊型態組內第一個該是融資警示(已驗證)，法人同步觀察不再是第一個 tab-group 的第一個
    按鈕；每個按鈕都要帶對應的證據徽章。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")

    # 特殊型態組：融資警示排最前面（已驗證優先）
    margin_idx = html.index('data-tab="tab-margin"')
    stealth_idx = html.index('data-tab="tab-stealth"')
    dipbuy_idx = html.index('data-tab="tab-dipbuy"')
    assert margin_idx < stealth_idx < dipbuy_idx

    # 每個 tab 按鈕都帶對應徽章（用 button id 附近的文字片段確認，不是全域計數，
    # 避免不同 tab 剛好同一種徽章互相混淆）。切片區間要照「新排列順序」抓下一個按鈕的
    # id 當結尾，順序是 margin→stealth→dipbuy→foreign→trust→signal→inst→holder→insider——
    # 抓錯順序會讓 start > stop，Python 切出空字串，斷言會誤判過（第一版寫錯過，這裡已修正）。
    margin_btn = html[html.index('id="tab-btn-margin"'):html.index('id="tab-btn-stealth"')]
    assert 'evid-verified' in margin_btn and '已驗證' in margin_btn

    dipbuy_btn = html[html.index('id="tab-btn-dipbuy"'):html.index('id="tab-btn-foreign"')]
    assert 'evid-weak' in dipbuy_btn and '證據偏弱' in dipbuy_btn

    signal_btn = html[html.index('id="tab-btn-signal"'):html.index('id="tab-btn-inst"')]
    assert 'evid-observe' in signal_btn and '觀察用' in signal_btn

    insider_btn = html[html.index('id="tab-btn-insider"'):]
    assert 'evid-unproven' in insider_btn and '待驗證' in insider_btn


def test_generate_default_tab_is_margin_not_signal(tmp_path):
    """預設分頁改成證據最強的融資警示，不再預設開在法人同步觀察。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "switchTab(_tabs.includes(_h)?_h:'tab-margin')" in html
```

加在 Task 1 新增的測試之後。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_chips_generator.py::test_generate_tab_nav_orders_by_evidence_strength_with_badges tests/test_chips_generator.py::test_generate_default_tab_is_margin_not_signal -v`
Expected: FAIL

- [ ] **Step 3: 改寫 tab-groups 靜態 HTML（`export/chips_generator.py` 第 1338-1362 行）**

把整段：

```python
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
```

改成（組內依證據強度重排，組本身順序也把「特殊型態」移到最前面因為它含唯一的 🟢 已驗證項目）：

```python
          <div class="tab-group">
            <span class="tab-group-label">特殊型態</span>
            <div class="tab-bar">
              <button id="tab-btn-margin" type="button" role="tab" aria-controls="tab-margin" aria-selected="false" class="tab-btn" data-tab="tab-margin" onclick="switchTab('tab-margin')"><span>融資警示</span><span class="evid evid-verified">已驗證</span></button>
              <button id="tab-btn-stealth" type="button" role="tab" aria-controls="tab-stealth" aria-selected="false" class="tab-btn" data-tab="tab-stealth" onclick="switchTab('tab-stealth')"><span>外資偷偷買</span><span class="evid evid-observe">觀察用</span></button>
              <button id="tab-btn-dipbuy" type="button" role="tab" aria-controls="tab-dipbuy" aria-selected="false" class="tab-btn" data-tab="tab-dipbuy" onclick="switchTab('tab-dipbuy')"><span>越跌越買</span><span class="evid evid-weak">證據偏弱</span></button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">法人動向</span>
            <div class="tab-bar">
              <button id="tab-btn-foreign" type="button" role="tab" aria-controls="tab-foreign" aria-selected="false" class="tab-btn" data-tab="tab-foreign" onclick="switchTab('tab-foreign')"><span>外資籌碼</span><span class="evid evid-observe">觀察用</span></button>
              <button id="tab-btn-trust" type="button" role="tab" aria-controls="tab-trust" aria-selected="false" class="tab-btn" data-tab="tab-trust" onclick="switchTab('tab-trust')"><span>投信籌碼</span><span class="evid evid-observe">觀察用</span></button>
              <button id="tab-btn-signal" type="button" role="tab" aria-controls="tab-signal" aria-selected="false" class="tab-btn" data-tab="tab-signal" onclick="switchTab('tab-signal')"><span>法人同步觀察</span><span class="evid evid-observe">觀察用</span></button>
            </div>
          </div>
          <div class="tab-group">
            <span class="tab-group-label">持股結構</span>
            <div class="tab-bar">
              <button id="tab-btn-inst" type="button" role="tab" aria-controls="tab-inst" aria-selected="false" class="tab-btn" data-tab="tab-inst" onclick="switchTab('tab-inst')"><span>法人買賣</span><span class="evid evid-observe">觀察用</span></button>
              <button id="tab-btn-holder" type="button" role="tab" aria-controls="tab-holder" aria-selected="false" class="tab-btn" data-tab="tab-holder" onclick="switchTab('tab-holder')"><span>大戶籌碼</span><span class="evid evid-observe">觀察用</span></button>
              <button id="tab-btn-insider" type="button" role="tab" aria-controls="tab-insider" aria-selected="false" class="tab-btn" data-tab="tab-insider" onclick="switchTab('tab-insider')"><span>董監持股</span><span class="evid evid-unproven">待驗證</span></button>
            </div>
          </div>
```

- [ ] **Step 4: 改 `_TAB_JS` 的 `_tabs` 陣列與預設 fallback（第 840、850 行附近）**

把：

```python
const _tabs=['tab-signal','tab-dipbuy','tab-stealth','tab-inst','tab-foreign','tab-trust','tab-margin','tab-holder','tab-insider'];
```

改成（跟新的視覺排列順序一致，Tab/方向鍵循環才會跟畫面上看到的順序對齊）：

```python
const _tabs=['tab-margin','tab-stealth','tab-dipbuy','tab-foreign','tab-trust','tab-signal','tab-inst','tab-holder','tab-insider'];
```

把：

```python
switchTab(_tabs.includes(_h)?_h:'tab-signal');
```

改成：

```python
switchTab(_tabs.includes(_h)?_h:'tab-margin');
```

- [ ] **Step 5: 執行測試確認通過**

Run: `pytest tests/test_chips_generator.py::test_generate_tab_nav_orders_by_evidence_strength_with_badges tests/test_chips_generator.py::test_generate_default_tab_is_margin_not_signal -v`
Expected: PASS

- [ ] **Step 6: 更新既有的分組順序測試 `test_generate_groups_sidebar_tabs_into_three_clusters`**

這個既有測試（`tests/test_chips_generator.py:650`）寫死了改版前的組順序（法人動向→特殊型態→
持股結構）跟組內順序，這次改版後會失敗，不是新 bug。把第 670-690 行：

```python
    label_signal_group = html.index("法人動向")
    label_pattern_group = html.index("特殊型態")
    label_structure_group = html.index("持股結構")
    assert label_signal_group < label_pattern_group < label_structure_group

    pos_signal = html.index('id="tab-btn-signal"')
    pos_foreign = html.index('id="tab-btn-foreign"')
    pos_trust = html.index('id="tab-btn-trust"')
    pos_dipbuy = html.index('id="tab-btn-dipbuy"')
    pos_stealth = html.index('id="tab-btn-stealth"')
    pos_margin = html.index('id="tab-btn-margin"')
    pos_inst = html.index('id="tab-btn-inst"')
    pos_holder = html.index('id="tab-btn-holder"')
    pos_insider = html.index('id="tab-btn-insider"')

    # 法人動向 group的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_signal_group < pos_signal < pos_foreign < pos_trust < label_pattern_group
    # 特殊型態 group的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_pattern_group < pos_dipbuy < pos_stealth < pos_margin < label_structure_group
    # 持股結構 group的按鈕都要落在自己的標籤之後
    assert label_structure_group < pos_inst < pos_holder < pos_insider
```

改成（組順序改成特殊型態→法人動向→持股結構；組內順序依 Task 2 表格重排）：

```python
    label_pattern_group = html.index("特殊型態")
    label_signal_group = html.index("法人動向")
    label_structure_group = html.index("持股結構")
    assert label_pattern_group < label_signal_group < label_structure_group

    pos_margin = html.index('id="tab-btn-margin"')
    pos_stealth = html.index('id="tab-btn-stealth"')
    pos_dipbuy = html.index('id="tab-btn-dipbuy"')
    pos_foreign = html.index('id="tab-btn-foreign"')
    pos_trust = html.index('id="tab-btn-trust"')
    pos_signal = html.index('id="tab-btn-signal"')
    pos_inst = html.index('id="tab-btn-inst"')
    pos_holder = html.index('id="tab-btn-holder"')
    pos_insider = html.index('id="tab-btn-insider"')

    # 特殊型態 group（已驗證優先）的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_pattern_group < pos_margin < pos_stealth < pos_dipbuy < label_signal_group
    # 法人動向 group的按鈕都要落在自己的標籤跟下一組標籤之間
    assert label_signal_group < pos_foreign < pos_trust < pos_signal < label_structure_group
    # 持股結構 group的按鈕都要落在自己的標籤之後（組內順序不變）
    assert label_structure_group < pos_inst < pos_holder < pos_insider
```

- [ ] **Step 7: 跑全部既有測試，確認沒有其他測試意外寫死舊順序**

Run: `pytest tests/test_chips_generator.py -v`
Expected: 全部 PASS。若還有 Step 6 沒抓到的測試因為順序假設失敗，比照 Step 6 的方式更新斷言
（改成符合新順序），不要反過來改回舊順序

- [ ] **Step 8: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips): tab nav加證據徽章+依證據強度重排+預設分頁改融資警示"
```

---

### Task 3: 拿掉「候選觀察」開頁 hero

**Files:**
- Modify: `export/chips_generator.py:11`（import）
- Modify: `export/chips_generator.py:1294,1298,1295-1297`（`generate()` 內的變數計算）
- Modify: `export/chips_generator.py:1367`（f-string 插入點）
- Test: `tests/test_chips_generator.py`

**Interfaces:**
- Consumes：無
- Produces：無（純移除）。`export/chips_headline.py` 模組本身不動、`build_candidate_cards()`/
  `render_headline_zone()` 保留（可能之後有其他用途），只是 `chips_generator.generate()` 不再
  呼叫

- [ ] **Step 1: 寫失敗測試，確認 hero 區塊已經不在輸出裡**

```python
def test_generate_no_longer_shows_candidate_observation_hero(tmp_path):
    """候選觀察/大戶持倉本週焦點的開頁hero已移除——joint_buy跟tdcc_accumulation
    回測都沒有展現edge，不該再佔全頁最顯眼的hero版位（見2026-08-25 spec）。
    法人同步觀察的完整榜單仍在tab-signal面板，不受影響。"""
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert 'class="hero"' not in html
    assert "候選觀察" not in html
    assert "大戶持倉本週焦點" not in html
```

加在 Task 2 新增的測試之後。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_chips_generator.py::test_generate_no_longer_shows_candidate_observation_hero -v`
Expected: FAIL（現況還看得到「候選觀察」字樣）

- [ ] **Step 3: 移除 import（第 11 行）**

刪除：

```python
from export.chips_headline import build_candidate_cards, render_headline_zone
```

- [ ] **Step 4: 移除 `generate()` 裡計算 hero 內容的區域變數（約 1294-1298 行）**

刪除這 5 行：

```python
    candidate_cards = build_candidate_cards(inst_scan, limit=3)
    holder_focus_sorted = sorted(
        shareholder_data, key=lambda r: -abs(r.get("week_chg") or 0)
    )[:5]
    headline_html = render_headline_zone(candidate_cards, holder_focus_sorted)
```

（`s7_html`/`s8_html` 等其他行維持不動，只刪這幾行）

- [ ] **Step 5: 移除 f-string 裡的插入點（第 1367 行附近）**

把：

```python
    <main id="main-content" class="main-content" tabindex="-1">
      {headline_html}
      {exch_filter_btns}
```

改成：

```python
    <main id="main-content" class="main-content" tabindex="-1">
      {exch_filter_btns}
```

- [ ] **Step 6: 執行測試確認通過**

Run: `pytest tests/test_chips_generator.py::test_generate_no_longer_shows_candidate_observation_hero -v`
Expected: PASS

- [ ] **Step 7: 刪除兩個既有的 hero 專屬測試（純測 hero 內容，移除後無可保留的斷言）**

`tests/test_chips_generator.py` 裡 `test_generate_includes_headline_zone`（約第 693-712 行）
跟 `test_generate_headline_zone_uses_shareholder_data_for_holder_focus`（約第 715-734 行）
兩個測試整個函式都是在斷言 hero 區塊的內容（候選觀察/大戶持倉本週焦點字樣、股票資料出現在
hero zone 裡），hero 整塊移除後這兩個測試沒有東西可以保留，直接刪除這兩個完整函式（不是改
斷言內容——這不是「行為變了要更新期望值」，是「這個行為本身不存在了」）。

- [ ] **Step 8: 跑全部既有測試，確認沒有其他地方依賴已移除的 hero 內容**

Run: `pytest tests/test_chips_generator.py -v`
Expected: 全部 PASS。若還有其他測試意外依賴 hero 內容（目前查過只有上面兩個），比照 Step 7
處理

Run: `pytest tests/test_chips_headline.py -v`
Expected: 全部 PASS（`chips_headline.py` 模組本身沒改，這個測試檔測的是模組本身、不是
`generate()` 有沒有呼叫它，不該壞）

- [ ] **Step 9: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "refactor(chips): 拿掉候選觀察開頁hero(joint_buy/tdcc回測均無edge)"
```

---

### Task 4: 證據卡／banner helper + 8 個面板套用

**Files:**
- Modify: `export/chips_generator.py`（新增 2 個函式，插入 `generate()` 8 處面板）
- Test: `tests/test_chips_generator.py`

**Interfaces:**
- Consumes：Task 1 的 `.evid-card`/`.caution-banner`/`.weak-banner`/`.evid-*` CSS class
- Produces：
  - `_evidence_card(tier: str, badge_label: str, stats: str, note: str) -> str`
  - `_evidence_banner(kind: str, title: str, body: str) -> str`（`kind` 是 `"caution"` 或
    `"weak"`）

- [ ] **Step 1: 寫失敗測試（helper 函式本身）**

```python
def test_evidence_card_renders_badge_and_stats():
    from export.chips_generator import _evidence_card
    html = _evidence_card("evid-verified", "已驗證", "訊號日 63．筆數 1154", "短期參考價值較高")
    assert 'class="evid evid-verified"' in html
    assert "已驗證" in html
    assert "訊號日 63" in html
    assert "短期參考價值較高" in html


def test_evidence_banner_caution_and_weak_variants():
    from export.chips_generator import _evidence_banner
    caution = _evidence_banner("caution", "樣本不足，尚未驗證", "資料只有3個月頻快照")
    assert 'class="caution-banner"' in caution
    assert "樣本不足，尚未驗證" in caution

    weak = _evidence_banner("weak", "回測顯示這個假設目前沒有得到支持", "D+14平均落後大盤0.53%")
    assert 'class="weak-banner"' in weak
    assert "回測顯示這個假設目前沒有得到支持" in weak
```

加在 `tests/test_chips_generator.py` 開頭 import 附近之後（新增這兩個函式名到檔案頂部的 import
清單）。把 `from export.chips_generator import ... generate` 那行加入
`_evidence_card, _evidence_banner`。

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_chips_generator.py::test_evidence_card_renders_badge_and_stats tests/test_chips_generator.py::test_evidence_banner_caution_and_weak_variants -v`
Expected: FAIL（ImportError，函式還不存在）

- [ ] **Step 3: 實作兩個 helper 函式**

加在 `export/chips_generator.py` 的 `_section()` 函式（約第 131 行）之後：

```python
def _evidence_card(tier: str, badge_label: str, stats: str, note: str) -> str:
    """回測證據卡：固定顯示在有回測結果的 tab 面板頂部。tier 是 CSS class
    （evid-verified/evid-observe/evid-unproven），數字/文字全部是靜態字串，直接抄自
    docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md 總表——回測結果是
    離線跑 `python main.py --backtest-chips` 才會更新，不隨每日資料變動，故不接即時查詢。"""
    return (f'<div class="evid-card"><span class="evid {tier}">{badge_label}</span>'
            f'<span>{stats}</span><span class="src">{note}</span></div>')


def _evidence_banner(kind: str, title: str, body: str) -> str:
    """證據不足/證據偏弱的說明 banner。kind='caution'(樣本不足待驗證) 或
    'weak'(已驗證但沒展現edge)，對應 Task 1 新增的 .caution-banner/.weak-banner CSS。"""
    cls = "caution-banner" if kind == "caution" else "weak-banner"
    return f'<div class="{cls}"><b>{_esc(title)}</b> — {_esc(body)}</div>'
```

（`title`/`body` 過 `_esc()` 是防禦性習慣，這裡雖然是寫死字串沒有外部輸入風險，但跟檔案裡其他
組字串的函式維持一致寫法）

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_chips_generator.py::test_evidence_card_renders_badge_and_stats tests/test_chips_generator.py::test_evidence_banner_caution_and_weak_variants -v`
Expected: PASS

- [ ] **Step 5: 寫失敗測試（8 個面板都要看到對應卡片/banner）**

```python
def test_generate_shows_evidence_card_in_every_backtested_tab(tmp_path):
    output_path = tmp_path / "chips.html"
    generate(date(2026, 7, 5), {"測試族群": {"foreign_net_today": 100}}, {}, output_path=str(output_path))
    html = output_path.read_text(encoding="utf-8")

    tab_signal = html[html.index('id="tab-signal"'):html.index('id="tab-dipbuy"')]
    assert 'evid-observe' in tab_signal and "訊號日 61" in tab_signal

    tab_dipbuy = html[html.index('id="tab-dipbuy"'):html.index('id="tab-stealth"')]
    assert 'weak-banner' in tab_dipbuy and "回測顯示這個假設目前沒有得到支持" in tab_dipbuy

    tab_stealth = html[html.index('id="tab-stealth"'):html.index('id="tab-inst"')]
    assert 'evid-observe' in tab_stealth and "訊號日 63" in tab_stealth

    tab_inst = html[html.index('id="tab-inst"'):html.index('id="tab-foreign"')]
    assert 'evid-observe' in tab_inst

    tab_foreign = html[html.index('id="tab-foreign"'):html.index('id="tab-trust"')]
    assert 'evid-observe' in tab_foreign and "訊號日 61" in tab_foreign

    tab_trust = html[html.index('id="tab-trust"'):html.index('id="tab-margin"')]
    assert 'evid-observe' in tab_trust and "訊號日 57" in tab_trust

    tab_margin = html[html.index('id="tab-margin"'):html.index('id="tab-holder"')]
    assert 'evid-verified' in tab_margin and "訊號日 63" in tab_margin

    tab_holder = html[html.index('id="tab-holder"'):html.index('id="tab-insider"')]
    assert 'evid-observe' in tab_holder and "訊號日 29" in tab_holder

    tab_insider = html[html.index('id="tab-insider"'):]
    assert 'caution-banner' in tab_insider and "樣本不足，尚未驗證" in tab_insider
```

加在 Task 3 新增的測試之後。

- [ ] **Step 6: 執行測試確認失敗**

Run: `pytest tests/test_chips_generator.py::test_generate_shows_evidence_card_in_every_backtested_tab -v`
Expected: FAIL

- [ ] **Step 7: 在 `generate()` 裡建立 9 個證據卡/banner 變數（緊接在 `s8_html, s8_note, s_insider_html = _build_section8(...)` 那行之後，約第 1300 行）**

```python
    evid_signal = _evidence_card("evid-observe", "觀察用", "訊號日 61．筆數 377",
        "勝率43-44%，平均超額+1.55%但中位數-2.58%(均值被少數大贏家拉正)，非穩定訊號")
    evid_dipbuy = _evidence_banner("weak", "回測顯示這個假設目前沒有得到支持",
        "1722筆訊號中D+14平均落後大盤0.53%，是11條規則裡樣本最大、表現也最差的，"
        "保留供觀察但不建議當作進場依據")
    evid_stealth = _evidence_card("evid-observe", "觀察用", "訊號日 63．筆數 1615",
        "勝率42-43%，平均超額+0.57%，11條規則裡表現相對最好，但仍不到50%勝率")
    evid_inst = _evidence_card("evid-observe", "觀察用", "與「外資籌碼」共用同一組回測證據",
        "族群層級彙總版，外資連買本身在回測中沒有展現預測力，僅供觀察")
    evid_foreign = _evidence_card("evid-observe", "觀察用", "訊號日 61．筆數 732-754",
        "勝率34-39%，平均超額-0.42%~-1.11%，盤整/空頭更差，連買本身沒有展現預測力")
    evid_trust = _evidence_card("evid-observe", "觀察用", "訊號日 57．筆數 437-439",
        "勝率37-40%，平均超額約0~+0.26%，略優於外資版但仍不到50%")
    evid_margin = _evidence_card("evid-verified", "已驗證", "訊號日 63．筆數 1154",
        "D+5避險命中54%．D+10 51%．D+14 47%，短期(5日內)參考價值較高，拉長會退化——"
        "這是示警用途不是選股訊號")
    evid_holder = _evidence_card("evid-observe", "觀察用", "訊號日 29(樣本最小)．筆數 834",
        "勝率37-40%，多頭市場平均超額反而-0.51%")
    evid_insider = _evidence_banner("caution", "樣本不足，尚未驗證",
        "集保揭露資料目前只有3個月頻快照(5月/6月/7月)，不足以做任何統計結論，"
        "這裡顯示的是最新一期原始數字，僅供參考，等資料再累積幾個月後會補回測")
```

- [ ] **Step 8: 把 9 個變數插進對應 tab 面板（`generate()` 的 f-string，約第 1370-1409 行）**

把：

```python
      <div class="tab-panel" id="tab-signal" role="tabpanel" aria-labelledby="tab-btn-signal">
        {s6a_html}
      </div>

      <div class="tab-panel" id="tab-dipbuy" role="tabpanel" aria-labelledby="tab-btn-dipbuy">
        {s35_html}
      </div>

      <div class="tab-panel" id="tab-stealth" role="tabpanel" aria-labelledby="tab-btn-stealth">
        {s_stealth_html}
      </div>

      <div class="tab-panel" id="tab-inst" role="tabpanel" aria-labelledby="tab-btn-inst">
        {s1_html}
      </div>

      <div class="tab-panel" id="tab-foreign" role="tabpanel" aria-labelledby="tab-btn-foreign">
        {s6_foreign_html}
        {s2_html}
        {s5_html}
      </div>

      <div class="tab-panel" id="tab-trust" role="tabpanel" aria-labelledby="tab-btn-trust">
        {s6_trust_html}
        {s3_html}
      </div>

      <div class="tab-panel" id="tab-margin" role="tabpanel" aria-labelledby="tab-btn-margin">
        {s7_html}
        {s4_html}
      </div>

      <div class="tab-panel" id="tab-holder" role="tabpanel" aria-labelledby="tab-btn-holder">
        {s8_note}
        {s8_html}
      </div>

      <div class="tab-panel" id="tab-insider" role="tabpanel" aria-labelledby="tab-btn-insider">
        {s_insider_html}
      </div>
```

改成（每個面板開頭插入對應證據卡/banner）：

```python
      <div class="tab-panel" id="tab-signal" role="tabpanel" aria-labelledby="tab-btn-signal">
        {evid_signal}
        {s6a_html}
      </div>

      <div class="tab-panel" id="tab-dipbuy" role="tabpanel" aria-labelledby="tab-btn-dipbuy">
        {evid_dipbuy}
        {s35_html}
      </div>

      <div class="tab-panel" id="tab-stealth" role="tabpanel" aria-labelledby="tab-btn-stealth">
        {evid_stealth}
        {s_stealth_html}
      </div>

      <div class="tab-panel" id="tab-inst" role="tabpanel" aria-labelledby="tab-btn-inst">
        {evid_inst}
        {s1_html}
      </div>

      <div class="tab-panel" id="tab-foreign" role="tabpanel" aria-labelledby="tab-btn-foreign">
        {evid_foreign}
        {s6_foreign_html}
        {s2_html}
        {s5_html}
      </div>

      <div class="tab-panel" id="tab-trust" role="tabpanel" aria-labelledby="tab-btn-trust">
        {evid_trust}
        {s6_trust_html}
        {s3_html}
      </div>

      <div class="tab-panel" id="tab-margin" role="tabpanel" aria-labelledby="tab-btn-margin">
        {evid_margin}
        {s7_html}
        {s4_html}
      </div>

      <div class="tab-panel" id="tab-holder" role="tabpanel" aria-labelledby="tab-btn-holder">
        {evid_holder}
        {s8_note}
        {s8_html}
      </div>

      <div class="tab-panel" id="tab-insider" role="tabpanel" aria-labelledby="tab-btn-insider">
        {evid_insider}
        {s_insider_html}
      </div>
```

- [ ] **Step 9: 執行測試確認通過**

Run: `pytest tests/test_chips_generator.py::test_generate_shows_evidence_card_in_every_backtested_tab -v`
Expected: PASS

- [ ] **Step 10: 跑全專案測試**

Run: `pytest -q`
Expected: 全綠。這次改動只動 `export/chips_generator.py` 一個檔案的樣板字串，不該影響
`screener/`/`processors/`/`scrapers/` 任何測試

- [ ] **Step 11: Commit**

```bash
git add export/chips_generator.py tests/test_chips_generator.py
git commit -m "feat(chips): 9個tab面板加證據卡/banner(數字抄自2026-08-25回測spec)"
```

---

## Self-Review 紀錄

- **Spec 覆蓋**：spec「視覺／資訊架構設計」節 4 項改動（badge 樣式/tab重排/拿掉hero/證據卡）
  都對應到 Task 1-4；spec 四級分類表 9 個 tab 全部在 Task 2 的對照表跟 Task 4 的 9 個
  `evid_*` 變數裡逐一覆蓋，含「法人買賣」這個 spec 總表沒直接列出、但共用外資籌碼證據的延伸
  分類（已在 Task 2 開頭註明決策依據）
- **Placeholder 掃描**：無 TBD/之後補/略——每個 Step 的證據卡文案都是完整字串，不是佔位符
- **型別一致性**：`_evidence_card`/`_evidence_banner` 的參數名/回傳型別（`str`）在 Task 1
  介面宣告、Task 4 實作、Task 4 測試三處一致；tab id／CSS class 名稱在 Task 1-4 全程沒有改名

## 執行選項

Plan 已存到 `docs/superpowers/plans/2026-08-25-chips-page-evidence-tiers.md`。兩種執行方式：

1. **Subagent-Driven（建議）**——每個 Task 派一個全新 subagent 執行，Task 之間我會 review，
   迭代快
2. **Inline Execution**——在這個 session 裡照 Task 順序批次執行，每個 Task 完成後停下來給你看

要用哪一種？
