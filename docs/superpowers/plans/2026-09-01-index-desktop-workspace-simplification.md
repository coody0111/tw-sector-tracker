# Index 桌面工作區精簡實作計畫

## 依據

- Spec：`docs/superpowers/specs/2026-09-01-index-desktop-workspace-simplification-design.md`
- 主要實作：`export/index_generator.py`
- 產生檔：`docs/index.html`，不手動修改

## 需求對照

| Spec | 實作決策 | 驗證 |
|---|---|---|
| §4.1–4.4 | 固定精簡 Header；市場、巨量換手、Top 10 依序使用同一內容寬度 | HTML 順序與不存在性測試 |
| §4.4、§6 | 卡片資料完整內嵌；瀏覽器端處理 Top 10／全部、搜尋、排序與進階篩選，狀態寫入 localStorage | 產生器字串契約＋瀏覽器驗證 |
| §4.5 | 新增互斥 `build_research_buckets()`；異動優先，其次觀察，最後避開，並保留衝突標記 | 純 Python 分類、排序、上限測試 |
| §5 | 移除可見轉折點、法人悄悄佈局、重複量能排行與常駐五級圖例；改用 tooltip／指標說明 | 不存在性測試 |
| §7、§10 | `selectGroup()` 改為右側 drawer；搜尋、摘要與 `#meta=` 共用；保留 STOCKS/CARD_META 與 XSS escaping | JS 契約＋瀏覽器鍵盤驗證 |
| §8 | `main.py` 透傳盤中／收盤模式；Header 顯示資料模式與產生時間 | HTML 模式測試 |
| §9 | 1440px 5×2；窄螢幕 drawer 退回全寬，控制列可換行且不水平破版 | 視覺驗證 |

## 實作順序

1. 先建立研究分類純函式與資料欄位。
2. 重寫首頁可見區塊與卡片精簡版 HTML。
3. 加入 client-side 排序、篩選、持久化與說明面板。
4. 把 inline detail 改為 drawer，補 focus restoration、Esc 與 deep link。
5. 更新聚焦測試與 Debugger 交接紀錄。

## 暫不混入

- Oliver Kell Market Structure。
- 逆轟策略分類重做。
- 自選股獨立頁。
- 排程器的 60 日快照檔案生命週期；本輪先完成頁面資料模式標示，檔案留存另由排程層計畫承接。
