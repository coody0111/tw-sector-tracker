# batch 股價改用 realtime 同源（與 --realtime 一致，杜絕盤中/盤後看到昨日數據）

**日期**：2026-07-09
**範圍**：只改 `python main.py`（batch）的**股價抓取來源**；籌碼（法人/融資/TAIEX）不動。

**狀態：✅ 已實作**（commit `25447d5` "feat: batch 股價改用 realtime 同源，與 --realtime 一致"，
2026-07-09 18:54，早於本檔寫檔時間，此份為事後補記的設計文件）。`main.py:397-418` 已落地：
batch 主打 `fetch_realtime_prices`，失敗/回空才退回 `fetch_prices_for_stocks`。未另開對應
`plans/` 檔案（範圍小、方案單一，直接實作未拆步驟）。

## 背景與痛點

Cody 實跑一整天，反覆遇到「跑 `python main.py` 看到舊/昨天的股價、族群漲跌」，但
`--realtime` 都正常。根因查清為兩類：

1. **TPEx 官方 endpoint 盤後定案延遲**：盤後太早跑（如 15:33），`tpex_mainboard_quotes`
   還沒把今日收盤定案，對部分低量/處置股回**前一交易日殘留值**（其陽 3564 一度顯示昨日
   漲停 +10%，實際今天是跌的 −3.57%）→ 個股/族群漲幅虛高。
2. **盤中跑 batch**：官方收盤 API 盤中無今日資料，「市場尚未更新」防呆會把日期切回昨天
   → 盤中看到的是昨天。

`--realtime`（`mis.twse.com.tw`）沒有這些問題：它是即時來源，盤中給即時價、**盤後回收盤
集合競價價**（實測 2026-07-09 17:55 仍撈得到，`time=13:30:00`，其陽正確回 54.1）。

## 核心洞察（決定方案的關鍵）

realtime 來源在**收盤後回的就是收盤定案價**（集合競價），與官方收盤價一致（台積電
2415 兩邊相同），**但沒有 TPEx 定案延遲**。所以「batch 股價改用 realtime 同源」能一次
解決上述兩類問題，且與 `--realtime` 天然一致。

## 設計

`main.py::run()` 的 batch（`else`，非 realtime）分支，股價抓取策略改為：

1. **主來源：`fetch_realtime_prices(unique_ids)`**（與 `--realtime` 同一支）
2. **退路：realtime 回空/失敗時 → `fetch_prices_for_stocks(unique_ids, trade_date)`**
   （官方 TWSE+TPEx 收盤）——涵蓋盤前/假日/realtime 服務未提供的情況，避免整批無資料。

下游完全不動：寫 daily_prices、算族群績效、更新籌碼 DB、產 HTML、push 全部照舊。

### 明確不在範圍（誠實界定）

- **籌碼欄（外資/投信/融資）維持官方來源**：realtime 來源本來就沒有籌碼資料，籌碼只有
  官方 API 有、且盤後才發布。所以「股價/族群」會與 --realtime 一致，但籌碼欄仍依官方
  發布時間，這是資料源本質，非本次可解。
- 不改 `--realtime` 行為。
- TPEx 官方 endpoint 的定案偵測不再需要（改用 realtime 已繞過該問題）。

## 既有防護的互動（要保持不壞）

- **完整性保險絲（2330 不在就中止）**：realtime 一定含 2330 → 正常通過；退路走官方時也
  照樣檢查。不衝突。
- **「市場尚未更新」防呆**：realtime 盤後給今日收盤、與昨日不同 → 防呆不誤觸。退路走官方
  時防呆仍有效。

## 資料正確性備註

- realtime 盤中跑會把「當下即時價」寫進 `daily_prices/{today}.csv`（歷史日檔）。這與現行
  `--realtime` 行為相同（本來就會寫），非新增風險；只要當天有一次盤後跑，最終會覆蓋成
  收盤價。近5/7/10/14日/回測依賴的是收盤，盤後那次跑即為準。

## 測試（交 Debugger 跑）

- batch 主來源走 realtime：mock `fetch_realtime_prices` 回正常 df → 用它、不呼叫官方。
- realtime 回空/丟例外 → 退回 `fetch_prices_for_stocks`（官方）。
- 兩條路徑最終 `prices_df` 都能讓下游正常算族群績效。
- 保險絲仍有效：realtime 回的 df 缺 2330 → 中止。
