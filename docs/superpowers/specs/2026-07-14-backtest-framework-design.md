# 回測地基一般化 + 超額報酬設計

**日期**：2026-07-14
**作者**：Developer（與 Cody brainstorming 後）
**狀態**：草案，待 Cody review

---

## 背景與痛點

我們要把「規則看起來合理」升級成「**過去這樣選，N 天後真的賺、而且贏大盤**」才採用（逆轟筆記反覆強調的自我驗證；Debugger 最想把關）。現況 `screener/backtest.py`：

- ✅ **雛型對**：逐歷史交易日 D → 跑訊號 → 查 D+1/D+3/D+5 報酬 → 算勝率/平均/贏輸/期望值。
- ❌ **只綁一個訊號**（`scan_volume_turnover` 巨量換手），型態/進貨分插不進來。
- ❌ **沒有 benchmark**：只報絕對報酬。選到的股 D+5 賺 2% 可能只是大盤那週漲 2%，跟選股無關 → **無法判斷「真的有價值」**。
- ❌ **進場價不真實**：用 D 收盤（＝算訊號用的那根）當進場，現實當天收盤前不知道；動能派選到的常是強勢股，D+1 開盤可能漲停買不到。
- ❌ 只有短天期、用原始股價、沒扣成本。

## 目標

把 `backtest.py` 一般化成「**評估任一選股訊號的預測力**」的地基：任一 scanner → 逐日選股 → **D+1 開盤進場** → 多天期 **超額報酬**（減大盤同期）→ 勝率/期望值/贏輸不對稱。

**先驗價格/型態訊號**（daily_prices 有 8 年、389 交易日，樣本夠）。**進貨分暫不驗**（法人僅 52 天、大戶僅 7 週，樣本太小、結論不可信）——這點在進貨分 spec 已註明。

## 非目標（本 spec 不做）

- **規則出場回測**（抱到跌破5MA下彎長黑才出）：更真實，但需要「出場三原則」邏輯（動能派筆記 B2，尚未實作）。本次先做**固定持有**當比較基準。
- **進貨分/籌碼訊號回測**：等籌碼資料累積幾個月。
- 參數最佳化/過度擬合搜尋：只做「驗證單一設定有沒有 edge」，不掃參數。

---

## 方法設計

### 核心流程（逐訊號、無 lookahead）

對每個歷史交易日 D：
1. `scanner(D, db_path)` → 當日選到的股票清單（**只能用 ≤ D 的資料**，scanner 本來就這樣，無 lookahead）。
2. 每檔算進場與後續報酬：
   - **進場價 = D+1 開盤**（現實：D 收盤後才知訊號，隔日才進）。
   - **漲停買不到**：若 D+1 開盤 ≥ D 收盤 ×1.095（近漲停）→ 標 `no_fill=True`，主結果**剔除**（另存一份「理想含漲停」對照）。
   - **報酬（多天期）**：對 H ∈ {5, 10, 14}，`ret_H = (adj_close[D+1+H] / adj_open[D+1] − 1) ×100`。
   - **超額報酬**：`excess_H = ret_H − benchmark_H`（見下）。
   - **扣成本**：`ret_H`、`excess_H` 一律扣 **來回 0.6%**（手續費+證交稅估）。
3. 匯總：勝率、平均超額報酬、贏平均/輸平均、期望值，**分天期 + 分訊號**。

### Benchmark（判斷「有沒有價值」的唯一標準）

- 主基準：**大盤同期報酬**（TAIEX，`taiex` 資料源；同一進出區間 D+1→D+1+H）。
- 「有 edge」= 平均 **excess > 0** 且勝率站得住（不是絕對報酬 > 0）。
- （次要，可選）等權 universe 同期報酬當第二對照，看是不是只贏在選市場。

### Scanner 介面（一般化的關鍵）

```python
Scanner = Callable[[str, str], list[dict]]   # (date_str, db_path) -> [{"stock_id","close",...}, ...]

def run_backtest(scanner: Scanner, db_path=..., horizons=(5,10,14),
                 cost_pct=0.6, limit_up_skip=True) -> pd.DataFrame: ...
```

- 既有 `scan_volume_turnover`、型態掃描 `scan_patterns`（或包一層）都符合這個 shape → 直接插入。
- 之後 `進貨分` 也是「算分→取高分股」的 scanner，同一套驗。

---

## 資料相依（先講清楚，有兩個前置）

1. **🔴 開盤價 open 目前被 import 丟掉**：`screener/database.py:179` 寫死 `NULL::DOUBLE AS open`（動能派筆記 B2 已發現）。D+1 開盤進場需要 open。
   - **近期解（一行）**：改 `CAST(open AS DOUBLE)`（high/low 同）+ reimport；每日爬蟲 CSV 本來就有 OHLC。
   - **退路**：open 沒補齊前，進場價**暫用 D+1 收盤**（略失真但可先跑通流程），spec 標明。
2. **🟡 還原股價**：daily_prices 是原始價，除權息當天跳空下修會被誤算成大跌 → 假輸。
   - v1：報酬計算**排除除權息日進出**，或標記；完整還原股價是更大工程（見 `project_data_sync_gap`，yfinance 還原價本身有髒值），不在本次。
3. 大盤 benchmark 需要 `taiex` 有對應日期資料（大盤分級儀表板已在用）。

---

## 架構與介面（單元）

- **`run_backtest(scanner, ...)`**（改寫既有）：吃 scanner + 參數，回每列一個 (訊號日, 股票, 進場, 各天期 ret/excess/no_fill) 的 DataFrame。純讀 DB。
- **`_benchmark_returns(dates, horizons)`**：算大盤各進出區間報酬，供相減。
- **`print_summary(df)`**（升級）：加「平均**超額**報酬」「漲停剔除前後」兩塊；沿用勝率/贏輸/EV。
- 邊界：資料不足（新股、H 天後沒資料）→ 該天期 NaN、匯總時 `dropna`（不污染平均，比照專案慣例）。

## 測試策略

`tests/test_backtest.py`（擴充既有）用**合成 price DB**（可控報酬）驗：
1. **無 lookahead + D+1 進場**：訊號日 D 選到 X，進場價確實是 D+1 open、不是 D close。
2. **超額報酬**：股票漲 5%、大盤同期漲 3% → excess ≈ 2%（扣成本後）。
3. **漲停剔除**：D+1 開盤 ≥ D 收 ×1.095 → `no_fill=True`、主結果不計。
4. **成本**：ret 有扣 0.6%。
5. **缺資料**：H 天後無報價 → 該天期 NaN、不 crash。
6. **一般化**：傳入一個假 scanner（回固定選股）→ run_backtest 正確串接（不綁死巨量換手）。

---

## 落地順序（給 writing-plans 參考）

1. 一般化 `run_backtest(scanner, ...)` + 假 scanner 測試（不動報酬邏輯）。
2. 加 benchmark 超額報酬 + 成本。
3. D+1 開盤進場 + 漲停剔除（相依：open import；未補前用 D+1 收盤退路）。
4. 升級 `print_summary`。
5. 拿 `scan_volume_turnover` + 型態掃描實跑一發，看有沒有 edge（真實 8 年資料）。

## 後續 follow-up

- 補 open import（`CAST(open AS DOUBLE)` + reimport）讓 D+1 開盤真實。
- 出場三原則邏輯 → 規則出場回測（比固定持有真實）。
- 籌碼資料累積足夠 → 進貨分回測校準。
