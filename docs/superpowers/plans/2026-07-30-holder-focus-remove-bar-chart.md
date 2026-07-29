# 大戶持倉本週焦點：拿掉長條圖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除「大戶持倉本週焦點」區塊的發散長條圖(`.hm-divbar`)，改成股票名稱｜週變化%pill｜目前水位% 的純文字一行式列表。

**Architecture:** 兩個檔案各改一處：`export/chips_headline.py::render_headline_zone()` 移除長條相關的HTML片段與 `max_abs`/`bar_pct` 計算；`export/chips_generator.py` 內嵌CSS移除 `.hm-divbar*` 規則、`.holder-mini-row` 從4欄改3欄。排序邏輯（依`|週變化%|`絕對值排序前5）完全不動。

**Tech Stack:** Python, pytest,純字串拼接的HTML/CSS產生器（無前端建置流程）。

**Spec:** `docs/superpowers/specs/2026-07-30-holder-focus-remove-bar-chart-design.md`

---

### Task 1: 移除 chips_headline.py 的長條圖邏輯

**Files:**
- Modify: `export/chips_headline.py:60-76`
- Test: `tests/test_chips_headline.py`

- [ ] **Step 1: 寫新的失敗測試，鎖住「長條真的被拿掉」**

在 `tests/test_chips_headline.py` 現有測試最後面新增：

```python
def test_render_headline_zone_holder_focus_rows_have_no_bar_chart():
    """Cody反饋長條圖是視覺雜訊、沒有用，拿掉後不能再有.hm-divbar相關HTML。"""
    holder_focus = [
        {"stock_id": "5347", "stock_name": "世界先進", "lv12_15_pct": 68.4, "week_chg": 2.1},
    ]
    html = render_headline_zone(candidate_cards=[], holder_focus=holder_focus)

    assert "hm-divbar" not in html
```

- [ ] **Step 2: 執行測試，確認會失敗**

Run: `pytest tests/test_chips_headline.py::test_render_headline_zone_holder_focus_rows_have_no_bar_chart -v`
Expected: FAIL（目前的實作仍會輸出 `<div class="hm-divbar">...`）

- [ ] **Step 3: 修改 `render_headline_zone()`，移除長條相關程式碼**

把 `export/chips_headline.py` 裡 `render_headline_zone()` 的這一段（目前約在第60-76行）：

```python
    if not holder_focus:
        holder_html = '<div class="detail-empty">今日無資料</div>'
    else:
        rows_html = []
        max_abs = max((abs(r.get("week_chg") or 0) for r in holder_focus[:5]), default=1.0) or 1.0
        for row in holder_focus[:5]:
            week_chg = row.get("week_chg") or 0.0
            direction = "up" if week_chg >= 0 else "down"
            bar_pct = abs(week_chg) / max_abs * 50
            lv12_15_pct = row.get("lv12_15_pct") or 0
            rows_html.append(f"""<div class="holder-mini-row">
  <span class="hm-name">{_esc(row.get('stock_name', ''))}</span>
  <div class="hm-divbar"><span class="{direction}" style="width:{bar_pct:.1f}%"></span></div>
  <span class="hm-delta {direction}">{week_chg:+.1f}%</span>
  <span class="hm-abs">{lv12_15_pct:.1f}%</span>
</div>""")
        holder_html = "".join(rows_html)
```

改成：

```python
    if not holder_focus:
        holder_html = '<div class="detail-empty">今日無資料</div>'
    else:
        rows_html = []
        for row in holder_focus[:5]:
            week_chg = row.get("week_chg") or 0.0
            direction = "up" if week_chg >= 0 else "down"
            lv12_15_pct = row.get("lv12_15_pct") or 0
            rows_html.append(f"""<div class="holder-mini-row">
  <span class="hm-name">{_esc(row.get('stock_name', ''))}</span>
  <span class="hm-delta {direction}">{week_chg:+.1f}%</span>
  <span class="hm-abs">{lv12_15_pct:.1f}%</span>
</div>""")
        holder_html = "".join(rows_html)
```

- [ ] **Step 4: 執行整份測試檔，確認全部通過**

Run: `pytest tests/test_chips_headline.py -v`
Expected: PASS（含既有的 `test_render_headline_zone_renders_populated_holder_focus_rows`，其斷言只檢查 `hm-delta up">+2.1%`/`hm-delta down">-0.8%`，不涉及長條，應維持通過不用改）

- [ ] **Step 5: Commit**

```bash
git add export/chips_headline.py tests/test_chips_headline.py
git commit -m "fix(chips_headline): 移除大戶持倉本週焦點的長條圖，改純文字呈現"
```

---

### Task 2: 更新 chips_generator.py 的CSS

**Files:**
- Modify: `export/chips_generator.py:813-822`

- [ ] **Step 1: 修改CSS區塊**

把 `export/chips_generator.py` 裡這段（目前第813-822行）：

```
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
```

改成（移除全部 `.hm-divbar*` 三條規則，`.holder-mini-row` 改3欄）：

```
  .holder-mini-row{display:grid;grid-template-columns:1fr 52px 50px;gap:8px;align-items:center;padding:6px 0}
  .hm-name{font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .hm-delta{font-family:ui-monospace,monospace;font-weight:700;font-size:.7rem;text-align:center;padding:2px 0;border-radius:8px;border:1px solid}
  .hm-delta.up{color:#FF9585;background:rgba(230,67,47,.32);border-color:rgba(230,67,47,.55)}
  .hm-delta.down{color:#7FE8A8;background:rgba(55,178,92,.32);border-color:rgba(55,178,92,.55)}
  .hm-abs{font-family:ui-monospace,monospace;font-size:.66rem;color:var(--subtle);text-align:right}
```

- [ ] **Step 2: 確認沒有其他地方還引用 `.hm-divbar`**

Run: `grep -rn "hm-divbar" export/ tests/ docs/chips.html 2>/dev/null`
Expected: 沒有任何輸出（全部清乾淨）。若 `docs/chips.html` 有殘留是因為它是產生出來的靜態檔案，下次 `main.py` 重新產生時會自動更新，不用手動改。

- [ ] **Step 3: 執行完整測試套件，確認沒有回歸**

Run: `pytest tests/ -v`
Expected: 全部PASS，數量應與Task 1完成後一致（Task 1新增1個測試，這裡不新增測試，只改CSS字串）

- [ ] **Step 4: Commit**

```bash
git add export/chips_generator.py
git commit -m "style(chips_generator): 移除大戶持倉本週焦點長條圖CSS，holder-mini-row改3欄"
```

---

### Task 3: 更新 debug-tasks.md 交接紀錄

**Files:**
- Modify: `debug-tasks.md`

- [ ] **Step 1: 在檔案最後面新增交接區塊**

依照專案既有格式（見 `CLAUDE.md` 範本），在 `debug-tasks.md` 檔案最末端新增：

```markdown
## [2026-07-30] 大戶持倉本週焦點：拿掉長條圖

### 改了什麼
- 異動檔案：export/chips_headline.py, export/chips_generator.py
- 邏輯說明：籌碼頁(docs/chips.html)首頁「今日焦點」的「大戶持倉本週焦點」子區塊，
  拿掉發散長條圖(.hm-divbar)，改成股票名稱｜週變化%pill｜目前水位% 純文字一行式。
  Cody反饋長條圖沒有比旁邊數字多傳達資訊，是視覺雜訊。排序邏輯（依|週變化%|絕對值
  排序前5，不分方向）完全沒動。

### 資料來源相關（如有異動）
- 無資料來源異動，純呈現層調整（HTML/CSS）

### 請 Debugger 驗證
- [ ] 「大戶持倉本週焦點」區塊視覺上正確顯示3欄（名稱/週變化%pill/目前水位%），沒有長條
- [ ] 週變化%的紅漲綠跌pill樣式跟頁面其他地方(連買/連賣天數)視覺一致
- [ ] 沒有影響「候選觀察」卡片（同一個headline zone的另一半，這次沒有動）
- [ ] 沒有影響完整「大戶籌碼」分頁（Section8，本來就沒有長條圖）

### 特別注意
- debug worktree的 docs/superpowers/mockups/2026-07-23-chips-v3-final.html 裡有一段
  解釋「為什麼改用發散長條」的註解，前提現在已經不成立，是歷史紀錄不用改，但對照時
  別誤以為現行程式碼還在用發散長條
```

- [ ] **Step 2: Commit**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 交接大戶持倉本週焦點拿掉長條圖"
```

---

## Self-Review Notes

- **Spec coverage**：spec的3個Implementation Decisions（chips_headline.py邏輯、CSS）對應Task1+2；Testing Decisions的回歸測試對應Task1 Step1；Out of Scope（排序邏輯/候選觀察/大戶籌碼分頁不動）在Task3的驗證清單裡有明確提醒Debugger不要誤判成也要改。
- **No placeholders**：每個Step都有完整程式碼，沒有「TODO」/「類似上面」等佔位敘述。
- **Type/命名一致性**：`holder_html`/`rows_html`/`row`/`week_chg`/`direction`/`lv12_15_pct` 變數名稱在Task1前後版本一致，沒有改名不一致的問題。
