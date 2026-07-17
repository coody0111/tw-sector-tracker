# `calc_meta_observation_scores()` 觀察分設計 Spec（v2 Plan 2/3）

**日期**：2026-07-17
**狀態**：定案，待寫 plan 實作
**上游依據**：`docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md` §2.2「主流族群優先序」、§6「`processors/performance.py`：共用 `calc_meta_observation_scores()` 作為族群優先序」

---

## 1. 這是什麼、不是什麼

「觀察分」（observation score）是逆轟策略 v2 頁面「四層決策模型」的**第二層**（見 v2 spec §2）：決定哪些族群值得優先展開檢視，**不是**買賣訊號、**不是**族群強弱的最終定論。

**共用對象**：這支函式由 `main.py` 每天呼叫一次，**同時**供 `index.html`（首頁族群總覽，目前排序邏輯是 `main.py:637-653` 呼叫 `calc_universe_performance()`/`calc_meta_performance()` 後直接依 `avg_change_pct` 排序，沒有任何綜合分）跟未來的 `export/momentum_generator.py`（Plan 3，尚未建立）共用消費，確保兩個頁面對「今天資金在哪個主流族群」給出同一個答案，不會各自產生互相矛盾的排序邏輯。**把 `index.html` 排序邏輯實際換成消費這支函式的輸出，是 Plan 3 的整合工作，不在本次範圍**——本次只交付 `calc_meta_observation_scores()` 這支函式本身跟它的測試。

---

## 2. 為什麼不直接沿用既有4支函式的組合呼叫

v2 spec 只給了5個因子的權重比例，沒有給精確公式（跟 Plan 1 的3個 Task 不同——Plan 1 的算法在 spec 裡已經完整定案可以直接抄，這裡需要先設計）。討論過程中比較了兩種實作路線：

- **組合呼叫既有4支函式**（`calc_cumulative_meta`/`calc_universe_performance`/`calc_meta_signals`/`calc_meta_chips_signals`）：優點是不重複邏輯、單一真相來源；缺點是每次呼叫都要開4條獨立 DuckDB 連線、查詢重疊的資料表。
- **完全獨立實作**（本次定案）：單一連線一次查完 `daily_prices`/`institutional`/`margin`，效能較好、跟既有4支函式完全隔離、互不影響。

**代價（刻意接受的取捨，不是疏忽）**：`calc_meta_chips_signals()` 裡面的跨交易所涵蓋度判斷邏輯（`partial_coverage`，約100行，判斷 TWSE/TPEx 資料是否同步到齊）會在 `calc_meta_observation_scores()` 裡重寫一份。這代表：

> ⚠️ 之後若 `calc_meta_chips_signals()` 的 `partial_coverage` 判斷邏輯被修正（例如發現新的 bug），`calc_meta_observation_scores()` 裡重寫的那份**不會自動跟進**，需要人工同步。這是 Cody 明確拍板的決定，接受這個維護成本換取效能與隔離性。

---

## 3. 五個因子的精確定義

| 因子 | 權重 | 原始值定義 | 「不可用」條件 |
|---|---|---|---|
| 相對強度 | 30% | `meta_cum3 - universe_cum3`（該族群近3個交易日等權平均累積報酬 − universe 整體等權平均近3個交易日累積報酬） | universe 或該族群累積報酬資料不足3個交易日 |
| 族群廣度 | 25% | `up_count / total_stocks`（今日該族群上漲檔數 ÷ 今日該族群有 `change_pct` 資料的檔數） | 該族群今日完全沒有股票有 `change_pct` 資料 |
| 延續性 | 20% | `min(max(streak, 0), 5) / 5`（連漲天數，正整數，封頂5天=滿分；0或負值＝連跌或持平＝0分） | 該族群完全查無近期價格資料（實務上極少見） |
| 成分股量能參與 | 15% | 族群集合量比 = 今日該族群成交量總和 ÷ 近5個交易日均量總和 | 資料不足6個交易日（沿用既有 `calc_meta_signals()` 的既有門檻慣例） |
| 籌碼確認 | 10% | `foreign_buy_ratio` = 外資買超檔數 ÷ 該族群當日**實際有資料**的交易所涵蓋檔數 | `partial_coverage=True`（族群橫跨多交易所但當日只有部分交易所資料到齊）或該族群今日完全沒有籌碼資料 |

**原始值** (`rs_raw`/`breadth_raw`/`continuation_raw`/`volume_raw`/`chips_raw`) 全部保留在回傳資料裡供 UI 顯示（例如頁面上顯示「+3.2% vs 大盤」而不是排名百分位數字）。

### 3.1 歸一化

- **相對強度**、**成分股量能參與**：原始值不是自然 0~1（cum3差值可能 -5%~+8%、集合量比可能 0.3~3.0），加權前先做「當日跨族群百分位排名」轉成 0~1（用法跟既有 `scan_momentum_health()` 的 `rs_rank_pct` 同一套技巧——不用猜任何人為切點，且不管當天族群表現好壞都能自動拉開差距）。
- **族群廣度**、**籌碼確認**：定義本身就是 0~1 比例，直接使用，不再排名。
- **延續性**：定義本身已封頂正規化到 0~1（見上表），不再排名。

### 3.2 資料來源（獨立查詢，不呼叫既有4支函式）

單一 DuckDB 唯讀連線，依序查：

1. `daily_prices`（近期資料，供 cum3/廣度/延續性/量能參與用）
2. `institutional`（供籌碼確認的外資買超檔數用）
3. `margin`（`partial_coverage` 判斷需要；沿用 `calc_meta_chips_signals()` 已驗證過的既有慣例——**margin 要用 margin 自己的最新日期，不能綁 institutional 的 today**，兩表發布日可能不同步，見 `processors/performance.py:669-671` 的既有註解）

查完立即 `con.close()`，後續全部用 pandas 在記憶體裡完成 5 個因子的計算、百分位排名、加權。

---

## 4. 資料不足時的 reweight 機制

```
score_coverage = 可用因子的權重總和
observation_score = round(100 * Σ(可用因子權重 × 該因子0~1分數) / score_coverage, 1)
```

用 `score_coverage` 校正分母，避免「剛好缺一項資料」的族群系統性被拉低分數（例如缺籌碼資料時，分母是 0.90 而不是 1.0，不會讓分數莫名其妙掉10分）。

**邊界情況**：

- 若5個因子全部不可用（`score_coverage == 0`）→ `observation_score = None`，**仍然回傳這筆**（不從結果消失），讓消費端（generator）可以顯示「資料不足」而不是該族群憑空消失，避免使用者誤以為某族群不存在。
- 涵蓋範圍：回傳所有「在至少一個因子來源裡有出現」的族群聯集，不限定只回傳 `config.py::META_SECTORS` 裡列出的族群（若某族群完全無資料，見上一條，仍回傳但分數是 `None`）。

---

## 5. 函式簽章

```python
def calc_meta_observation_scores(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
) -> Dict[str, Dict[str, Any]]:
    """
    首頁與逆轟頁共用的「觀察分」，決定族群優先展開順序（非最終買賣動作）。

    完全獨立實作：不呼叫 calc_cumulative_meta()/calc_universe_performance()/
    calc_meta_signals()/calc_meta_chips_signals()，單一 DuckDB 連線查完
    daily_prices/institutional/margin 後在記憶體算完。刻意的設計決定，換取
    效能（不用開4次連線）與跟既有4支函式的完全隔離；代價是 partial_coverage
    等邏輯與 calc_meta_chips_signals() 重複一份，兩邊之後各自修正不會自動
    同步，見本文件 §2。

    Returns
    -------
    {meta_name: {
        "observation_score": float | None,  # 0~100，5因子全不可用時 None
        "score_coverage": float,            # 0~1，實際可用權重比例
        "rs_raw": float | None,             # cum3差值（%），供UI顯示原始值，非0~1
        "breadth_raw": float | None,        # 今日上漲比例（0~1，本身就是最終用於加權的值）
        "continuation_raw": int | None,     # streak天數（原始整數，未封頂，供UI顯示）
        "volume_raw": float | None,         # 集合量比（原始值，非0~1）
        "chips_raw": float | None,          # foreign_buy_ratio（0~1，本身就是最終用於加權的值）
        "partial_coverage": bool,           # 籌碼資料是否涵蓋不全（chips_raw為None時的原因標記）
    }}
    """
```

---

## 6. 驗收條件

- [ ] 5個因子的原始值計算正確（尤其相對強度是 cum3 差值、不是單日 `daily_excess_pct` 也不是 cum5/cum7，避免跟 Plan 1 剛修正過的「週期別搞混」問題重蹈覆轍）。
- [ ] 延續性封頂邏輯：連漲6天以上跟連漲5天分數要相同（都是滿分1.0）；連跌或持平都是0分，不會出現負分。
- [ ] 相對強度、量能參與的百分位排名：至少2個族群時能正確拉開差距；只有1個族群時排名固定是1.0（不crash、不除以零）。
- [ ] `score_coverage` 隨缺失因子正確調整（缺籌碼時是0.90，缺籌碼+量能參與時是0.75）。
- [ ] 5因子全不可用時回傳 `observation_score=None`、`score_coverage=0`，該族群仍在結果裡（不從dict消失）。
- [ ] `partial_coverage` 判斷邏輯跟 `calc_meta_chips_signals()` 既有版本行為一致（同樣輸入應該得到同樣的 `partial_coverage` 判斷結果，即使是兩份獨立程式碼）。
- [ ] margin 資料用自己的最新日期，不綁 institutional 的日期（沿用既有慣例，見 §3.2）。
- [ ] 所有計算不使用未來資料（no look-ahead）。
- [ ] nullable 欄位（`volume`/`change_pct`/`foreign_net`/`margin_balance` 等）比照 Plan 1 這輪抓到的4次教訓，NA/NaN 一律映射成文件裡承諾的 `None`，不洩漏成 `float('nan')`、不讓未防呆的 `bool()`/`int()`/`float()` 對 NA 值直接 crash。

---

## 7. Out of scope（本次不做）

- 把 `index.html` 的排序邏輯換成實際消費這支函式（屬於 Plan 3 整合工作）。
- `export/momentum_generator.py` 本身（Plan 3）。
- 回測驗證這5個因子的權重/門檻是否真的有效（跟 v2 spec §5/§8 一致，回測是獨立任務，不跟資料層/計算邏輯開發綁在一起；Cody已明確表示「先用推薦的作法，之後回測不OK再換」，這份 spec 裡的所有數值都屬於實驗性、待回測校準）。
- 修正 `calc_meta_chips_signals()` 既有的 `partial_coverage` 邏輯本身（如果之後發現有 bug，是另一個獨立任務，且修正後別忘了本文件 §2 提到的「兩邊不會自動同步」）。
