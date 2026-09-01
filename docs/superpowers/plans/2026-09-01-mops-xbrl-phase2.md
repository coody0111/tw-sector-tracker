# MOPS XBRL Phase 2 實作計畫

對應 spec：`docs/superpowers/specs/2026-09-01-mops-xbrl-phase2-design.md`

## Requirements mapping

| Requirement | Implementation | Verification |
|---|---|---|
| 官方清單與版本化 ZIP | `scrapers/mops_xbrl.py` discovery/download | mock HTML、ZIP、hash 測試 |
| XML/iXBRL context facts | `parse_xbrl_instance()` | fixture 單元測試 |
| append-only 版本 | `xbrl_archives`/`xbrl_filings`/`xbrl_facts` | idempotency/新 SHA 測試 |
| canonical current projection | mapping + `xbrl_current_facts` | context、revision 測試 |
| 成長率與 EPS 規則 | `financial_fact_growth` | 缺季、EPS 累計 YoY 測試 |
| 獨立回填指令 | `main.py --backfill-fundamentals` | CLI dispatch 測試 |

## Tasks

1. 建立 XBRL source model、官方清單 parser 與低頻下載 cache。
2. 建立安全 ZIP reader 與 XML／Inline XBRL parser。
3. 建立歷史 QName mapping、context 選擇與單位正規化。
4. 擴充 DuckDB schema、transactional save 與 current projection。
5. 接上 CLI、使用文件、測試案例與 Debugger handoff。
6. 執行 AST／compile／diff 靜態驗證，不跑 pytest 或真實資料。

## Phase 2B 月營收歷史

1. 解析 MOPS `nas/t21/sii|otc` Big5 11 欄整批頁面。
2. 保存 page SHA 與 append-only normalized versions。
3. 依官方 OpenAPI 最新月份控制回填終點，接入同一個 `--backfill-fundamentals`。
4. 補 Big5、合計列、擋頁、版本、report_date 與 MoM／YoY 測試案例。
