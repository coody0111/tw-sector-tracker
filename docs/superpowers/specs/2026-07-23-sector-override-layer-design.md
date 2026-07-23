# 族群分類校正層 設計 (2026-07-23)

## 背景與問題

族群分類目前的資料流：

```
main.py --update-sectors  →  scrapers/moneydj.py 爬 MoneyDJ (約15分)
                          →  data/sectors/industry_sectors.csv (中繼檔)
scripts/build_universe.py →  讀 industry_sectors.csv
                          →  依 config.py 的 META_PRIORITY_LIST 取第一個命中的 META
                          →  data/stock_universe.csv (main.py 每日流程實際讀取的檔)
```

兩個問題：

1. **build 目前無法重跑**：`data/sectors/industry_sectors.csv` 已不存在（`data/sectors/` 為空，該中繼檔未進 git、`--update-sectors` 未近期執行）。`build_universe.py` 少了輸入檔，直接 pandas `FileNotFoundError`。
2. **MoneyDJ 自動分類會錯放**：MoneyDJ 的產業/概念 tag 加上 `META_PRIORITY_LIST` 的優先序，會把「三五族磊晶／光通訊上游材料」吃進最高優先的「晶圓代工」。例如：
   - 聯亞(3081)、全新(2455)、環宇-KY(4991) → 被歸「晶圓代工」，實際是光通訊上游（InP/GaAs 磊晶、LD/PD）。
   - 光聖(6442) → 被歸「連接器」（⚠️ 也在光通訊），實際光通訊佔營收約 80%。
   - 對照財報狗「題材」分類，上述皆屬「光通訊」題材。

## 目標

- **MoneyDJ 自動分類為底**，加一層**人工校正**，用財報狗「題材」佐證特定錯放個股。
- 校正必須**在 build 重跑後仍存活**（目前 `build_universe.py` 會整檔覆蓋 `stock_universe.csv`，手改會被沖掉）。
- **範圍收斂**：只做針對性校正，**不做全族群對照財報狗**的審計。首批處理光通訊那叢。

## 非目標 (YAGNI)

- 不改用財報狗為分類主來源（財報狗頁面為 SPA，無法程式化整批取得題材成員名單）。
- 不重寫 MoneyDJ 爬蟲或 `META_PRIORITY_LIST` 的關鍵字優先序（整批搬「砷化鎵/磊晶」會誤傷穩懋、環宇這類砷化鎵**射頻代工**）。
- 不做全 1038 檔的族群審計。

## 架構

### ① 修復 build 管線

- `data/sectors/industry_sectors.csv` 由 Cody 執行 `python main.py --update-sectors` 重新產出（約 15 分；依 CLAUDE.md，資料抓取由 Cody 跑，開發者不自跑）。
- `build_universe.py` 增加輸入檔缺失時的**明確錯誤訊息**（提示先跑 `--update-sectors`），取代裸 `FileNotFoundError`。

### ② 校正層檔案 `data/sector_overrides.csv`（新增，git tracked）

欄位：

| 欄位 | 說明 |
|---|---|
| `stock_id` | 股票代號（字串，保留前導零） |
| `meta_sector` | 要覆蓋成的 META 族群 |
| `sub_sector` | 要覆蓋成的子族群 |
| `source_note` | 校正依據（例：`財報狗題材:光通訊`） |

規則：
- 允許只想改 meta 的情況；`sub_sector` 留空時，沿用自動分類算出的 sub（不強制一起改）。
- 檔案 git tracked，異動會過 review、可跨機同步。

### ③ `build_universe.py` 套用校正

在自動分類算完每檔的 `meta`/`matched_sub` 之後、寫出 `stock_universe.csv` 之前，最後套用 overrides：

- 讀 `data/sector_overrides.csv`（不存在則視為無校正、照常執行）。
- 對每個命中 `stock_id` 的列：
  - `meta_sector` ← override 的 meta。
  - `sub_sector` ← override 的 sub；override 的 sub 留空則保留原自動 sub。
  - `note` ← `手動校正:<source_note>`，並**清除**原本的 ⚠️ 爭議標記。
- override 名單裡若有 universe 中不存在的 `stock_id`（下市／代號錯），在 build 報告中列出警告，不中斷。

### ④ 種子資料

`data/sector_overrides.csv` 初始內容：

```
stock_id,meta_sector,sub_sector,source_note
2455,光通訊,光通訊,財報狗題材:光通訊
3081,光通訊,光通訊,財報狗題材:光通訊
4991,光通訊,光通訊,財報狗題材:光通訊
6442,光通訊,光通訊,財報狗題材:光通訊
```

過渡期：這 4 檔目前已直接手改在 `data/stock_universe.csv`（build 尚未能重跑前保持有效）。待 Cody 重跑 `--update-sectors` + `build_universe.py` 後，改由 overrides CSV 自動接手，兩者結果一致。

## 資料來源相關（CLAUDE.md 要求）

- 本變更**只影響族群分類（universe 建置）**，不碰每日行情/籌碼的 TWSE/TPEx 來源，不涉歷史回補。
- 上市/上櫃資料來源無混用疑慮。

## 測試策略

- `build_universe.py` 的 override 套用邏輯抽成可單元測試的函式，測：
  - override 命中 → meta/sub 被覆蓋、⚠️ 被清除。
  - override 的 sub 留空 → 保留自動 sub。
  - override 指到不存在的 stock_id → 產生警告、不中斷。
  - 無 overrides 檔 → 行為與現況相同。
- 輸入檔缺失 → 給明確錯誤而非裸例外。

## 分工

- **開發者（我）**：`build_universe.py` 的 override 邏輯與缺檔錯誤處理、建立 `data/sector_overrides.csv` 種子、單元測試。
- **Cody**：執行 `--update-sectors` 重建 `industry_sectors.csv`、之後重跑 `build_universe.py` 驗證校正生效。
- **Debugger**：驗證分類正確、來源無混用、不影響其他模組。

## 風險與注意

- `data/sectors/` 與 `industry_sectors.csv` 若被 gitignore，重建後仍只在執行機生效——但 `stock_universe.csv` 是 tracked，最終產物會同步，故校正結果可跨機一致。
- `.gitignore` 第 1 行 `data/` 會 ignore 整個 data 目錄；`stock_universe.csv` 是當初 `git add -f` 強制追蹤的（無 `!` 例外）。新檔 `data/sector_overrides.csv` 同樣需**一次 `git add -f`** 納入追蹤，之後改動即照常同步，不需改 `.gitignore`。
- override 是「以個股硬蓋分類」，屬人工維護清單；規模應保持小而精，避免變成第二套分類規則。
