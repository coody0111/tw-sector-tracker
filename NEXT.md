# 交接 / 接下來做什麼（always-current）

> 這份是**單一、最新的「接下來做什麼」**。每次收工覆寫更新，永遠反映當前狀態。
> 詳細日誌在 `debug-tasks.md`；設計在 `docs/superpowers/specs/`、實作步驟在 `docs/superpowers/plans/`。

**最後更新：2026-07-14（下班前）**

---

## 換機開工先做
1. `git pull`（強制版：`git fetch && git reset --hard origin/master`）。
2. ⚠️ `data/` 與 `notes/` 是 gitignored、**不會同步**——真實資料只在原本那台。
3. 讀這份 → `debug-tasks.md` 置頂 →（要動 code 才讀）對應 spec/plan。

## 目前進行中的主線：籌碼面重構 + 回測

### 待做（依順序）
1. **review 3 份新文件**（有要改先改）：
   - `docs/superpowers/specs/2026-07-14-accumulation-score-design.md`（進貨分）
   - `docs/superpowers/specs/2026-07-14-backtest-framework-design.md`（回測地基）
   - `docs/superpowers/plans/2026-07-14-backtest-framework.md`（回測 plan，6 Task）
2. **執行「回測地基」plan**（6 Task，建議 subagent 驅動）→ 做完拿真實 8 年資料跑巨量換手，看各 regime 有沒有 edge。
3. **拆「進貨分」plan** → 再實作（accumulation-score spec 還沒拆 plan）。

### 關鍵洞見（今天實證，影響設計，別忘）
- **籌碼 = 配角（逆轟 50 分）**：三族群（功率/被動/載板）報酬龍頭法人籌碼幾乎全 0；投信重壓的反而平庸。
- **→ 進貨分絕不單獨選股**、價格/動能為主、籌碼加分確認；三來源都留；不倒扣連賣；多邊同買加權（待回測）。
- **⚠️ 單一 regime 限制**：結論來自 5/26→7/14 輪動市（全市場 +0.8%、無空頭樣本）→ 回測要按 regime 分段。

### 待決定 / 未查
- `momentum-health-signal`（07-02 spec+plan）**做了沒**？= 筆記 B2 出場三原則（保命側、CP 最高），待查。
- 逆轟藍圖個股層 **B1–B5**（均線 5/10/60、出場、RS、連續漲停）整片未動。
- `open` 開盤價被 import 丟掉（`screener/database.py:179`）→ 回測 D+1 進場暫用收盤退路；要真開盤需 `CAST(open AS DOUBLE)` + reimport。

## 已完成（近期，都在 origin）
- 大戶持倉待修 **#1–#8 全完成**（缺週/離群值/NaN guard/缺週回補/清髒值），**195 passed**。
- 籌碼面重構 brainstorming → 上面 3 份文件。
- 更早：大盤分級儀表板、chips tab 重整、shareholder 分層、data_date 跨交易日修復、死碼清理等（見 git log / debug-tasks）。

---

## 每日執行 / 部署（不變）
- 每日：`python main.py`（TWSE + TPEx 官方 API）→ 產 `docs/*.html` → 自動 commit/push。
- 部署：GitHub Pages → `docs/index.html`、`docs/chips.html`。
- 歷史回補：`--backfill-shareholder N`（現在只補缺週）、`--backfill-twse` / `--backfill-yf`。
