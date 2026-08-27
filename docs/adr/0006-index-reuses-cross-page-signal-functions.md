# 首頁跨頁重用 momentum/patterns 的訊號函式，新增「今日/本週異動」合併區塊

**背景**：`index.html` 第二波改版要把原本分散在「異動族群」「族群近況」兩個區塊裡、但本質
都是「族群層級發生變化，值得注意」的訊號（異動族群、轉折點、排名進出榜）合併成一個新區塊
「今日/本週異動」（見 `CONTEXT.md`）。討論過程中發現這個區塊有空間也有必要納入兩個
**個股層級**的真數字訊號：融資背離警示（`processors/performance.py::get_margin_divergence()`）
與連續漲停鎖死（`screener/signals.py::scan_consecutive_limit_up()`）。這兩支函式現有，
但目前只餵給 momentum.html／patterns.html，`index.html` 從未引用過。

**決定**：`index.html` 直接呼叫這兩支既有函式，不重新實作一份 index 專用版本。「今日/本週
異動」區塊內部依時間尺度分兩層：今日層（異動族群、融資背離警示、連續漲停鎖死，三個平列，
都是真數字實色強調）、本週層（轉折點、排名進出榜，並排二欄，套草案標籤）。

**why（重用而非重算）**：這兩支函式本身算的就是全市場個股層級的通用訊號，不是
momentum/patterns 頁面專屬的邏輯，語意上沒有理由為 index.html 另開一份幾乎一樣的計算。
專案裡跨頁共用底層計算函式本來就是既有慣例（`processors/`／`screener/` 本來就是給四個
頁面共用的層），只是這是第一次把「目前只有單一頁面在用」的函式接到第二個頁面，值得記一筆
讓之後改這兩支函式的人知道 index.html 也依賴它們。

**why（轉折點/排名進出榜維持並排二欄，不進一步合併成一個訊號）**：這不是新決定，是延續
`docs/adr/0003-rank-crossing-signal-kept-separate-from-tier-signal.md` 既有結論——兩者
只是搬到新區塊裡的同一個位置相鄰呈現，語意上依然是兩個獨立訊號，沒有因為這次重排而合併。

**代價**：`export/index_generator.py` 現在依賴 `screener/signals.py`（原本主要是
patterns.html／momentum.html 在用的模組），未來修改 `scan_consecutive_limit_up()` 的
回傳格式時，需要記得同步檢查 index.html 的用法，不能只看 momentum/patterns 兩個既有
呼叫端。
