# 個股列表新增欄位：融資佔比／維持率(估)

## Problem Statement

Cody 想在個股列表看出「這檔股票的融資部位風險大不大」——現有欄位（收盤/漲跌%/量比/
5~14日報酬）都沒有反映融資槓桿相關的風險。具體想知道兩件事：
1. 這檔股票有多少比例是用融資（槓桿）買的（曝險規模）
2. 這些融資部位現在離「被追繳/斷頭」有多近（急迫風險）

這兩者是不同問題：曝險規模高但維持率健康、或曝險規模低但維持率逼近斷頭線，都是有意義
的不同組合，需要兩個獨立欄位。

## Solution

個股列表新增兩個可排序欄位，緊接在「量比」後面：

- **融資佔比**＝融資餘額(股數) ÷ 已發行股數 × 100%
- **維持率(估)**＝現價 ÷ 20日均價 ÷ 融資成數 × 100%，低於130%（法規追繳門檻）用警示色
  +徽章標示

維持率(估) 是估算值，不是真實維持率（真實維持率是帳戶層級資料，交易所不公布單一股票的
精確數字）。20日均價當融資成本基準是業界慣例做法，見
`docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md`。

## User Stories

1. As Cody，我想在個股列表看到「融資佔比」欄位，這樣能知道這檔股票有多少籌碼是槓桿部位。
2. As Cody，我想在個股列表看到「維持率(估)」欄位，這樣能抓出哪些股票的融資部位接近斷頭。
3. As Cody，我想維持率(估)低於130%時有明顯的警示色跟徽章，不用自己記門檻數字。
4. As Cody，我想這兩欄都能點欄名排序，這樣能直接把風險最高的幾檔排到最前面，不用一檔一
   檔點開看。
5. As Cody，如果一檔股票融資餘額是0（沒人用融資買），我想看到「─」而不是一個沒意義的
   百分比或維持率數字。
6. As Cody，我想知道融資佔比用的集保資料是哪一天的，因為它是每週更新，可能比其他欄位
   （收盤、量比）舊——不想誤以為全部欄位都是當天數字。
7. As Cody，我想清楚知道維持率(估)是估算值不是真實維持率，避免我或其他人誤以為這是
   精確數字去做重大決策。

## Implementation Decisions

**新資料來源函式**：

- `screener/database.py` 新增 `get_latest_total_shares(trade_date: str) -> pd.DataFrame`：
  比照 `get_chips_today()` 的 per-stock fallback 模式（每支股票取 `<= trade_date` 的最新一筆，
  不是整表取單一最新日期），從 `shareholder` 表撈 `stock_id, total_shares, date`，回傳的
  `date` 欄位用來顯示「集保資料實際日期」的提示。
- `processors/performance.py` 新增 `calc_avg20_close(universe_df, db_path) -> Dict[str, float]`：
  每支股票近20個交易日的平均收盤價（`daily_prices.close`），輸出 `{stock_id: avg20}`。
  比照 `calc_stock_sparklines()` 現有的 pivot 模式抓資料，不足20天的股票用實際天數的
  平均值（不強求剛好20筆，跟現有其他 rolling 函式對「資料不足」的處理原則一致：能算
  多少算多少，不硬湊）。

**組裝到個股資料**：`export/index_generator.py::build_stock_detail_data()` 新增參數
`chips_df`（已有，含 `margin_balance`）、新增 `total_shares_df`（`get_latest_total_shares()`
輸出）、`avg20_map`（`calc_avg20_close()` 輸出）。每支股票算出：

```
financed_pct = margin_balance * 1000 / total_shares * 100   # None 若 margin_balance 為 0/None 或 total_shares 缺
maintenance_est = close / avg20 / financing_ratio * 100     # None 若 avg20 缺；margin_balance=0 一樣不顯示（見下）
financing_ratio = 0.6 if exchange == "TWSE" else 0.5        # 注意股/處置股例外不處理，見 Out of Scope
```

`financed_pct`／`maintenance_est` 若融資餘額為0或缺值，兩欄都回傳 None（前端顯示「─」）——
即使 `maintenance_est` 公式本身不需要 `margin_balance` 這個輸入，沒有融資部位的股票顯示
這個數字沒有意義（見 `CONTEXT.md`「融資維持率(估)」定義）。

同時回傳 `total_shares_asof`（`get_latest_total_shares()` 的 date 欄位），供前端顯示
「集保資料：YYYY-MM-DD」提示。

**HTML/CSS/JS**：`export/index_generator.py` 的個股列表相關函式（`renderStockListItem`、
`_sortValue`、`sortStockList`）新增兩欄：
- 表頭「股票/收盤/漲跌%/量比/**融資佔比**/**維持率(估)**/5日/7日/10日/14日」
- 「融資佔比」欄旁邊（或表頭 tooltip）顯示集保資料實際日期
- 「維持率(估)」低於130%：警示色（`var(--down)`）+ 粗體 + 徽章（比照既有 `vol-burst-badge`
  的視覺慣例，新增 `maint-badge` class）
- 融資佔比不設警示門檻，純數字顯示（沒有客觀依據硬設門檻，見討論記錄）
- 兩欄都可點欄名排序，`_sortValue()` 新增對應 key

## Testing Decisions

- `calc_avg20_close()`／`get_latest_total_shares()` 是純函式，比照 `tests/test_processors.py`／
  `tests/test_database.py` 既有模式：臨時 DB 塞造資料，驗證輸出正確
  - 測試 `get_latest_total_shares()` 的 per-stock fallback（某股集保資料比整表最新日期舊，
    仍要抓到自己的最新一筆，不是回空）
  - 測試 `calc_avg20_close()` 資料不滿20天時用實際天數平均，不強湊
- `build_stock_detail_data()` 的 `financed_pct`/`maintenance_est` 計算：構造真實情境數字
  （複刻這次討論用的真實案例，例如凌華 close=159.5、20日均價=139.35、TWSE、融資佔比
  1.55%、維持率190.8%）驗證公式正確；驗證融資餘額=0時兩欄回None
- 個股列表排序/徽章 JS 行為：比照既有 `test_generate_renders_volume_ratio_column_with_burst_badge`
  的模式，加對應測試斷言表頭存在、可排序、低於130%時徽章正確出現
- 只測試外部行為（函式輸出、HTML 是否含正確文字/欄位），不測試內部實作細節

## Out of Scope

- 不處理注意股/處置股等可能有不同融資成數的例外情況（估算一律用交易所預設值 60%/50%）
- 不做「融資使用率」（融資餘額÷融資限額，另一個已查到但決定不採用的官方精確指標，
  見 `CONTEXT.md`）
- 不為「融資佔比」設警示門檻/徽章

## Further Notes

- 兩個新指標都已經用真實資料庫驗證過公式（工業電腦38檔真實查詢，見
  `docs/superpowers/mockups/2026-07-28-stocklist-margin-columns-preview.html`），今天這批
  真實資料沒有任何一檔維持率(估)低於130%，警示狀態的視覺樣式是用建構範例展示，不是這批
  真實資料觸發的
- 設計討論見 `CONTEXT.md`（融資佔比/融資維持率(估)/融資使用率/融資成數等詞彙定義）與
  `docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md`
