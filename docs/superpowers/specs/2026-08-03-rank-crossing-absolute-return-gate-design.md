# 排名進出榜：加上絕對報酬閘門

## Problem Statement

「排名進出榜」（`find_rank_crossings()`）目前純粹比較「這週排名」vs「上週排名」是否跨過前10名
門檻，完全不看族群自己的絕對報酬方向。這會在**全市場普遍走弱**的時候產生誤導：某族群本週
5日複利報酬是 **-1.21%**（負的），只因為上週更慘（-9.6%），就被列進「剛進榜」，看起來像是
在噴，但其實只是「跌最少」。Cody 實際看到「散熱 #24→#1」這筆時，驗證數字沒有算錯，但這種
呈現方式不是他要的——相對排名在這種情境下會誤導人。

## Solution

在「剛進榜／剛掉出榜」的判定上，除了原本的「跨過前10名門檻」，再加一個**絕對報酬閘門**：

- **剛進榜**：原本條件（上週不在前10、這週進前10）之外，還需要**這週自身5日複利報酬 > 0%**
- **剛掉出榜**：原本條件（上週在前10、這週掉出前10）之外，還需要**這週自身5日複利報酬 < 0%**

門檻值訂在 **0%**（單純看正負號），不額外要求幅度。不滿足絕對報酬閘門的跨榜（例如「跌最少
擠進榜」或「漲最少被擠出榜」）不會出現在任一份清單裡——不算誤判成剛進榜，也不會另外歸類，
單純從這次的名單消失。

## Scope

只改 `find_rank_crossings()`（頁面最下面的「排名進出榜」子區塊）。**不改**
`calc_meta_rank_history()` 本身的排名計算邏輯、也不改單一族群「歷史出現紀錄」用到的
`in_top10_this_week`/`consecutive_weeks_in_top10`（那些維持現狀，純看排名<=10，不加絕對
報酬閘門）——這兩個功能顯示的是「有沒有進前10」的歷史走勢，跟「排名進出榜」要回答的問題
不同，Cody 這次的反饋只針對「排名進出榜」這個子區塊。

## Implementation Decisions

**`processors/performance.py::calc_meta_rank_history()`**：目前每週迴圈算出的
`week_pcts: Dict[str, float]`（每個meta這週的5日複利報酬）只拿來排名，排完名數值本身就丟掉
了。需要額外把這個數值保留下來，比照 `weekly_ranks` 的做法新增一個平行欄位
`weekly_returns: List[float]`（舊到新，長度跟 `weekly_ranks` 一致，資料不足的週一樣不硬湊）。

```python
# 迴圈裡新增 week_pcts_by_week 累積(跟 week_ranks_by_week 平行)
week_pcts_by_week: List[Dict[str, float]] = []
for i in range(weeks_available):
    ...
    week_pcts_by_week.append(week_pcts)  # 排名前先存一份原始複利報酬

# 每個meta的結果新增 weekly_returns（做法比照 weekly_ranks_raw 的過濾邏輯）
weekly_returns_raw = [week_pcts_by_week[i].get(meta_name) for i in range(weeks_available)]
weekly_returns = [r for r in weekly_returns_raw if r is not None]
results[meta_name] = {
    "weekly_ranks": weekly_ranks_raw,
    "weekly_returns": weekly_returns_raw,  # 新增，跟weekly_ranks_raw index對齊
    ...
}
```

**`export/index_generator.py::find_rank_crossings()`**：讀取新增的 `weekly_returns`，取最後一筆
（這週）當絕對報酬閘門的判斷依據：

```python
def find_rank_crossings(rank_history: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    just_in = []
    just_out = []
    for meta_name, data in rank_history.items():
        ranks = data.get("weekly_ranks") or []
        returns = data.get("weekly_returns") or []
        if len(ranks) < 2:
            continue
        prev_rank, cur_rank = ranks[-2], ranks[-1]
        cur_return = returns[-1] if returns else None
        prev_in = prev_rank <= 10
        cur_in = cur_rank <= 10
        if not prev_in and cur_in and cur_return is not None and cur_return > 0:
            just_in.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})
        elif prev_in and not cur_in and cur_return is not None and cur_return < 0:
            just_out.append({"meta_name": meta_name, "prev_rank": prev_rank, "cur_rank": cur_rank})

    just_in.sort(key=lambda r: r["prev_rank"] - r["cur_rank"], reverse=True)
    just_out.sort(key=lambda r: r["cur_rank"] - r["prev_rank"], reverse=True)
    return {"just_in": just_in, "just_out": just_out}
```

**`export/index_generator.py::_sector_recap_html()`**：更新排名進出榜的說明小字，反映新定義
（目前文案「跟上週排名比較，不是自身動能」在加了絕對報酬閘門後不再準確，需要調整成同時提到
排名跨榜+自身報酬方向一致才會列入）：

```
現在：這週剛擠進/掉出前10名的族群（跟上週排名比較，不是自身動能——跟上面「轉折點」是不同角度的訊號）
改成：這週剛擠進/掉出前10名、且自身報酬方向一致的族群（單純排名進步但自身仍是負報酬、或退步但自身仍是正報酬，不算——跟上面「轉折點」是不同角度的訊號）
```

## Testing Decisions

- 新增/調整 `tests/test_processors.py` 裡 `calc_meta_rank_history` 相關測試，驗證
  `weekly_returns` 欄位存在、數值跟排名用的複利報酬一致、長度與過濾規則跟 `weekly_ranks`
  對齊。
- 調整 `tests/test_index_generator.py` 裡 `find_rank_crossings` 相關測試：
  - 既有測試如果假設「純排名跨榜就算進出榜」，需要補上 `weekly_returns` 讓數值為正/負以符合
    新閘門，維持原本斷言成立
  - 新增回歸測試：排名從外到內跨榜、但這週自身報酬是負的 → **不列入** just_in（這正是
    「散熱」這個案例的重現）
  - 新增回歸測試：排名從內到外跨榜、但這週自身報酬是正的 → **不列入** just_out（對稱情境）

## Out of Scope

- 不改 `calc_meta_rank_history()` 的排名計算邏輯本身（複利公式、5日滾動窗定義都不動）
- 不改 `in_top10_this_week`/`consecutive_weeks_in_top10`/`last_top10_week_index`/
  `last_top10_rank`（單一族群「歷史出現紀錄」用的欄位），維持純排名判定
- 不改「轉折點列表」（tier轉換訊號），兩者依然是獨立子類別（`docs/adr/0003-rank-crossing-signal-kept-separate-from-tier-signal.md` 的核心決定不變——這次只是替「排名進出榜」自己
  這一個訊號加內部一致性檢查，不是要把它跟tier訊號合併）
- 絕對報酬閘門門檻固定0%，不做成可調參數

## Further Notes

- 這次修改讓「排名進出榜」不再是「純相對排名」訊號，需要記一筆ADR說明為什麼在
  `0003` 已經論證「相對排名的矛盾本身是有意義資訊」之後，還是決定加絕對報酬閘門——
  差別在於：`0003` 討論的是「要不要跟另一個獨立訊號（tier）合併」，這次是「同一個訊號内部
  要不要有自我一致性檢查」，範疇不同，`0003`的結論不受影響。
