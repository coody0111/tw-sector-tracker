# 大戶持倉本週焦點：拿掉長條圖，改純文字列表

## Problem Statement

`docs/chips.html` 首頁「今日焦點」區塊裡的「大戶持倉本週焦點」子區塊，目前用發散長條圖
（`.hm-divbar`，置中0、依這批Top5的最大變化幅度動態縮放）呈現每檔股票的週變化%。

Cody 反饋這個長條圖沒有用：長條本身沒有比旁邊已經寫出來的數字（週變化% pill、目前水位%）
多傳達任何資訊，只是把數字又畫了一次，是視覺雜訊，不是額外資訊量。

## Solution

拿掉 `.hm-divbar` 長條，改成純文字一行式：股票名稱｜週變化% pill｜目前水位%。

- 排序邏輯不變：依 `|週變化%|` 絕對值排序取前5，不分方向（增倉減倉都算）——這本身就是
  重點，不是缺點，不用改成增倉/減倉分兩組
- 週變化% 的 pill 樣式（`.hm-delta.up`/`.hm-delta.down`）保留——這是頁面既有的「帶方向性
  數字」視覺語言（跟 `.hc-streak-pill` 同一套慣例），拿掉長條不代表要拿掉這個
- 目前水位%（`.hm-abs`）維持灰階小字輔助資訊，不額外強調樣式——這是次要資訊，週變化%
  pill 才是這一列的視覺重點

## User Stories

1. As Cody，我想在「大戶持倉本週焦點」看到乾淨的一行式列表（股票名稱｜週變化%｜目前
   水位%），不要有長條圖佔版面又不提供額外資訊。
2. As Cody，我想這個區塊的排序邏輯維持不變（依週變化絕對值排序前5，不分方向），因為
   「這週誰的大戶部位變動最劇烈」本身就是我想看的重點。
3. As Cody，我想週變化%繼續用現有的 pill 標籤樣式呈現，跟頁面其他地方（連買/連賣天數）
   的視覺語言一致，不要因為拿掉長條就連帶改變這個既有慣例。

## Implementation Decisions

**`export/chips_headline.py::render_headline_zone()`**：目前這段迴圈算 `max_abs`/`bar_pct`
純粹是為了畫長條，拿掉長條後這兩個計算不再需要，一併移除：

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

改成（移除 `max_abs`/`bar_pct`/`.hm-divbar`，其餘欄位/邏輯不變）：

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

排序邏輯（`export/chips_generator.py` 裡 `holder_focus_sorted = sorted(shareholder_data,
key=lambda r: -abs(r.get("week_chg") or 0))[:5]`）完全不變，不動。

**CSS（`export/chips_generator.py` 內嵌的 `_CSS`/樣式字串）**：`.holder-mini-row` 從4欄
（name/divbar/delta/abs）改成3欄，拿掉的 `1fr` 中間欄（原本保留給長條）讓給名稱欄，
名稱不再需要固定窄寬度：

```
.holder-mini-row{display:grid;grid-template-columns:76px 1fr 46px 50px;gap:8px;align-items:center;padding:6px 0}
.hm-name{font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hm-divbar{height:6px;background:var(--surface-2);border-radius:2px;position:relative;overflow:hidden}
.hm-divbar span{position:absolute;top:0;bottom:0;border-radius:2px}
.hm-divbar span.up{left:50%;background:var(--up)}
.hm-divbar span.down{right:50%;background:var(--down)}
.hm-delta{font-family:ui-monospace,monospace;font-weight:700;font-size:.7rem;text-align:center;padding:2px 0;border-radius:8px;border:1px solid}
```

改成（3欄：name彈性寬度/delta固定/abs固定，移除全部 `.hm-divbar*` 規則）：

```
.holder-mini-row{display:grid;grid-template-columns:1fr 52px 50px;gap:8px;align-items:center;padding:6px 0}
.hm-name{font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hm-delta{font-family:ui-monospace,monospace;font-weight:700;font-size:.7rem;text-align:center;padding:2px 0;border-radius:8px;border:1px solid}
```

（`.hm-delta.up`/`.hm-delta.down`/`.hm-abs` 三條規則不動，繼續保留。）

## Testing Decisions

- `tests/test_chips_headline.py::test_render_headline_zone_renders_populated_holder_focus_rows`
  是現有測試，目前斷言只檢查 `hm-delta up">+2.1%`/`hm-delta down">-0.8%` 字串是否存在——
  這兩個斷言在拿掉長條後仍然成立，不用改。額外新增斷言確認 `.hm-divbar` 相關 HTML
  不再出現在輸出裡（回歸測試，鎖住「長條真的被拿掉」而不是「長條還在但被隱藏」）：

```python
def test_render_headline_zone_holder_focus_rows_have_no_bar_chart():
    """Cody反饋長條圖是視覺雜訊、沒有用，拿掉後不能再有.hm-divbar相關HTML。"""
    holder_focus = [
        {"stock_id": "5347", "stock_name": "世界先進", "lv12_15_pct": 68.4, "week_chg": 2.1},
    ]
    html = render_headline_zone(candidate_cards=[], holder_focus=holder_focus)

    assert "hm-divbar" not in html
```

- 只測試外部行為（`render_headline_zone()` 的輸出字串），不測試內部實作細節。

## Out of Scope

- 不改排序邏輯（依然是 `|週變化%|` 絕對值排序前5，不分方向）
- 不改候選觀察卡片（`build_candidate_cards`/`_candidate_card_html`），這個spec只動
  「大戶持倉本週焦點」那一半
- 不改完整「大戶籌碼」分頁（Section8 的卡片化列表），那邊本來就沒有長條圖，這次沒有
  牽連到

## Further Notes

- debug worktree 的 `docs/superpowers/mockups/2026-07-23-chips-v3-final.html`（這個功能
  最初的設計依據）裡有一段解釋「為什麼改用發散長條」的說明註解，這次拿掉長條後那段
  註解的前提已經不成立，但那份 mockup 檔案是歷史紀錄用途、不是正式程式碼，這次不去
  改它，只在這裡記錄「後來又反悔拿掉長條」這個結論，避免以後對照 mockup 時誤以為
  現行程式碼還在用發散長條。
