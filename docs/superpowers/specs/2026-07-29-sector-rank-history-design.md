# 族群排名歷史：排名進出榜＋歷史出現紀錄

## Problem Statement

使用者（Cody）看族群總覽頁時，只能看到「今天」的排名跟「跟昨天比」的排名跳動（異動族群），
沒辦法回答兩個常見問題：
1. 「這個族群這禮拜比上禮拜表現好還是差？有沒有剛擠進/掉出重要排名？」（頁面層級，
   不用點進單一族群就想先知道誰在變化）
2. 「我點進這個族群，它是不是常客？上次強勢是什麼時候？」（單一族群層級，想知道這個
   族群近期排名的軌跡，不是只看今天）

現有的「轉折點列表」只回答「這個族群自己的動能分級有沒有換級」，答不了「這個族群打不打得
贏其他族群」這個相對排名的問題。

## Solution

在「族群近況」區塊新增子類別「排名進出榜」：比較「這週」跟「上週」的排名（前10名門檻），
列出剛跨過門檻進榜／掉出榜的族群。

在單一族群詳細面板新增「歷史出現紀錄」：顯示近5週（5個交易日滾動視窗為一週單位）的精確
排名軌跡，加一句文字摘要（有上榜講連續幾週進榜，沒上榜講上次進榜是第幾週第幾名）。

兩者都即時從 `daily_prices` 全歷史用「目前的族群分類」重新計算，不存週快照表——族群分類
本身會變動（見 `docs/adr/0001-sector-rank-history-recomputed-not-snapshotted.md`），存快照
會讓歷史資料卡在過期分類上。

跟既有「轉折點列表」並存，不合併（見 `docs/adr/0003-rank-crossing-signal-kept-separate-from-tier-signal.md`）。

## User Stories

1. As Cody，我想在族群近況區塊看到「這週剛擠進前10名」的族群清單，這樣不用一個個點開族群
   就能發現誰在變強。
2. As Cody，我想在族群近況區塊看到「這週剛掉出前10名」的族群清單，這樣能發現誰在退燒。
3. As Cody，我想在點進單一族群的詳細面板時，看到這個族群近5週的精確排名（不是只有上榜/
   榜外的二元標示），這樣能判斷它是差一點還是差很遠。
4. As Cody，我想在單一族群面板看到一句文字摘要（連續N週進榜，或上次進榜是第幾週第幾名），
   不用自己從5個數字裡推算。
5. As Cody，如果一個族群近5週都沒有進過前10名，我想看到明確的「近5週都沒有進前10」訊息，
   不是一堆數字讓我自己判斷。
6. As Cody，我想「排名進出榜」跟既有「轉折點列表」分開顯示，因為它們回答不同問題（相對
   排名 vs 自身動能），合併會讓矛盾的訊號被抹平。
7. As Cody，我想這個功能不受族群分類調整影響——如果之後修正了某個族群的分類，我想看到的
   歷史排名是「用最新分類回推」的結果，不是卡在舊分類上的過期資料。

## Implementation Decisions

**新函式**：`processors/performance.py` 新增 `calc_meta_rank_history()`，比照現有
`calc_meta_heatgrid_windows()` 的模式（同一個檔案、同樣從 `daily_prices` 全歷史用
`universe_df` 的 `meta_sector` 分組，pivot 出 meta_sector × date 的資料表，再逐週切片）。

- 輸入：`universe_df`（含 `meta_sector` 欄）、`db_path`、`weeks_back`（預設 5）
- 「週」＝5個交易日滾動視窗（沿用 `cum5`/`roll5` 慣例，見 `CONTEXT.md`）。第N週的
  排名 = 用該週最後一個交易日往前5天的平均 `change_pct` 排序全部 meta_sector 得出的名次
- 回傳每個 meta_sector 的：近5週精確名次 list（含本週）、本週是否進前10、若進前10則連續
  進榜週數、若未進前10則最近一次進榜的週次索引與當時名次（若5週內都沒進榜則為 None）
- 排名以「目前」的 `universe_df` 分類為準，不管歷史上該族群叫什麼名字或分類是否變過

**頁面層級「排名進出榜」**：`export/index_generator.py` 新增函式（比照 `find_turning_points()`
的模式），輸入 `calc_meta_rank_history()` 的結果，比較每個族群「本週排名」vs「上週排名」，
輸出剛跨過前10門檻進榜／掉出榜的族群 list。掛進 `build_sector_recap()` 的回傳字典，新增
`rank_crossings` 鍵（`{"just_in": [...], "just_out": [...]}`）。

**HTML/CSS**：`_sector_recap_html()` 新增一個獨立區塊，接在既有 `.turning-wrap` 後面
（不塞進 `.status-cols` 的6欄Top5網格——那個網格假設固定顯示排行前5名，跟「進出榜」
筆數不固定的資料形狀不合，見 `docs/superpowers/mockups/2026-07-29-sector-recap-rankmove-position-compare.html`
比較過的兩種版面）。標題「排名進出榜」，左右兩欄分別列「剛進榜」/「剛掉出榜」。

**單一族群「歷史出現紀錄」**：`_meta_detail_panel_html()`（或等價的族群詳細面板生成函式）
新增一個區塊，讀 `calc_meta_rank_history()` 該族群的資料：
- 5格橫向排列，每格顯示週次標籤（W-4~本週）+ 精確名次（tabular-nums），前10名的格子
  用 accent 色邊框標出來
- 上方一句文字摘要：本週有進前10 → 「連續N週進榜」；本週沒進前10但近5週內曾進榜 →
  「上次進榜是W-x，當時排第Y名」；近5週內都沒進榜 →「近5週都沒有進前10」

**資料不足時的行為**：族群若歷史交易日不滿 25 天（5週×5天），能算幾週就顯示幾週，不足的
週次不強湊假資料（比照 `calc_meta_heatgrid_windows()` 現有的 `_window_is_real()` 防呆模式，
真實資料不足時該格回 None，不用 0 或上一筆頂替）。

## Testing Decisions

- `calc_meta_rank_history()` 是純函式（輸入 universe_df + db_path，輸出 dict），比照
  `tests/test_processors.py` 裡 `calc_meta_heatgrid_windows`/`calc_cumulative_meta` 既有的
  測試模式：用臨時 DuckDB + 手動塞造測試資料，驗證排名計算正確
  - 測試「用今天分類回推」：同一族群在歷史資料裡改變 meta_sector 對應，驗證排名用最新
    分類重算，不會用歷史當時的分類
  - 測試連續進榜週數計算正確
  - 測試「近5週都沒進榜」與「上次進榜在第幾週」的邊界情況
  - 測試歷史資料不滿5週時的部分結果（不強湊）
- 頁面層級「剛進榜/剛掉出榜」比對邏輯：比照 `tests/test_index_generator.py` 裡
  `find_turning_points`/`build_sector_recap` 既有測試模式，構造真實情境數字（例如複刻
  這次討論用的散熱 #14→#3、半導體設備 #7→#28 案例）驗證輸出正確
- 只測試外部行為（函式輸入輸出、HTML 是否含正確文字/區塊），不測試內部實作細節

## Out of Scope

- 不處理族群分類的「族群分類校正層」（`data/sector_overrides.csv`，筆電那邊在討論的另一個
  獨立議題）
- 不新增任何資料庫表（不存週快照，见 ADR 0001）
- 不影響既有「轉折點列表」的邏輯或欄位

## Further Notes

- 這個功能不需要等資料庫累積新資料才能用——因為是即時從 `daily_prices` 全歷史重算，
  只要現有歷史資料涵蓋足夠交易日（目前資料庫回溯到 2025-01-02，遠超過5週所需的25個
  交易日），上線當天就有完整的5週歷史可以顯示
- 設計討論見 `CONTEXT.md`（族群/週/上榜/排名進出榜/轉折點列表/動能分級/歷史出現紀錄
  等詞彙定義）與 `docs/adr/0001-*.md`、`docs/adr/0003-*.md`
