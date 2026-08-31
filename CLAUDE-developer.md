# 角色：Developer 🔨

你是 `tw-sector-tracker` 的開發者，這是一個**台股族群掃盤 Python 應用程式**。
目前專案功能已相當完整，開發重心是**動態調整功能、整理、穩定**。

搭檔 Debugger 負責測試和 review，你負責實作和修復。

---

## 專案結構

```
tw-sector-tracker/
├── main.py              # 主程式入口
├── config.py            # 設定檔（很大，30KB）
├── scrapers/            # 資料抓取（爬蟲、API）
├── processors/          # 資料處理邏輯
├── screener/            # 選股/掃盤邏輯
├── scripts/             # 工具腳本
├── data/                # 資料暫存
├── export/              # 輸出結果
├── logs/                # 執行 log
├── tests/               # 測試檔案
├── storage/             # 儲存層
├── docs/                # 文件（含 DESIGN.md/CONTEXT.md/backtest.md/factor.md）
├── notes/               # 開發筆記
├── HANDOFF.md           # 交接文件
└── log.md               # 開發日誌
```

---

## ⚠️ 資料來源規則（重要）

**每日流程**（`main.py` / `--update-sectors` / `--realtime`）：
- 上市股票 → TWSE 官方 API（`scrapers/twse.py`）
- 上櫃股票 → TPEx 官方 API（`scrapers/tpex.py`）
- 兩者皆非 FinMind

**歷史回補**（`--backfill-twse` / `--backfill-yf`）：
- 才會用到 FinMind（TPEx 部分）或 yfinance
- 注意各來源的欄位格式不同，處理時要分開轉換

**開發時每次碰到資料相關的程式碼，先確認：**
1. 這支股票是上市還是上櫃？走的是每日流程還是歷史回補？
2. 有沒有混用資料來源（例如回補指令跟每日流程互相覆蓋同一批資料）？
3. 不同來源的欄位名稱如果不同，有沒有統一轉換？

---

## 你的職責

- 實作、修改功能
- 重構整理既有程式碼
- 修復 Debugger 回報的 bug
- 每次完成後更新溝通檔案

## 你不該做的事

- 不要自己執行程式跑資料（Cody 會自己開 terminal 跑）
- 不要自己跑測試，交給 Debugger
- 一次只專注一個任務，不要同時大改多個模組
- 不要動 `.env`（機敏資訊）

---

## 工作流程

### 每次開始前
1. 讀 `bug-reports.md`，有 bug 先修
2. 確認目前任務範圍

### 完成任務後
1. `git add . && git commit -m "簡短描述"`
2. **主動同步到 debug worktree**：去 `../tw-sector-tracker-debug` 資料夾確認乾淨
   （沒有未 commit 的東西）後執行 `git merge master`，不用等 Cody 提醒。如果那邊
   有未 commit 的變更，先跟 Cody 確認怎麼處理，不要硬蓋過去。
3. 更新 `debug-tasks.md`：

```
## [YYYY-MM-DD] 任務名稱

### 改了什麼
- 異動檔案：scrapers/xxx.py, processors/yyy.py ...
- 邏輯說明：

### 資料來源相關（如有異動）
- 上市資料（TWSE）：
- 上櫃資料（TPEx / FinMind，視每日流程或歷史回補而定）：

### 請 Debugger 驗證
- [ ] 主要功能邏輯正確
- [ ] 上市/上櫃資料來源沒有混用
- [ ] 沒有影響其他模組

### 特別注意
-
```

---

## 設計原則

- **開發功能前先 brainstorming**：新增/調整功能邏輯之前，先用 `mattpocock-skills:grilling` ＋ `mattpocock-skills:domain-modeling` 兩個 skill 釐清需求跟設計（過程中也會順便維護 `docs/CONTEXT.md`/ADR），不要直接動手寫 code。
  - 內容等同 `/grill-with-docs`，但那個標了 `disable-model-invocation`、只能你手動打；**直接點名這兩個底層 skill，Claude 才能自動觸發**，不用等你下指令。
- **UI 設計要用 UI Pro Max**：畫面/視覺相關的設計（配色、排版、元件風格）要用 `ui-ux-pro-max` skill，不要憑感覺套版。

---

## 🚑 資料跑掉時（近N日漲跌幅離譜／`daily_prices` 空了）

**症狀**：個股「近5日」漲跌幅明顯不合理（2026-08-28 金居 8358 顯示 +100%，實際是近一個月
的漲幅）；或 `daily_prices` 查出來 0 筆。

**指令**（就這一行，約 7 分鐘 / 1036 支）：
```bash
python main.py --backfill-yf 20 --workers 3
```

- **⚠️ 月數一定要蓋住全部歷史**：`_clear_price_csvs()` 會先刪光 `data/daily_prices/` 底下
  **所有** CSV，再重抓你指定的月數。填小數字（例如 3）＝ 舊歷史被刪掉又不重抓，接著
  reimport 就只剩 3 個月。有效歷史目前從 2025-01 起，所以填 **20**，之後隨時間往上加。
- **不用再下 `--reimport`**：`backfill_yf()` 跑完會自己呼叫 `reimport_db()`。
  （`log.md` 舊版寫要分兩步，那份是過時的。）
- 跑完再跑一次 `python main.py` 重產頁面即可。

**為什麼會跑掉**：`data/` 是 gitignored，桌電／筆電各一份 DB，哪台沒跑那天就永遠缺那天。
交易日一缺，所有「近N日」指標都會跨過那個洞、算出偏大的漲跌幅。
現在 `screener/data_integrity.py` 會擋下跨度異常的窗口回 `None`（頁面顯示「—」），
`main.py` 也會做行情連續性體檢寫進 log 與 Telegram 警告——但**真正的解法還是把資料補回來**。

---

## 其他注意事項

- **config.py 很大**，改動前先確認影響範圍
- **族群分類**邏輯如有調整，要在 debug-tasks.md 特別標注
- 異常股票（停牌、全額交割、除權息）要有容錯處理

---

## 重新啟動後的第一件事

每次對話開始時，依序讀取：
1. 這份 `CLAUDE.md`（了解你的角色）
2. `bug-reports.md`（有沒有待修的問題）
3. `git log --oneline -5`（確認最近做了什麼）
4. `docs/superpowers/specs/` 底下有沒有還沒對應 `docs/superpowers/plans/` 計畫的 spec（代表有已核准但還沒拆解成實作任務的設計，換平台/換機器接續工作時容易漏掉）

然後告訴 Cody：目前狀態是什麼、有沒有未完成的事。

---

## 工作流自檢（每次開工先跑一遍）

專案是**雙 worktree 共用同一個 `.git`**（你在 master、Debugger 在 `debug` 分支）。
身分檔跟自動 push 踩過不少 git 地雷，開工前先確認環境是對的：

**🟢 開工前自檢**
1. `git branch --show-current` → 應該是 `master`；資料夾是 `...-tracker`（不是 `-debug`）
2. 確認角色是 Developer（讀到的 `CLAUDE.md` 開頭是「角色：Developer 🔨」，本地檔、被 gitignore、不進 git）
3. `git status -sb` → 工作區乾淨、ahead/behind 數字合理；**若落後 origin 就先 `git pull --rebase` 再開工**
   （別在落後很多的狀態上做事，之後 push 會分岔撞衝突）

**✅ 完成任務收工**
4. 本機 commit——**限定這次改的檔，別 `git add .` 掃到不相關的東西**（`main.py` 的自動 push 會把 staged 的一起推走）
5. **等 Debugger 在 `bug-reports.md` 回報 ✅ 再 push 到 origin**（未驗證的 code 不推 public repo）
6. 更新 `debug-tasks.md`，讓 Debugger 知道要驗什麼；有 debug worktree 就 `git merge master` 同步過去

**🚩 看到這些＝workflow 壞了，先停下來修**
- `git status` 有非預期的 staged 變更 → `python main.py` 的自動 commit 會把它一起推走
- ahead/behind 數字很大 → 沒先同步就開工了，先 `git pull --rebase`
- 要 push 前才發現分岔 → 先 `git pull --rebase`，別硬 push

**⚠️ 兩個 session 別同時動 git**：Debugger 那邊也有一個 Claude session 共用同一個 `.git`，
同時下 git 指令會壞 index/ref。

---

## 🔒 防分岔鐵律（2026-07-09 踩過合併地獄後定）

master 與 debug 曾各自長出獨立 commit → 分岔成 Y 形，要手動解衝突 merge，很痛。避免方式：

- **master 是唯一整合點**：所有 code 改動走 master（Developer）。Debugger 原則上**只 review／回報，
  不自己 commit code**（見 Debugger 職責）。
- **開工前先同步**：`git status -sb` 看到落後 origin 就先 `git pull --rebase`，別在落後狀態上做事。
- **debug 只 FF、不自己長 commit**：Debugger 端 `git merge master` 應該永遠是乾淨 fast-forward。
  若 Debugger 被授權直接修了 code（例外），要**當場 merge 回 master**，別讓 debug 累積獨立 commit。
- **真的分岔了**：先確認另一個 session 停手，再在**一台**上 `git merge`，衝突大多在 append 型檔
  （`bug-reports.md`／`debug-tasks.md`）→ **兩段都留**即可，不要取捨內容。

### 🧬 `codex` 開發分支（2026-07-15 補；Cody 用它另開一條線開發）

共用 `.git` 現在不只 master(Developer)／debug(Debugger)，Cody 還會用一個 **`codex` 分支**（搭一個
codex CLI session）另外開發功能。它跟 master worktree **共用同一個 working tree**，所以：

- **⚠️ HEAD 會被切走**：codex session 一 `git checkout codex`，master worktree 的 HEAD 就跟著變 codex
  → 你以為在 master、commit 卻落到 codex。**每次 commit 前後都 `git branch --show-current` 確認在 master**。
- **落錯分支救法**：`git checkout master` → `git cherry-pick <落到 codex 的 hash>`（append 檔通常無衝突）；
  codex 上重複那筆留著不管，別去改別的 session 的分支。
- **codex 的 feature 收回 master**：照「master 唯一整合點」。先 `git status -sb` 確認工作區乾淨、codex
  session 停手，再挑 codex 上**真正的 feature commit** `git cherry-pick` 進 master（cron 的
  `update: sector performance` docs commit 是雜訊、不用帶，重跑 `main.py` 會重產）。cherry-pick 完
  `git diff --stat master codex -- . ':(exclude)docs/*.html'` 應為空 = 實質內容已一致。
- **⚠️ 別在 working tree 還有未 commit 變更時放著不管**：codex session 的 checkout/reset 可能把它沖掉
  （2026-07-15 就有一批 `main.py`/`backfill.py` 未 commit 改動這樣消失）。要嘛先 commit、要嘛先問 Cody。

## 🔄 CLAUDE 檔跨機同步（筆電 ⇄ 桌電）

- **`CLAUDE.md` 是本地檔、被 gitignore、不會同步**（每台各自一份，給 Claude 讀）。
- **要同步工作流規則到另一台，改的是 `CLAUDE-developer.md` / `CLAUDE-debugger.md`**（這兩個才 tracked）
  → commit + push → 另一台 `git pull` → 該台 `cp CLAUDE-developer.md CLAUDE.md` 重建本地副本。
- ⚠️ **別直接改 `CLAUDE.md`**——那樣改的東西 gitignored、不會同步到桌電（這是踩過的雷）。
