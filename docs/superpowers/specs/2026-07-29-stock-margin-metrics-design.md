# 個股列表新增欄位：融資／融券佔比與維持率(估)

## Problem Statement

Cody 想在個股列表看出「這檔股票的融資融券部位風險大不大」——現有欄位（收盤/漲跌%/量比/
5~14日報酬）都沒有反映槓桿部位的風險。具體想知道四件事：
1. 這檔股票有多少比例是用融資（做多槓桿）買的（多方曝險規模）
2. 這些融資部位現在離「被追繳/斷頭」有多近（多方急迫風險——股價跌破成本會被追繳）
3. 這檔股票有多少比例是被融券（做空槓桿）放空的（空方曝險規模／軋空潛力）
4. 這些融券部位現在離「被軋空/回補」有多近（空方急迫風險——股價漲破放空成本會被軋空）

融資與融券的風險方向完全相反（融資怕跌、融券怕漲），但都是「槓桿部位＋方向性風險」的
同一種問題，值得用同一套呈現邏輯處理，只是公式方向相反。

## Solution

個股列表新增四個可排序欄位，依「多方一組、空方一組」分組排列，緊接在「量比」後面：

- **融資佔比**＝融資餘額(股數) ÷ 已發行股數 × 100%
- **融資維持率(估)**＝現價 ÷ 20日均價 ÷ 融資成數 × 100%，低於130%（法規追繳門檻）用警示色
  +徽章標示
- **融券餘額佔比**＝融券餘額(股數) ÷ 已發行股數 × 100%
- **融券維持率(估)**＝估計放空成本價(20日均價) ÷ 現價 × (1÷融資成數) × 100%，低於130%
  （同樣沿用融資的法規門檻）用警示色+徽章標示

兩個「維持率(估)」都是估算值，不是真實維持率（真實維持率是帳戶層級資料，交易所不公布
單一股票的精確數字）。20日均價當融資/放空成本基準是業界慣例做法，融券維持率的公式方向
刻意跟融資相反（分子分母對調）以反映風險方向相反這件事，見
`docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md`。

## User Stories

1. As Cody，我想在個股列表看到「融資佔比」欄位，這樣能知道這檔股票有多少籌碼是做多槓桿部位。
2. As Cody，我想在個股列表看到「融資維持率(估)」欄位，這樣能抓出哪些股票的融資部位接近斷頭。
3. As Cody，我想在個股列表看到「融券餘額佔比」欄位，這樣能知道這檔股票被放空的深度有多少。
4. As Cody，我想在個股列表看到「融券維持率(估)」欄位，這樣能抓出哪些股票的融券部位接近
   被軋空（股價漲多少會讓空方受不了）。
5. As Cody，我想融資維持率(估)/融券維持率(估)低於130%時都有明顯的警示色跟徽章，不用自己
   記門檻數字，也不用分別記兩個方向各自的門檻（兩者共用130%）。
6. As Cody，我想這四欄都能點欄名排序，這樣能直接把風險最高的幾檔排到最前面，不用一檔一
   檔點開看。
7. As Cody，如果一檔股票融資餘額是0（沒人用融資買），我想融資佔比/融資維持率(估)看到「─」
   而不是沒意義的數字；融券餘額是0時，融券餘額佔比/融券維持率(估)同樣顯示「─」。
8. As Cody，我想知道融資佔比/融券餘額佔比用的集保資料是哪一天的，因為它是每週更新，可能
   比其他欄位（收盤、量比）舊——不想誤以為全部欄位都是當天數字。
9. As Cody，我想清楚知道兩個「維持率(估)」都是估算值不是真實維持率，避免我或其他人誤以為
   這是精確數字去做重大決策。
10. As Cody，我想融資/融券兩組欄位各自把「佔比」跟「維持率」擺在相鄰位置（而不是把兩組的
    佔比放一起、兩組的維持率放一起），這樣看單一方向（多方或空方）的完整風險時比較方便。

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
`chips_df`（已有，含 `margin_balance`、`short_balance`）、新增 `total_shares_df`
（`get_latest_total_shares()` 輸出）、`avg20_map`（`calc_avg20_close()` 輸出）。每支股票算出：

```
financing_ratio = 0.6 if exchange == "TWSE" else 0.5   # 注意股/處置股例外不處理，見 Out of Scope

# 多方（融資）
financed_pct = margin_balance * 1000 / total_shares * 100        # None 若 margin_balance 為 0/None 或 total_shares 缺
maintenance_est = close / avg20 / financing_ratio * 100          # None 若 avg20 缺；margin_balance=0 也回 None（見下）

# 空方（融券）——風險方向跟融資相反，公式分子分母對調
shorted_pct = short_balance * 1000 / total_shares * 100          # None 若 short_balance 為 0/None 或 total_shares 缺
short_maintenance_est = avg20 / close / financing_ratio * 100    # None 若 avg20 缺；short_balance=0 也回 None（見下）
```

`financed_pct`／`maintenance_est` 若融資餘額為0或缺值，兩欄都回傳 None（前端顯示「─」）；
`shorted_pct`／`short_maintenance_est` 若融券餘額為0或缺值，兩欄都回傳 None——即使兩個
「維持率(估)」公式本身不需要對應的餘額當輸入，沒有部位的股票顯示這個數字沒有意義（見
`CONTEXT.md`「融資維持率(估)」「融券維持率(估)」定義）。

同時回傳 `total_shares_asof`（`get_latest_total_shares()` 的 date 欄位），供前端顯示
「集保資料：YYYY-MM-DD」提示。

**HTML/CSS/JS**：`export/index_generator.py` 的個股列表相關函式（`renderStockListItem`、
`_sortValue`、`sortStockList`）新增四欄，順序為多方一組、空方一組各自相鄰：
- 表頭「股票/收盤/漲跌%/量比/**融資佔比**/**融資維持率(估)**/**融券餘額佔比**/
  **融券維持率(估)**/5日/7日/10日/14日」
- 「融資佔比」「融券餘額佔比」欄旁邊（或表頭 tooltip）顯示集保資料實際日期
- 「融資維持率(估)」「融券維持率(估)」低於130%：警示色（`var(--down)`）+ 粗體 + 徽章
  （比照既有 `vol-burst-badge` 的視覺慣例，新增 `maint-badge` class，兩個維持率欄共用
  同一套 class／門檻邏輯）
- 融資佔比/融券餘額佔比不設警示門檻，純數字顯示（沒有客觀依據硬設門檻，見討論記錄）
- 四欄都可點欄名排序，`_sortValue()` 新增對應 key

## Testing Decisions

- `calc_avg20_close()`／`get_latest_total_shares()` 是純函式，比照 `tests/test_processors.py`／
  `tests/test_database.py` 既有模式：臨時 DB 塞造資料，驗證輸出正確
  - 測試 `get_latest_total_shares()` 的 per-stock fallback（某股集保資料比整表最新日期舊，
    仍要抓到自己的最新一筆，不是回空）
  - 測試 `calc_avg20_close()` 資料不滿20天時用實際天數平均，不強湊
- `build_stock_detail_data()` 的四個新欄位計算：構造真實情境數字（複刻這次討論用的真實
  案例，例如凌華 close=159.5、20日均價=139.35、TWSE、融資佔比1.55%、融資維持率190.8%）
  驗證融資公式正確；另外構造融券情境（現價高於20日均價，代表放空者已經虧損、維持率
  低於100%）驗證融券維持率公式方向相反、確實跟融資算法對稱；驗證融資餘額=0時融資兩欄
  回None、融券餘額=0時融券兩欄回None（兩組各自獨立判斷，不互相影響）
- 個股列表排序/徽章 JS 行為：比照既有 `test_generate_renders_volume_ratio_column_with_burst_badge`
  的模式，加對應測試斷言四個表頭都存在、可排序、融資/融券維持率各自低於130%時徽章正確出現
- 只測試外部行為（函式輸出、HTML 是否含正確文字/欄位），不測試內部實作細節

## Out of Scope

- 不處理注意股/處置股等可能有不同融資成數的例外情況（估算一律用交易所預設值 60%/50%，
  多空雙方共用同一套比例假設）
- 不做「融資使用率」（融資餘額÷融資限額，另一個已查到但決定不採用的官方精確指標，
  見 `CONTEXT.md`）
- 不為「融資佔比」「融券餘額佔比」設警示門檻/徽章
- 不處理融券的其他規則細節（如平盤下不得放空、融券保證金追繳實際流程等），估算只聚焦
  在「維持率距離130%多近」這個單一數字

## Further Notes

- 融資側的兩個指標已經用真實資料庫驗證過公式（工業電腦38檔真實查詢，見
  `docs/superpowers/mockups/2026-07-28-stocklist-margin-columns-preview.html`），今天這批
  真實資料沒有任何一檔融資維持率(估)低於130%，警示狀態的視覺樣式是用建構範例展示，不是
  這批真實資料觸發的
- 融券側兩個指標是本次追加討論的結果，尚未做過真實資料驗證，實作時應比照融資側的做法
  （抓真實 `short_balance` 資料驗證公式），不能只憑公式推導就視為正確
- 設計討論見 `CONTEXT.md`（融資佔比/融資維持率(估)/融券餘額佔比/融券維持率(估)/融資使用率/
  融資成數等詞彙定義）與 `docs/adr/0002-margin-maintenance-ratio-is-an-estimate.md`
