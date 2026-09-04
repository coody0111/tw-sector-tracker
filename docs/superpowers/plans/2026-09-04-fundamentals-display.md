# 季報基本面展示層實作計畫

## 依據

- Spec：`docs/superpowers/specs/2026-09-04-fundamentals-display-design.md`
- ADR：`docs/adr/0007-fundamentals-availability-uses-statutory-deadline.md`
- 主要實作：`screener/database.py`、`export/index_generator.py`
- 產生檔：`docs/index.html`，不手動修改

## 需求對照

| Spec | 實作決策 | 驗證 |
|---|---|---|
| §5.3 | `_statutory_available_date(year, quarter)` 純函式；Q1→5/15、Q2→8/14、Q3→11/14、Q4→隔年 3/31 | 四季別 + 邊界日 + 跨年 pytest |
| §5.4–5.5 | `as_of` 由 `daily_prices` MAX(date) 取得；每檔取可得日 ≤ as_of 中 period_end 最大者 | 合成資料 pytest |
| §4.1 | 所有 `sector_stocks` join 先 `SELECT DISTINCT stock_id` | 筆數不放大的斷言 |
| §7 | Q1 取累計；Q2–Q4 相減；EPS 永遠累計、不相減 | 三種季別各一測試 |
| §8.2 | 獲利類 \|YoY/QoQ\|>999% → 「轉盈」／「轉虧」；營收不設限；比率超出 ±999% → 「—」 | 邊界值 pytest |
| §8.1 | 缺值回 None，卡片保留，不 crash | 空資料 / 部分缺值測試 |
| §6 | modal 於 `.sc-chips` 之後新增基本面區塊，標頭含季別、「單季」字樣與可得日 | HTML 字串契約測試 |
| §9 | 查詢集中在 `screener/database.py::get_fundamentals_snapshot()` | 不新增 `processors/` 模組 |
| §3 | `.stock-list-table` 14 欄 HTML 與排序行為零變更 | 既有測試須全過 |

## 實作順序

1. **資料層**：`screener/database.py` 新增 `_statutory_available_date()` 與
   `get_fundamentals_snapshot(as_of)`。含單季換算、YoY／QoQ、比率、離群防護，
   回傳 DataFrame（每檔一列，缺值為 None）。
2. **測試**：`tests/test_fundamentals_snapshot.py`——可得日四季別與邊界、跨年落回 Q3、
   單季換算、EPS 不相減、離群三種規則、缺值不 crash、DISTINCT 不放大。
3. **展示層資料**：`build_stock_detail_data()` 新增 `fundamentals_df` 參數（可選，
   不傳則該區塊整體為 None），依既有慣例把欄位掛進每檔的 dict。
4. **展示層 HTML**：`openStockCard()` 於 `.sc-chips` 之後輸出基本面區塊，
   沿用既有 CSS token（`--panel-2`／`--mono`／`.sc-chips` 那套），不新增視覺語言。
5. **接線**：`main.py` 取 `as_of` 並把 `get_fundamentals_snapshot()` 結果透傳給
   `generate()`；更新 `debug-tasks.md` 交接。

## 暫不混入

- **月營收**。`monthly_revenue` 目前 0 筆，Phase 1／2B 尚未實際回填並驗證。
- **`operating_income` 映射修復**。`scrapers/mops_xbrl.py` 上一版修改（`99fba2a`）
  還在等 Debugger 驗證、尚未 push，不在其上疊加解析語意變更。本輪改顯示稅前淨利率。
- **金融業 `pretax_income` 映射**。universe 1,033 檔全為 `'ci'` 一般業，不受影響。
- **基本面進選股分數／訊號**。需先過 `research/` 的 RankIC 驗證。
- **14 欄個股表加欄位**。按成長排序屬排行／篩選需求，不塞進兩層式設計的第一層。
- **真實申報日爬蟲**（MOPS 逐檔查詢頁）。
- **`ui-ux-pro-max` 視覺提案**。本輪是在已定案 modal 內沿用既有 token 加區塊。
