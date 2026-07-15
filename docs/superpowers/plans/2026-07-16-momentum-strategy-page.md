# 逆轟策略頁面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增獨立靜態頁面 `docs/逆轟策略.html`，把動能派五個決策問題收斂成「族群→個股→動作」單一清單，並修好 `scan_consecutive_limit_up()` 缺的起漲日量能確認。

**Architecture:** 新開 `export/momentum_generator.py`（比照 `export/chips_generator.py` 自成一檔慣例），純 Python 計算業務邏輯（tier→動作映射、進出場訊號推導、換股候選判斷、大盤橫幅文案）後，把資料序列化成 JSON 嵌入 `<script>` 標籤，JS 渲染邏輯直接沿用已定案的 `docs/superpowers/mockups/2026-07-16-momentum-strategy-v5-breakout-volume.html`（只把硬寫死的示範資料換成真實 JSON），跟 `chips.html` 現有的「Python 算資料、JS 做互動」分工一致。`scan_consecutive_limit_up()` 新增 `breakout_volume_confirmed` 欄位（純新增、不改既有語意）。最後掛進 `main.py::run()` 既有每日流程，重用已經算好的 `market_regime`/`meta_perf`/`cum_data`，不重新抓 TAIEX。

**Tech Stack:** Python、DuckDB、pandas（既有依賴，無新套件）。

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-15-momentum-strategy-page-visual-design.md`（下稱「spec」）。
- **不修改** `screener/signals.py::scan_bullish_alignment_new_high()`（spec §11.2b 已排除，量能確認缺口留給後續任務）。
- **不修改** `screener/patterns.py::detect_breakout_confirm()`（spec §11.1 已說明為什麼不採用它）。
- **`scan_momentum_health()` 不需要修改**——寫本計畫時重新核對過原始碼，`close`/`ma5`/`ma10`/`ma20`/`ma60`/`ma_alignment`/`ma5_slope_down`/`change_pct`/`entry_confirmed`/`exit_3_rule_triggered`/`rs_score`/`rs_rank_pct`/`rs_market_score`/`strength_tier` 全部已經是既有回傳欄位，消費端可以直接用這些欄位推導出場三原則的三個子條件（`close<ma5`／`ma5_slope_down`／`change_pct<=閾值`），不需要函式本身新增任何東西。**這點修正了 spec §11.1 最後一段「建議修改 scan_momentum_health() 回傳形狀」的說法**——那段是 brainstorming 階段的推測，寫 plan 時重新核對原始碼後發現不成立，這裡照實記錄修正，不誤導後續維護者。
- 不做回測驗證、族群連續天數（「連N日主流」）、盤中戰術、持股清單追蹤（spec §9/§11.4 已排除）。

---

### Task 1: `scan_consecutive_limit_up()` 新增連板起漲日量能確認

**Files:**
- Modify: `screener/signals.py`（`scan_consecutive_limit_up` 函式本體）
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: 無新依賴，沿用函式現有的 `price_df`/`streak`/`i`（迴圈變數，連板起點索引為 `i+1`）。
- Produces: `scan_consecutive_limit_up()` 回傳的每筆 dict 新增 `breakout_volume_confirmed`（`bool | None`）欄位。`True`＝連板起點當天量 ≥ 起點前20個交易日均量×1.5；`False`＝量沒跟上，疑似假突破；`None`＝起點前歷史不足20個交易日，無法判斷。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_signals.py` 加入（放在既有 `test_scan_consecutive_limit_up_single_day_streak_has_none_volume_trend` 之後）：

```python
def test_scan_consecutive_limit_up_flags_breakout_volume_confirmed(tmp_path):
    """連板起點那天（第一根漲停）若量 >= 前20日均量*1.5，breakout_volume_confirmed=True；
    量不夠則 False。用兩檔股票對照：AAAA 起漲日爆量、BBBB 起漲日量平淡。"""
    db_path = tmp_path / "test.db"
    rows = []
    # AAAA：前20個交易日量都在 1000 附近（均量約1000），起漲日(07-12) 量衝到 3000（>=1500門檻）
    for d in range(1, 21):
        rows.append(("AAAA", f"2026-06-{d:02d}", 100.0, 0.5, 1000))
    rows += [
        ("AAAA", "2026-07-12", 110.0, 9.8, 3000),   # 起漲日，爆量
        ("AAAA", "2026-07-13", 121.0, 10.0, 2500),
        ("AAAA", "2026-07-14", 133.1, 10.0, 2000),
    ]
    # BBBB：前20個交易日量都在 1000 附近，起漲日(07-12) 量只有 1100（<1500門檻，量沒跟上）
    for d in range(1, 21):
        rows.append(("BBBB", f"2026-06-{d:02d}", 50.0, 0.5, 1000))
    rows += [
        ("BBBB", "2026-07-12", 55.0, 9.8, 1100),    # 起漲日，量沒跟上
        ("BBBB", "2026-07-13", 60.5, 10.0, 900),
        ("BBBB", "2026-07-14", 66.5, 10.0, 800),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    a = next(r for r in results if r["stock_id"] == "AAAA")
    b = next(r for r in results if r["stock_id"] == "BBBB")
    assert a["breakout_volume_confirmed"] is True
    assert b["breakout_volume_confirmed"] is False


def test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history(tmp_path):
    """連板起點前歷史不足20個交易日（新股）時，breakout_volume_confirmed 應為 None，
    不是猜一個 True/False。"""
    db_path = tmp_path / "test.db"
    rows = [
        # 只有5天歷史可比對均量，不足20天門檻
        ("CCCC", "2026-07-08", 50.0, 0.5, 1000),
        ("CCCC", "2026-07-09", 50.2, 0.5, 1000),
        ("CCCC", "2026-07-10", 50.5, 0.5, 1000),
        ("CCCC", "2026-07-11", 50.8, 0.5, 1000),
        ("CCCC", "2026-07-12", 55.0, 9.8, 3000),   # 起漲日
        ("CCCC", "2026-07-13", 60.5, 10.0, 2500),
        ("CCCC", "2026-07-14", 66.5, 10.0, 2000),
    ]
    _seed_db(db_path, rows)

    results = scan_consecutive_limit_up("2026-07-14", db_path=str(db_path))

    assert results[0]["breakout_volume_confirmed"] is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_signals.py::test_scan_consecutive_limit_up_flags_breakout_volume_confirmed tests/test_signals.py::test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history -q`
Expected: FAIL（`KeyError: 'breakout_volume_confirmed'`）

- [ ] **Step 3: 實作**

在 `screener/signals.py` 找到 `_BREAKOUT_VOL_MULTIPLE`（新常數，加在 `_LIMIT_UP_PCT` 定義之後，約第35行）：

```python
_LIMIT_UP_PCT = 9.5   # 漲停判定門檻，沿用 scan_volume_turnover 既有慣例（見設計文件資料正確性風險）
_BREAKOUT_VOL_MULTIPLE = 1.5  # 連板起漲日量能確認門檻，沿用 scan_volume_turnover/detect_breakout_confirm 既有 1.5 倍慣例
_BREAKOUT_VOL_LOOKBACK_DAYS = 20  # 起漲日均量比較窗口
```

在 `scan_consecutive_limit_up()` 內，`volume_declining_streak` 計算區塊（`if streak >= 2:` 那段）之後，加入起漲日量能確認邏輯：

```python
        # 量縮鎖死判斷（筆記：惜售最強）：連板期間成交量逐日遞減或持平（舊→新）。
        # streak 天數對應的列是 [i+1, today_idx]（含頭尾，已按日期升冪排序）。
        volume_declining_streak = None
        if streak >= 2:
            streak_vols = grp.iloc[i + 1: today_idx + 1]["volume"].tolist()
            volume_declining_streak = all(
                streak_vols[k] <= streak_vols[k - 1] for k in range(1, len(streak_vols))
            )

        # 連板起漲日量能確認（筆記四十五：起漲沒出量=假突破機率高，不追）。
        # 跟 volume_declining_streak 是不同階段的量能訊號：這個看「起點那天」相對它自己
        # 20日均量是否放量，不是看連板期間日與日之間的相對變化。
        breakout_start_idx = i + 1
        pre_breakout = grp.iloc[max(0, breakout_start_idx - _BREAKOUT_VOL_LOOKBACK_DAYS): breakout_start_idx]
        if len(pre_breakout) < _BREAKOUT_VOL_LOOKBACK_DAYS:
            breakout_volume_confirmed = None
        else:
            pre_avg_vol = pre_breakout["volume"].mean()
            breakout_day_vol = grp.iloc[breakout_start_idx]["volume"]
            breakout_volume_confirmed = bool(
                pre_avg_vol > 0 and breakout_day_vol >= pre_avg_vol * _BREAKOUT_VOL_MULTIPLE
            )
```

並在 `results.append({...})` 區塊新增這個欄位：

```python
        uinfo = universe_map.get(str(sid), {})
        results.append({
            "stock_id":                sid,
            "stock_name":              uinfo.get("stock_name", ""),
            "meta_sector":             uinfo.get("meta_sector", ""),
            "close":                   float(today["close"]),
            "change_pct":              float(today["change_pct"]),
            "volume":                  int(today["volume"]),
            "limit_up_streak":         streak,
            "volume_declining_streak": volume_declining_streak,
            "breakout_volume_confirmed": breakout_volume_confirmed,
        })
```

同時更新函式 docstring 的 Returns 段落，加上這個新欄位的說明：

```python
        volume_declining_streak (bool|None，連板期間量是否逐日遞減/持平；
                                  streak<2 時為 None)，
        breakout_volume_confirmed (bool|None，連板起點當天量是否 >= 起點前20個交易日
                                    均量*1.5；起點前歷史不足20日時為 None)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_signals.py::test_scan_consecutive_limit_up_flags_breakout_volume_confirmed tests/test_signals.py::test_scan_consecutive_limit_up_breakout_volume_none_when_insufficient_history -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/signals.py tests/test_signals.py
git commit -m "feat(signals): scan_consecutive_limit_up 新增連板起漲日量能確認(breakout_volume_confirmed)"
```

---

### Task 2: `export/momentum_generator.py` 業務邏輯層（tier動作映射／進出場訊號／大盤橫幅文案／換股候選）

**Files:**
- Create: `export/momentum_generator.py`
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- Consumes: 無外部依賴（純函式，吃已經算好的純量/dict/list，不連 DB）。
- Produces：
  - `_LIMIT_DOWN_PCT = -9.5`、`_EXIT_BIG_BLACK_PCT = -4.0`（本檔案私有常數，見下方「為什麼不跨模組 import」說明）
  - `tier_action_text(strength_tier: str, change_pct: float) -> str`：五級→動作文字映射（spec §7.3/§7.4）
  - `entry_signals(stock_row: dict, bullish_new_high_ids: set) -> list[tuple[str, bool]]`：兩個進場燈號（spec §7.5 欄1第一部分）
  - `exit_signals(stock_row: dict) -> list[tuple[str, bool]]`：三個出場燈號（spec §7.5 欄1第二部分）
  - `regime_banner_content(market_regime: dict) -> dict`：大盤橫幅顯示內容（spec §4），回傳
    `{mode, tier_text, tier_class, meta_text, concentration_text, advice_html}`
  - `resilience_candidates(momentum_results: list[dict]) -> dict`：換股警戒表資料（spec §6），回傳
    `{"resilient": [...], "limit_down": [...]}` 兩個 list

**為什麼不跨模組 import `screener/signals.py` 的私有常數**：`_LIMIT_UP_PCT`／`_EXIT_BIG_BLACK_PCT` 在
`screener/signals.py` 是前底線私有常數（模組內部使用慣例，不對外匯出）。這個新檔案改用同樣的數值
在自己檔案內重新定義同名私有常數，並在註解標明「維持與 screener/signals.py 同步」，不破壞既有模組
的封裝邊界，也不需要為了這次新增而把既有常數改成公開匯出（那是超出本次範圍的既有程式碼改動）。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_momentum_generator.py`：

```python
from export.momentum_generator import (
    tier_action_text, entry_signals, exit_signals,
    regime_banner_content, resilience_candidates,
)


def test_tier_action_text_maps_five_tiers():
    assert tier_action_text("超強", change_pct=3.0) == "超強·隨時加碼"
    assert tier_action_text("強", change_pct=1.0) == "強·續抱"
    assert tier_action_text("整理", change_pct=0.0) == "整理·反彈可出"
    assert tier_action_text("弱", change_pct=-2.0) == "弱·直接出清"


def test_tier_action_text_superweak_without_limit_down_shows_watch_only():
    """超弱但沒跌停：只顯示觀望，不建議放空（筆記三十四：不空漲停的股票，只空跌停的股票）。"""
    assert tier_action_text("超弱", change_pct=-6.0) == "超弱·直接出清觀望"


def test_tier_action_text_superweak_with_limit_down_suggests_short():
    """超弱且當日觸及跌停常數，才顯示可反手放空。"""
    assert tier_action_text("超弱", change_pct=-9.6) == "超弱·跌停可反手放空"
    assert tier_action_text("超弱", change_pct=-9.5) == "超弱·跌停可反手放空"  # 邊界值本身也算觸及


def test_entry_signals_reflects_b3_membership_and_entry_confirmed():
    stock_row = {"stock_id": "2330", "entry_confirmed": True}
    signals_in_b3 = entry_signals(stock_row, bullish_new_high_ids={"2330", "2454"})
    assert signals_in_b3 == [
        ("多頭排列＋創新高（B3清單內）", True),
        ("動能確認：MA5/MA10皆上揚", True),
    ]

    signals_not_in_b3 = entry_signals(stock_row, bullish_new_high_ids={"2454"})
    assert signals_not_in_b3[0] == ("多頭排列＋創新高（B3清單內）", False)


def test_exit_signals_derives_three_conditions_from_existing_fields():
    """出場三原則的三個子條件全部從既有欄位推導，不需要 scan_momentum_health() 額外回傳任何東西。"""
    stock_row = {
        "close": 95.0, "ma5": 100.0, "ma5_slope_down": True, "change_pct": -5.0,
    }
    result = exit_signals(stock_row)
    assert result == [
        ("跌破五日線", True),   # close(95) < ma5(100)
        ("五日線下彎", True),   # ma5_slope_down
        ("重挫長黑", True),     # change_pct(-5.0) <= -4.0
    ]

    stock_row_safe = {
        "close": 105.0, "ma5": 100.0, "ma5_slope_down": False, "change_pct": 1.0,
    }
    result_safe = exit_signals(stock_row_safe)
    assert result_safe == [
        ("跌破五日線", False),
        ("五日線下彎", False),
        ("重挫長黑", False),
    ]


def test_regime_banner_content_selloff_mode():
    market_regime = {"tier": "大跌", "taiex_change_pct": -1.82, "breadth_ratio": 0.28,
                      "concentration_direction": "中小型輪動"}
    content = regime_banner_content(market_regime)
    assert content["mode"] == "selloff"
    assert content["tier_text"] == "大跌"
    assert content["tier_class"] == "down"
    assert "不是清倉不動的時候" in content["advice_html"]
    assert "筆記一" in content["advice_html"]


def test_regime_banner_content_calm_mode():
    market_regime = {"tier": "小漲", "taiex_change_pct": 0.68, "breadth_ratio": 0.61,
                      "concentration_direction": None}
    content = regime_banner_content(market_regime)
    assert content["mode"] == "calm"
    assert content["tier_class"] == "up"
    assert "不用啟動換股警戒" in content["advice_html"]


def test_regime_banner_content_flat_tier_uses_neutral_class():
    market_regime = {"tier": "持平", "taiex_change_pct": 0.1, "breadth_ratio": 0.45,
                      "concentration_direction": None}
    content = regime_banner_content(market_regime)
    assert content["mode"] == "calm"
    assert content["tier_class"] == "flat"


def test_resilience_candidates_splits_resilient_and_limit_down():
    momentum_results = [
        {"stock_id": "2609", "stock_name": "陽明", "change_pct": 1.2, "rs_market_score": 3.02},
        {"stock_id": "2617", "stock_name": "台航", "change_pct": -0.4, "rs_market_score": 1.42},
        {"stock_id": "2023", "stock_name": "燁輝", "change_pct": -9.7, "rs_market_score": -7.88},
        {"stock_id": "9999", "stock_name": "無關股", "change_pct": -1.0, "rs_market_score": -0.5},
    ]
    result = resilience_candidates(momentum_results)

    resilient_ids = [r["stock_id"] for r in result["resilient"]]
    limit_down_ids = [r["stock_id"] for r in result["limit_down"]]
    assert resilient_ids == ["2609", "2617"]  # rs_market_score > 0，依分數降冪
    assert limit_down_ids == ["2023"]          # change_pct <= -9.5
    assert "9999" not in resilient_ids and "9999" not in limit_down_ids  # 兩邊都不符合，不出現


def test_resilience_candidates_limit_down_takes_precedence_over_resilient():
    """理論邊界案例：若一檔股票當日觸及跌停、但5日相對強弱仍是正的（例如前幾日噴很兇），
    優先判定為跌停立刻砍——現在能不能賣是更急迫的判斷，不該同時出現在兩邊。"""
    momentum_results = [
        {"stock_id": "1111", "stock_name": "極端股", "change_pct": -9.6, "rs_market_score": 2.0},
    ]
    result = resilience_candidates(momentum_results)
    assert [r["stock_id"] for r in result["limit_down"]] == ["1111"]
    assert result["resilient"] == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'export.momentum_generator'`）

- [ ] **Step 3: 實作**

建立 `export/momentum_generator.py`：

```python
"""
生成 docs/逆轟策略.html — 動能派選股決策獨立頁面
資料來源：scan_momentum_health() + scan_bullish_alignment_new_high() +
         scan_consecutive_limit_up() + classify_market_regime()
設計依據：docs/superpowers/specs/2026-07-15-momentum-strategy-page-visual-design.md
"""
from datetime import date
from html import escape as _html_escape

# 跌停判斷門檻，跟 screener/signals.py::_LIMIT_UP_PCT(9.5) 對稱，本檔案私有維護
# （不跨模組 import 私有常數，見本檔案模組說明／plan Task 2 說明）。
_LIMIT_DOWN_PCT = -9.5

# 「重挫長黑」門檻，維持與 screener/signals.py::_EXIT_BIG_BLACK_PCT 同步（目前皆為 -4.0）。
_EXIT_BIG_BLACK_PCT = -4.0

_TIER_ACTION = {
    "超強": "超強·隨時加碼",
    "強":   "強·續抱",
    "整理": "整理·反彈可出",
    "弱":   "弱·直接出清",
}


def _esc(value) -> str:
    """HTML-escape 外部資料（股票名稱等），比照 chips_generator.py::_esc() 同一防護。"""
    return _html_escape(str(value)) if value else ""


def tier_action_text(strength_tier: str, change_pct: float) -> str:
    """
    五級 strength_tier → 動作文字（spec §7.3）。
    超弱是特例：只有當日觸及跌停常數才顯示「可反手放空」，否則只顯示觀望
    （筆記三十四：不空漲停的股票，只空跌停的股票，見 spec §7.4）。
    """
    if strength_tier == "超弱":
        if change_pct is not None and change_pct <= _LIMIT_DOWN_PCT:
            return "超弱·跌停可反手放空"
        return "超弱·直接出清觀望"
    return _TIER_ACTION.get(strength_tier, strength_tier or "")


def entry_signals(stock_row: dict, bullish_new_high_ids: set) -> list:
    """
    進場訊號兩燈號（spec §7.5 欄1）：
    1. 多頭排列＋創新高：是否出現在 scan_bullish_alignment_new_high() 今日輸出的
       stock_id 集合內（呼叫端需自行把該函式輸出轉成集合傳進來）。
    2. 動能確認：scan_momentum_health() 既有回傳的 entry_confirmed bool。
    """
    sid = stock_row.get("stock_id")
    return [
        ("多頭排列＋創新高（B3清單內）", sid in bullish_new_high_ids),
        ("動能確認：MA5/MA10皆上揚", bool(stock_row.get("entry_confirmed"))),
    ]


def exit_signals(stock_row: dict) -> list:
    """
    出場三原則三燈號（spec §7.5 欄1），全部從 scan_momentum_health() 既有回傳欄位推導，
    不需要該函式額外回傳任何子欄位：
    1. 跌破五日線：close < ma5
    2. 五日線下彎：ma5_slope_down（既有欄位，直接用）
    3. 重挫長黑：change_pct <= _EXIT_BIG_BLACK_PCT
    """
    close = stock_row.get("close")
    ma5 = stock_row.get("ma5")
    change_pct = stock_row.get("change_pct")
    return [
        ("跌破五日線", close is not None and ma5 is not None and close < ma5),
        ("五日線下彎", bool(stock_row.get("ma5_slope_down"))),
        ("重挫長黑", change_pct is not None and change_pct <= _EXIT_BIG_BLACK_PCT),
    ]


def regime_banner_content(market_regime: dict) -> dict:
    """
    大盤狀態橫幅顯示內容（spec §4）。market_regime 是既有
    processors/performance.py::classify_market_regime() 的回傳 dict，外加呼叫端
    （main.py）已經合併進去的 taiex_change_pct/breadth_ratio。

    回傳 {mode, tier_text, tier_class, meta_text, concentration_text, advice_html}。
    mode ∈ {"calm", "selloff"}；tier_class ∈ {"up","down","flat"}（純樣式用，
    不是 tier 本身，"大漲"/"小漲"→up、"大跌"/"小跌"→down、"持平"→flat）。
    """
    tier = market_regime.get("tier", "持平")
    selloff = tier in ("小跌", "大跌")
    mode = "selloff" if selloff else "calm"

    if tier in ("大漲", "小漲"):
        tier_class = "up"
    elif tier in ("小跌", "大跌"):
        tier_class = "down"
    else:
        tier_class = "flat"

    taiex_pct = market_regime.get("taiex_change_pct")
    breadth = market_regime.get("breadth_ratio")
    taiex_str = f"{taiex_pct:+.2f}%" if taiex_pct is not None else "─"
    breadth_str = f"{breadth * 100:.0f}%" if breadth is not None else "─"
    meta_text = f"加權 {taiex_str} · 上漲家數比 {breadth_str}"

    concentration_direction = market_regime.get("concentration_direction")
    concentration_text = f"資金集中：{concentration_direction}" if concentration_direction else "資金分散：無明顯集中"

    if selloff:
        advice_html = (
            "大盤急殺，<b>不是清倉不動的時候</b>——先看還在紅盤、跌得比大盤少的個股，"
            "把弱勢股（尤其跌停鎖死）換到最強的1～2檔，資金集中不分散。急殺撬開最後那幾檔"
            "鎖漲停時是換股的黃金時間，不是逃跑時機。"
            "<span class=\"src\">依據：筆記一(買紅不買綠)、二十三(換股實戰)、"
            "十四(大殺盤情緒點抓法) · 大盤分級來源："
            "processors/performance.py::classify_market_regime()</span>"
        )
    else:
        advice_html = (
            "盤面平穩偏多，照正常流程走：先看①主流族群、②族群內誰最強，"
            "③符合多頭排列+創新高才進，④出場三原則觸發就出，不用啟動換股警戒。"
            "<span class=\"src\">大盤分級來源："
            "processors/performance.py::classify_market_regime()</span>"
        )

    return {
        "mode": mode,
        "tier_text": tier,
        "tier_class": tier_class,
        "meta_text": meta_text,
        "concentration_text": concentration_text,
        "advice_html": advice_html,
    }


def resilience_candidates(momentum_results: list) -> dict:
    """
    換股警戒表資料（spec §6）。momentum_results 是 scan_momentum_health() 的完整輸出
    （全市場，不限單一族群——換股邏輯不限產業，筆記十四/二十三皆是跨族群找最強）。

    判斷邏輯（沿用既有 rs_market_score 欄位，不重新定義新欄位，見 spec §6）：
    - 跌停鎖死·立刻砍：change_pct <= _LIMIT_DOWN_PCT（優先權最高，若同時符合
      resilient 條件也只算進 limit_down，因為「現在能不能賣」比5日相對強弱更急迫）
    - 弱中透強·可換入：rs_market_score > 0（近5日報酬贏過 universe 等權平均，
      即使當下是急殺盤仍相對抗跌），依 rs_market_score 降冪排列

    回傳 {"resilient": [...], "limit_down": [...]}。
    """
    limit_down = [
        r for r in momentum_results
        if r.get("change_pct") is not None and r["change_pct"] <= _LIMIT_DOWN_PCT
    ]
    limit_down_ids = {r["stock_id"] for r in limit_down}

    resilient = [
        r for r in momentum_results
        if r.get("rs_market_score") is not None and r["rs_market_score"] > 0
        and r["stock_id"] not in limit_down_ids
    ]
    resilient.sort(key=lambda r: r["rs_market_score"], reverse=True)

    return {"resilient": resilient, "limit_down": limit_down}
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator 業務邏輯層(tier動作映射/進出場訊號/大盤橫幅/換股候選)"
```

---

### Task 3: 族群/個股表格資料整理（族群排名、族群內個股排名、streak卡片）

**Files:**
- Modify: `export/momentum_generator.py`（新增函式，加在 Task 2 函式之後）
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- Consumes: Task 2 的 `tier_action_text`/`entry_signals`/`exit_signals`；既有 `calc_meta_performance()` 輸出格式（`meta_name`/`avg_change_pct`/`up_count`/`down_count`/`flat_count`）；`scan_momentum_health()`/`scan_consecutive_limit_up()` 輸出格式。
- Produces：
  - `build_sector_pills(meta_perf: list) -> list[dict]`：spec §7.1，依 `avg_change_pct` 降冪排列，每筆 `{meta_name, rank, avg_change_pct, stock_count}`
  - `build_stock_table(momentum_results: list, bullish_new_high_ids: set) -> dict`：spec §7.2，回傳 `{meta_sector: [stock_dict, ...]}`，每個 `stock_dict` 含族群內排名（`rank`/`total`）、tier chip 動作文字、entry/exit 訊號、均線/相對強弱數值，欄位形狀對齊 mockup v5 的 `SECTORS` JS 物件
  - `build_streak_cards(limit_up_results: list) -> list[dict]`：spec §8，每筆 `{stock_id, stock_name, limit_up_streak, volume_declining_streak, breakout_volume_confirmed}`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_momentum_generator.py` 加入（先加一行 import）：

```python
from export.momentum_generator import build_sector_pills, build_stock_table, build_streak_cards


def test_build_sector_pills_ranks_by_avg_change_pct_descending():
    meta_perf = [
        {"meta_name": "記憶體", "avg_change_pct": 4.82, "up_count": 15, "down_count": 2, "flat_count": 1},
        {"meta_name": "航運", "avg_change_pct": 3.10, "up_count": 7, "down_count": 2, "flat_count": 0},
        {"meta_name": "金融", "avg_change_pct": -1.28, "up_count": 3, "down_count": 12, "flat_count": 1},
    ]
    pills = build_sector_pills(meta_perf)

    assert [p["meta_name"] for p in pills] == ["記憶體", "航運", "金融"]
    assert pills[0]["rank"] == 1
    assert pills[0]["stock_count"] == 18  # 15+2+1
    assert pills[2]["rank"] == 3


def test_build_stock_table_groups_by_sector_and_ranks_within_sector():
    momentum_results = [
        {"stock_id": "2408", "stock_name": "南亞科", "meta_sector": "記憶體",
         "close": 68.4, "change_pct": 6.8, "ma5": 64.2, "ma10": 60.1, "ma20": 55.8, "ma60": 48.3,
         "ma_alignment": "多頭排列", "ma5_slope_down": False,
         "entry_confirmed": True, "exit_3_rule_triggered": False,
         "rs_score": 5.9, "rs_rank_pct": 0.94, "rs_market_score": 6.7, "strength_tier": "超強"},
        {"stock_id": "2344", "stock_name": "華邦電", "meta_sector": "記憶體",
         "close": 27.3, "change_pct": 4.2, "ma5": 26.4, "ma10": 25.6, "ma20": 24.1, "ma60": 22.0,
         "ma_alignment": "多頭排列", "ma5_slope_down": False,
         "entry_confirmed": True, "exit_3_rule_triggered": False,
         "rs_score": 2.1, "rs_rank_pct": 0.50, "rs_market_score": 2.9, "strength_tier": "強"},
        {"stock_id": "2603", "stock_name": "長榮", "meta_sector": "航運",
         "close": 198.0, "change_pct": 9.5, "ma5": 178.2, "ma10": 165.0, "ma20": 150.4, "ma60": 120.8,
         "ma_alignment": "多頭排列", "ma5_slope_down": False,
         "entry_confirmed": True, "exit_3_rule_triggered": False,
         "rs_score": 6.4, "rs_rank_pct": 0.96, "rs_market_score": 7.2, "strength_tier": "超強"},
    ]
    table = build_stock_table(momentum_results, bullish_new_high_ids={"2408", "2603"})

    assert set(table.keys()) == {"記憶體", "航運"}
    assert len(table["記憶體"]) == 2
    memory_ids = [s["stock_id"] for s in table["記憶體"]]
    assert memory_ids == ["2408", "2344"]  # rs_rank_pct 降冪：0.94 > 0.50
    assert table["記憶體"][0]["rank"] == 1
    assert table["記憶體"][0]["total"] == 2
    assert table["記憶體"][0]["action_text"] == "超強·隨時加碼"
    assert table["記憶體"][0]["entry"] == [
        ("多頭排列＋創新高（B3清單內）", True),
        ("動能確認：MA5/MA10皆上揚", True),
    ]
    assert table["記憶體"][0]["ma"] == {"ma5": 64.2, "ma10": 60.1, "ma20": 55.8, "ma60": 48.3}
    assert table["記憶體"][0]["rs"] == {"score": 5.9, "rank": 0.94, "market": 6.7}


def test_build_stock_table_skips_stocks_without_meta_sector():
    """meta_sector 空字串（不在任何族群，例如 universe.csv 資料不完整）的股票不該出現在表格裡，
    避免產生一個空字串當 key 的族群。"""
    momentum_results = [
        {"stock_id": "9999", "stock_name": "無族群股", "meta_sector": "",
         "close": 10.0, "change_pct": 0.0, "ma5": 10.0, "ma10": 10.0, "ma20": 10.0, "ma60": 10.0,
         "ma_alignment": "糾結", "ma5_slope_down": False,
         "entry_confirmed": False, "exit_3_rule_triggered": False,
         "rs_score": None, "rs_rank_pct": None, "rs_market_score": None, "strength_tier": "整理"},
    ]
    table = build_stock_table(momentum_results, bullish_new_high_ids=set())
    assert table == {}


def test_build_streak_cards_carries_breakout_volume_confirmed():
    limit_up_results = [
        {"stock_id": "6770", "stock_name": "力積電", "limit_up_streak": 4,
         "volume_declining_streak": True, "breakout_volume_confirmed": True},
        {"stock_id": "1560", "stock_name": "中砂", "limit_up_streak": 3,
         "volume_declining_streak": True, "breakout_volume_confirmed": False},
    ]
    cards = build_streak_cards(limit_up_results)

    assert cards[0]["stock_id"] == "6770"
    assert cards[0]["breakout_volume_confirmed"] is True
    assert cards[1]["breakout_volume_confirmed"] is False
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py::test_build_sector_pills_ranks_by_avg_change_pct_descending tests/test_momentum_generator.py::test_build_stock_table_groups_by_sector_and_ranks_within_sector tests/test_momentum_generator.py::test_build_stock_table_skips_stocks_without_meta_sector tests/test_momentum_generator.py::test_build_streak_cards_carries_breakout_volume_confirmed -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

在 `export/momentum_generator.py` 加入（`resilience_candidates` 函式之後）：

```python
def build_sector_pills(meta_perf: list) -> list:
    """
    族群篩選 pill 資料（spec §7.1），依 avg_change_pct 降冪排列。
    meta_perf 是既有 processors/performance.py::calc_meta_performance() 的輸出。
    """
    sorted_perf = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
    pills = []
    for i, row in enumerate(sorted_perf):
        stock_count = row["up_count"] + row["down_count"] + row["flat_count"]
        pills.append({
            "meta_name": row["meta_name"],
            "rank": i + 1,
            "avg_change_pct": row["avg_change_pct"],
            "stock_count": stock_count,
        })
    return pills


def build_stock_table(momentum_results: list, bullish_new_high_ids: set) -> dict:
    """
    族群→個股→動作合一主表資料（spec §7.2），依 meta_sector 分組、組內依 rs_rank_pct
    降冪排列（None 視為最低，排最後）。meta_sector 為空字串的股票略過，不建立空字串族群。
    """
    by_sector: dict = {}
    for row in momentum_results:
        sector = row.get("meta_sector")
        if not sector:
            continue
        by_sector.setdefault(sector, []).append(row)

    table = {}
    for sector, rows in by_sector.items():
        ranked = sorted(rows, key=lambda r: (r["rs_rank_pct"] is None, -(r["rs_rank_pct"] or 0)))
        total = len(ranked)
        sector_stocks = []
        for i, row in enumerate(ranked):
            sector_stocks.append({
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "close": row["close"],
                "change_pct": row["change_pct"],
                "rank": i + 1,
                "total": total,
                "rs_rank_pct": row["rs_rank_pct"],
                "tier": row["strength_tier"],
                "action_text": tier_action_text(row["strength_tier"], row["change_pct"]),
                "entry": entry_signals(row, bullish_new_high_ids),
                "exit": exit_signals(row),
                "ma": {
                    "ma5": row["ma5"], "ma10": row["ma10"],
                    "ma20": row["ma20"], "ma60": row["ma60"],
                },
                "rs": {
                    "score": row["rs_score"], "rank": row["rs_rank_pct"],
                    "market": row["rs_market_score"],
                },
            })
        table[sector] = sector_stocks
    return table


def build_streak_cards(limit_up_results: list) -> list:
    """最強型態卡片資料（spec §8），依 scan_consecutive_limit_up() 既有降冪排序直接沿用。"""
    return [
        {
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "limit_up_streak": row["limit_up_streak"],
            "volume_declining_streak": row["volume_declining_streak"],
            "breakout_volume_confirmed": row["breakout_volume_confirmed"],
        }
        for row in limit_up_results
    ]
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（全部，含 Task 2 的測試）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator 族群/個股表格資料整理(build_sector_pills/build_stock_table/build_streak_cards)"
```

---

### Task 4: HTML 頁面生成（`generate()` 主函式，CSS+JS 沿用 mockup v5）

**Files:**
- Modify: `export/momentum_generator.py`（新增 `generate()` 及 CSS/JS 常數，加在檔案最後）
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- Consumes: Task 2/3 所有函式的輸出。
- Produces: `generate(trade_date: date, market_regime: dict, momentum_results: list, bullish_new_high_results: list, limit_up_results: list, meta_perf: list, output_path: str = "docs/逆轟策略.html") -> bool`。回傳是否實際寫入（`momentum_results` 為空時不寫檔、回傳 `False`，比照 `chips_generator.py::generate()` 既有慣例）。

**CSS 沿用來源**：`docs/superpowers/mockups/2026-07-16-momentum-strategy-v5-breakout-volume.html` 第2-183行的完整 `<style>` 內容，逐字複製進 `_CSS` 常數字串，不重新設計（該版本已經過 5 輪與 Cody 的視覺定案）。

**JS 沿用來源**：同一份 mockup 第405-525行的 `renderStocks`/`selectSector`/`toggleTheme` 三個函式邏輯**大致保留**，資料來源從硬寫死的 `SECTORS` 常數改成 Python 用 `json.dumps()` 序列化 Task 3 算好的真實資料。**拿掉的部分**：`applyRegime()`／`REGIMES` 雙模式字典／`toggleRegime()` 示範按鈕全部不留——正式頁面的大盤橫幅由 Task4 `generate()` 直接把 `regime_banner_content()` 算好的文案伺服端渲染進 HTML（見下方 `generate()` 程式碼裡的 `{banner['tier_text']}` 等內插），不需要客戶端切換兩種示範狀態。**一處刻意偏離 mockup 的地方**：`selectSector(el, name)` 改成 `selectSector(el)`，族群名稱改用 `data-meta-name` 屬性讀取（`el.dataset.metaName`），不再把名稱直接內插進 `onclick="...'...'..."` 的 JS 字串常值——`_esc()` 只做 HTML escape，不是 JS 字串 escape，直接內插若名稱含單引號會弄壞 JS；`export/html_generator.py`（`_meta_card`/`_sector_mini_card`）已經用 `data-meta-name` 屬性存實際名稱、onclick 只傳安全的合成 id 這個既有安全慣例，這裡照抄，不是新發明。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_momentum_generator.py` 加入（先加一行 import）：

```python
from export.momentum_generator import generate


def _sample_momentum_results():
    return [
        {"stock_id": "2408", "stock_name": "南亞科", "meta_sector": "記憶體",
         "close": 68.4, "change_pct": 6.8, "ma5": 64.2, "ma10": 60.1, "ma20": 55.8, "ma60": 48.3,
         "ma_alignment": "多頭排列", "ma5_slope_down": False,
         "entry_confirmed": True, "exit_3_rule_triggered": False,
         "rs_score": 5.9, "rs_rank_pct": 0.94, "rs_market_score": 6.7, "strength_tier": "超強"},
    ]


def test_generate_returns_false_and_skips_write_when_no_momentum_data(tmp_path):
    output_path = tmp_path / "momentum.html"
    market_regime = {"tier": "小漲", "taiex_change_pct": 0.5, "breadth_ratio": 0.55,
                      "concentration_direction": None}

    result = generate(date(2026, 7, 16), market_regime, [], [], [], [], output_path=str(output_path))

    assert result is False
    assert not output_path.exists()


def test_generate_returns_true_and_writes_when_data_present(tmp_path):
    output_path = tmp_path / "momentum.html"
    market_regime = {"tier": "小漲", "taiex_change_pct": 0.5, "breadth_ratio": 0.55,
                      "concentration_direction": None}
    meta_perf = [{"meta_name": "記憶體", "avg_change_pct": 4.8, "up_count": 1, "down_count": 0, "flat_count": 0}]

    result = generate(
        date(2026, 7, 16), market_regime, _sample_momentum_results(), [], [], meta_perf,
        output_path=str(output_path),
    )

    assert result is True
    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "逆轟策略" in html
    assert "南亞科" in html


def test_generate_escapes_malicious_stock_name(tmp_path):
    """股票名稱來自 universe.csv/資料源，頁面會發布到 GitHub Pages，比照 chips_generator.py
    既有防護，不能讓竄改過的名稱注入成可執行標籤。"""
    output_path = tmp_path / "momentum.html"
    market_regime = {"tier": "小漲", "taiex_change_pct": 0.5, "breadth_ratio": 0.55,
                      "concentration_direction": None}
    meta_perf = [{"meta_name": "記憶體", "avg_change_pct": 4.8, "up_count": 1, "down_count": 0, "flat_count": 0}]
    malicious_results = [{
        "stock_id": "9999", "stock_name": '<script>alert(1)</script>', "meta_sector": "記憶體",
        "close": 10.0, "change_pct": 1.0, "ma5": 9.0, "ma10": 9.0, "ma20": 9.0, "ma60": 9.0,
        "ma_alignment": "多頭排列", "ma5_slope_down": False,
        "entry_confirmed": False, "exit_3_rule_triggered": False,
        "rs_score": 1.0, "rs_rank_pct": 1.0, "rs_market_score": 1.0, "strength_tier": "強",
    }]

    generate(date(2026, 7, 16), market_regime, malicious_results, [], [], meta_perf, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert '<script>alert(1)</script>' not in html


def test_generate_selloff_mode_includes_resilience_section(tmp_path):
    """急殺模式下，換股警戒區塊的資料應該出現在頁面（用 json 序列化嵌入，檢查資料值而非 HTML 結構）。"""
    output_path = tmp_path / "momentum.html"
    market_regime = {"tier": "大跌", "taiex_change_pct": -1.82, "breadth_ratio": 0.28,
                      "concentration_direction": "中小型輪動"}
    meta_perf = [{"meta_name": "記憶體", "avg_change_pct": -2.0, "up_count": 0, "down_count": 1, "flat_count": 0}]
    momentum_results = _sample_momentum_results()
    momentum_results[0]["rs_market_score"] = 5.0  # 弱中透強候選

    generate(date(2026, 7, 16), market_regime, momentum_results, [], [], meta_perf, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "換股到哪" in html
    assert "南亞科" in html  # 出現在 resilience 表格的 JSON 資料裡
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py::test_generate_returns_false_and_skips_write_when_no_momentum_data tests/test_momentum_generator.py::test_generate_returns_true_and_writes_when_data_present tests/test_momentum_generator.py::test_generate_escapes_malicious_stock_name tests/test_momentum_generator.py::test_generate_selloff_mode_includes_resilience_section -q`
Expected: FAIL（`ImportError: cannot import name 'generate'`）

- [ ] **Step 3: 實作**

先讀取 mockup 第2-183行的完整 CSS，在 `export/momentum_generator.py` 檔案開頭 import 區塊補上：

```python
import json
from pathlib import Path
```

在檔案最後加入（CSS 內容從 `docs/superpowers/mockups/2026-07-16-momentum-strategy-v5-breakout-volume.html`
第2-183行逐字複製，這裡以省略號標示複製範圍，實作時完整貼上不省略）：

```python
_CSS = """
:root{
  --bg:#080B12; --panel:#0F1420; --panel-2:#161D2C; --panel-3:#1E2738;
  --border:#293346; --border-2:#37435C;
  --ink:#DADFE8; --ink-2:#98A0B4; --ink-3:#636B80;
  --up:#E6432F; --down:#37B25C;
  --accent:#F0BB55; --accent-dim:#B98A3A;
  --tier-super:#F0BB55; --tier-strong:#4FC46A; --tier-mid:#8B94AC; --tier-weak:#E08A3E; --tier-superweak:#E6432F;
  --serif: Georgia,"Iowan Old Style","Source Serif 4","Noto Serif TC",serif;
  --sans: "Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
  --mono: ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;
  --shadow-1: 0 1px 2px rgba(0,0,0,.35);
  --shadow-2: 0 10px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.35);
}
:root[data-theme="light"]{
  --bg:#EFE8D8; --panel:#F8F3E6; --panel-2:#EAE1CB; --panel-3:#E0D5B8;
  --border:#D6C9A3; --border-2:#C3B387;
  --ink:#241C10; --ink-2:#6B5B3D; --ink-3:#93825E;
  --up:#A8432C; --down:#3D7048;
  --accent:#93701E; --accent-dim:#C4A24E;
  --tier-super:#93701E; --tier-strong:#3D7048; --tier-mid:#7A7260; --tier-weak:#9A5A24; --tier-superweak:#A8432C;
  --shadow-1: 0 1px 2px rgba(60,45,10,.1);
  --shadow-2: 0 10px 28px rgba(60,45,10,.16), 0 2px 6px rgba(60,45,10,.1);
}

*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;padding:0 0 100px;
  background-image:radial-gradient(ellipse at top left, rgba(255,255,255,.04), transparent 55%);
}
.tabular{font-family:var(--mono);font-variant-numeric:tabular-nums}

.topbar{display:flex;align-items:baseline;gap:16px;padding:20px 28px;border-bottom:1px solid var(--border)}
.topbar h1{font-family:var(--serif);font-size:1.32rem;font-weight:600;color:var(--ink);letter-spacing:.01em;margin:0}
.topbar .kicker{font-size:.6rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.topbar .sub{font-size:.72rem;color:var(--ink-3);margin-left:4px}
.topbar .updated{font-size:.72rem;color:var(--ink-3);margin-left:auto;font-family:var(--mono)}
.topbar .theme-btn{font-family:var(--mono);font-size:.66rem;background:var(--panel-2);border:1px solid var(--border);color:var(--ink-2);padding:5px 11px;border-radius:4px;cursor:pointer}

.regime-banner{margin:16px 28px 0;border-radius:6px;border:1px solid var(--border);overflow:hidden;transition:border-color .2s}
.regime-banner.mode-calm{border-left:3px solid var(--tier-strong)}
.regime-banner.mode-selloff{border-left:3px solid var(--tier-superweak)}
.regime-head{display:flex;align-items:center;gap:14px;padding:14px 18px;background:var(--panel)}
.regime-tier{font-family:var(--serif);font-size:1.05rem;font-weight:700}
.regime-tier.up{color:var(--up)}
.regime-tier.down{color:var(--down)}
.regime-tier.flat{color:var(--ink-2)}
.regime-meta{font-family:var(--mono);font-size:.72rem;color:var(--ink-3)}
.regime-concentration{font-size:.72rem;color:var(--ink-2);margin-left:auto;padding:3px 9px;border:1px solid var(--border);border-radius:4px;background:var(--panel-2)}
.regime-advice{padding:12px 18px 15px;font-size:.8rem;color:var(--ink-2);line-height:1.65;background:var(--panel-2);border-top:1px solid var(--border)}
.regime-advice b{color:var(--ink);font-weight:700}
.regime-advice .src{display:block;margin-top:5px;font-size:.66rem;color:var(--ink-3);font-family:var(--mono)}

.philosophy-note{margin:10px 28px 0;padding:10px 16px;font-size:.72rem;color:var(--ink-3);line-height:1.6;border-left:2px solid var(--border-2)}
.philosophy-note b{color:var(--ink-2)}

.legend{margin:16px 28px 0;padding:13px 18px;background:var(--panel);border:1px solid var(--border);border-radius:5px;display:flex;flex-wrap:wrap;gap:18px;align-items:center}
.legend .lg-title{font-size:.68rem;font-weight:700;color:var(--ink-2);letter-spacing:.04em}
.legend .lg-item{display:flex;align-items:center;gap:6px;font-size:.72rem;color:var(--ink-2);white-space:nowrap}
.legend .dot{width:8px;height:8px;border-radius:50%;flex:none}
.legend .lg-item b{color:var(--ink);font-weight:700}
.legend .lg-arrow{color:var(--ink-3)}

.section-head{display:flex;align-items:baseline;gap:12px;padding:30px 28px 6px}
.section-head .num{font-family:var(--serif);font-size:1.5rem;font-weight:600;color:var(--accent-dim);line-height:1}
.section-head h2{font-family:var(--serif);font-size:1.1rem;font-weight:600;color:var(--ink);margin:0}
.section-head .count{font-family:var(--mono);font-size:.7rem;color:var(--ink-3);margin-left:auto}
.section-rule{height:1px;background:linear-gradient(to right,var(--ink) 0%,var(--border) 45%,transparent 100%);margin:0 28px 4px}
.section-sub{padding:0 28px 16px;font-size:.78rem;color:var(--ink-2);max-width:680px}

.sector-strip{display:flex;gap:10px;overflow-x:auto;padding:2px 28px 4px}
.sector-pill{flex:0 0 auto;display:flex;flex-direction:column;gap:4px;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:11px 16px;cursor:pointer;transition:border-color .15s,background .15s;min-width:120px}
.sector-pill:hover{border-color:var(--border-2)}
.sector-pill.active{border-color:var(--accent);background:var(--panel-2);box-shadow:0 0 0 1px var(--accent) inset}
.sector-pill .sp-rank{font-family:var(--mono);font-size:.6rem;color:var(--ink-3);font-weight:700}
.sector-pill .sp-name{font-family:var(--serif);font-size:.94rem;font-weight:600;color:var(--ink)}
.sector-pill .sp-pct{font-family:var(--mono);font-size:.86rem;font-weight:700}
.sector-pill .sp-note{font-size:.62rem;color:var(--ink-3)}

.stock-table-wrap{margin:0 28px;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:var(--panel)}
.stock-table-wrap{overflow-x:auto}
.stock-table{width:100%;border-collapse:collapse;min-width:860px}
.stock-table thead th{text-align:left;font-size:.62rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);padding:10px 14px;border-bottom:1px solid var(--border);background:var(--panel-2);white-space:nowrap}
.stock-table thead th.num{text-align:right}
.stock-row{border-bottom:1px solid var(--border);cursor:pointer;transition:background .12s}
.stock-row:hover{background:var(--panel-2)}
.stock-row:last-child{border-bottom:none}
.stock-row td{padding:11px 14px;vertical-align:middle}
.sr-name{display:flex;flex-direction:column;gap:1px}
.sr-name .id{font-family:var(--mono);font-size:.66rem;color:var(--ink-3)}
.sr-name .nm{font-family:var(--serif);font-size:.94rem;font-weight:600;color:var(--ink)}
.sr-price{font-family:var(--mono);font-weight:700;font-size:.92rem;text-align:right}
.sr-pct{font-family:var(--mono);font-weight:700;font-size:.82rem;text-align:right;white-space:nowrap}
.sr-rank{font-family:var(--mono);font-size:.76rem;color:var(--ink-2);text-align:right;white-space:nowrap}
.sr-rank .bar-wrap{display:inline-block;width:44px;height:4px;background:var(--panel-3);border-radius:2px;margin-left:7px;vertical-align:middle;overflow:hidden}
.sr-rank .bar-fill{height:100%;background:var(--accent-dim);border-radius:2px}
.tier-chip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:.7rem;font-weight:700;padding:4px 10px;border-radius:4px;white-space:nowrap}
.tier-chip .dot{width:7px;height:7px;border-radius:50%;flex:none}
.tier-super{background:color-mix(in srgb, var(--tier-super) 15%, var(--panel));color:var(--tier-super)}
.tier-super .dot{background:var(--tier-super)}
.tier-strong{background:color-mix(in srgb, var(--tier-strong) 15%, var(--panel));color:var(--tier-strong)}
.tier-strong .dot{background:var(--tier-strong)}
.tier-mid{background:color-mix(in srgb, var(--tier-mid) 15%, var(--panel));color:var(--tier-mid)}
.tier-mid .dot{background:var(--tier-mid)}
.tier-weak{background:color-mix(in srgb, var(--tier-weak) 15%, var(--panel));color:var(--tier-weak)}
.tier-weak .dot{background:var(--tier-weak)}
.tier-superweak{background:color-mix(in srgb, var(--tier-superweak) 15%, var(--panel));color:var(--tier-superweak)}
.tier-superweak .dot{background:var(--tier-superweak)}
.sr-action{font-size:.78rem;color:var(--ink-2)}
.sr-chevron{color:var(--ink-3);font-size:.7rem;text-align:center;transition:transform .15s}
.stock-row.expanded .sr-chevron{transform:rotate(90deg);color:var(--accent)}

.detail-row{display:none}
.detail-row.open{display:table-row}
.detail-row td{padding:0;border-bottom:1px solid var(--border)}
.detail-inner{padding:16px 18px 18px 46px;background:var(--panel-2);display:grid;grid-template-columns:1fr 1fr 1fr;gap:22px}
.detail-block h4{margin:0 0 9px;font-size:.68rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3)}
.cond-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.cond-list li{display:flex;align-items:flex-start;gap:8px;font-size:.78rem;color:var(--ink-2);line-height:1.5}
.cond-icon{flex:none;width:15px;height:15px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.6rem;font-weight:800;margin-top:1px}
.cond-icon.met{background:color-mix(in srgb, var(--down) 18%, var(--panel));color:var(--down)}
.cond-icon.unmet{background:var(--panel-3);color:var(--ink-3)}
.cond-list li.met-text{color:var(--ink)}

.ma-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.ma-list li{display:flex;justify-content:space-between;align-items:baseline;font-size:.78rem;color:var(--ink-2)}
.ma-list .ma-label{font-family:var(--mono);font-size:.68rem;color:var(--ink-3)}
.ma-list .ma-val{font-family:var(--mono);font-weight:700;color:var(--ink)}
.ma-list li.price-row{padding-top:6px;margin-top:2px;border-top:1px solid var(--border)}
.ma-list li.price-row .ma-val{font-size:.9rem;color:var(--accent)}
.ma-note{margin-top:8px;font-size:.68rem;color:var(--ink-3);line-height:1.5}

.rs-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:9px}
.rs-list li{display:flex;flex-direction:column;gap:2px}
.rs-list .rs-label{font-size:.72rem;color:var(--ink-3)}
.rs-list .rs-val{font-family:var(--mono);font-weight:700;font-size:.9rem}
.rs-list .rs-val.pos{color:var(--up)}
.rs-list .rs-val.neg{color:var(--down)}

.selloff-section{display:none}
.selloff-section.show{display:block}
.resilience-table-wrap{margin:0 28px;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:var(--panel);overflow-x:auto}
.resilience-table{width:100%;border-collapse:collapse;min-width:640px}
.resilience-table thead th{text-align:left;font-size:.62rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);padding:10px 14px;border-bottom:1px solid var(--border);background:var(--panel-2);white-space:nowrap}
.resilience-table thead th.num{text-align:right}
.resilience-table tbody tr{border-bottom:1px solid var(--border)}
.resilience-table tbody tr:last-child{border-bottom:none}
.resilience-table td{padding:10px 14px;vertical-align:middle}
.res-verdict{font-size:.74rem;color:var(--tier-strong);font-weight:600}
.action-row{display:flex;flex-wrap:wrap;gap:10px;margin:0 28px;padding:12px 16px;background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--tier-superweak);border-radius:5px;font-size:.78rem;color:var(--ink-2);line-height:1.6}
.action-row b{color:var(--ink)}

.streak-strip{display:flex;gap:14px;overflow-x:auto;padding:2px 28px 6px}
.streak-card{flex:0 0 200px;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px 16px;position:relative;overflow:hidden}
.streak-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--tier-super)}
.streak-card .sc-name{font-family:var(--serif);font-weight:600;font-size:.96rem;color:var(--ink)}
.streak-card .sc-id{font-family:var(--mono);font-size:.62rem;color:var(--ink-3);margin-left:6px}
.streak-card .sc-streak{font-family:var(--mono);font-size:1.5rem;font-weight:800;color:var(--tier-super);margin-top:6px}
.streak-card .sc-streak span{font-size:.7rem;font-weight:600;color:var(--ink-3);margin-left:3px}
.streak-card .sc-vol{font-size:.66rem;color:var(--ink-3);margin-top:5px}
.streak-card .sc-vol b{color:var(--down)}
.sc-breakout{display:inline-block;font-family:var(--mono);font-size:.6rem;font-weight:700;padding:2px 7px;border-radius:3px;margin-top:8px}
.sc-breakout.confirmed{background:color-mix(in srgb, var(--tier-strong) 15%, var(--panel));color:var(--tier-strong)}
.sc-breakout.warn{background:color-mix(in srgb, var(--tier-superweak) 15%, var(--panel));color:var(--tier-superweak)}

footer{padding:30px 28px 0;font-size:.68rem;color:var(--ink-3);font-family:var(--mono)}

@media (max-width:900px){
  .detail-inner{grid-template-columns:1fr}
}
"""

_JS = """
function renderStocks(sector){
  const list = SECTORS[sector] || [];
  document.getElementById('stock-sec-title').textContent = sector + '族群 — 誰最強？能不能進？該不該出？';
  document.getElementById('stock-count').textContent = list.length + ' 檔';
  const tbody = document.getElementById('stock-tbody');
  tbody.innerHTML = '';
  list.forEach((s,i)=>{
    const pctColor = s.pct>=0 ? 'var(--up)' : 'var(--down)';
    const barPct = Math.round((1 - (s.rank-1)/s.total)*100);
    const tr = document.createElement('tr');
    tr.className = 'stock-row';
    tr.innerHTML = `
      <td><div class="sr-name"><span class="id tabular">${s.id}</span><span class="nm">${s.name}</span></div></td>
      <td class="sr-price tabular">${s.price.toFixed(1)}</td>
      <td class="sr-pct tabular" style="color:${pctColor}">${s.pct>=0?'+':''}${s.pct.toFixed(2)}%</td>
      <td class="sr-rank tabular">#${s.rank}/${s.total}<span class="bar-wrap"><span class="bar-fill" style="width:${barPct}%"></span></span></td>
      <td><span class="tier-chip tier-${s.tier}"><span class="dot"></span>${s.actionText}</span></td>
      <td class="sr-chevron">▸</td>
    `;
    const ma = s.ma || {};
    const rs = s.rs || {};
    const aboveMA = (v)=> s.price >= v;
    const detailTr = document.createElement('tr');
    detailTr.className = 'detail-row';
    detailTr.innerHTML = `<td colspan="6"><div class="detail-inner">
      <div class="detail-block"><h4>進場訊號</h4><ul class="cond-list">
        ${s.entry.map(([txt,met])=>`<li class="${met?'met-text':''}"><span class="cond-icon ${met?'met':'unmet'}">${met?'✓':'—'}</span>${txt}</li>`).join('')}
      </ul>
      <h4 style="margin-top:14px">出場三原則</h4><ul class="cond-list">
        ${s.exit.map(([txt,met])=>`<li class="${met?'met-text':''}"><span class="cond-icon ${met?'met':'unmet'}">${met?'✓':'—'}</span>${txt}</li>`).join('')}
      </ul></div>

      <div class="detail-block"><h4>均線數值（今日）</h4><ul class="ma-list">
        <li class="price-row"><span class="ma-label">收盤價</span><span class="ma-val tabular">${s.price.toFixed(1)}</span></li>
        <li><span class="ma-label">MA5</span><span class="ma-val tabular" style="color:${aboveMA(ma.ma5)?'var(--up)':'var(--down)'}">${ma.ma5?.toFixed(1)}</span></li>
        <li><span class="ma-label">MA10</span><span class="ma-val tabular" style="color:${aboveMA(ma.ma10)?'var(--up)':'var(--down)'}">${ma.ma10?.toFixed(1)}</span></li>
        <li><span class="ma-label">MA20</span><span class="ma-val tabular" style="color:${aboveMA(ma.ma20)?'var(--up)':'var(--down)'}">${ma.ma20?.toFixed(1)}</span></li>
        <li><span class="ma-label">MA60</span><span class="ma-val tabular" style="color:${aboveMA(ma.ma60)?'var(--up)':'var(--down)'}">${ma.ma60?.toFixed(1)}</span></li>
      </ul>
      <div class="ma-note">紅＝價在均線之上、綠＝價在均線之下（沿用漲跌色）。MA20 純參考，不參與多頭/空頭排列判斷。</div></div>

      <div class="detail-block"><h4>相對強弱（近5日）</h4><ul class="rs-list">
        <li><span class="rs-label">vs 族群平均</span><span class="rs-val ${rs.score>=0?'pos':'neg'} tabular">${rs.score>=0?'+':''}${rs.score?.toFixed(1)}pp</span></li>
        <li><span class="rs-label">族群內百分位</span><span class="rs-val tabular">${Math.round((rs.rank||0)*100)}%（1.0＝最強）</span></li>
        <li><span class="rs-label">vs 大盤等權</span><span class="rs-val ${rs.market>=0?'pos':'neg'} tabular">${rs.market>=0?'+':''}${rs.market?.toFixed(1)}pp</span></li>
      </ul></div>
    </div></td>`;
    tr.onclick = ()=>{
      const open = detailTr.classList.toggle('open');
      tr.classList.toggle('expanded', open);
      tr.querySelector('.sr-chevron').textContent = open ? '▾' : '▸';
    };
    tbody.appendChild(tr);
    tbody.appendChild(detailTr);
  });
}

function selectSector(el){
  document.querySelectorAll('.sector-pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  renderStocks(el.dataset.metaName);
}

function toggleTheme(){
  const root = document.documentElement;
  const cur = root.getAttribute('data-theme');
  root.setAttribute('data-theme', cur==='light' ? 'dark' : 'light');
}

renderStocks(DEFAULT_SECTOR);
"""


def _sector_pills_html(pills: list) -> str:
    if not pills:
        return ""
    items = []
    for p in pills:
        pct = p["avg_change_pct"]
        color = "var(--up)" if pct >= 0 else ("var(--ink-2)" if pct == 0 else "var(--down)")
        active = " active" if p["rank"] == 1 else ""
        items.append(f"""
  <div class="sector-pill{active}" data-meta-name="{_esc(p['meta_name'])}" onclick="selectSector(this)">
    <span class="sp-rank tabular">#{p['rank']}</span>
    <span class="sp-name">{_esc(p['meta_name'])}</span>
    <span class="sp-pct tabular" style="color:{color}">{pct:+.2f}%</span>
    <span class="sp-note">{p['stock_count']}檔</span>
  </div>""")
    return "".join(items)


def _streak_cards_html(cards: list) -> str:
    if not cards:
        return '<div class="section-sub">今日無連續鎖漲停個股。</div>'
    items = []
    for c in cards:
        vol_text = "今日剛鎖" if c["volume_declining_streak"] is None else (
            f"量縮鎖死" if c["volume_declining_streak"] else "出量中"
        )
        if c["breakout_volume_confirmed"] is None:
            breakout_html = ""
        elif c["breakout_volume_confirmed"]:
            breakout_html = '<span class="sc-breakout confirmed">起漲出量 ✓</span>'
        else:
            breakout_html = '<span class="sc-breakout warn">量沒跟上 ⚠ 疑似假突破</span>'
        items.append(f"""
  <div class="streak-card">
    <span class="sc-name">{_esc(c['stock_name'])}</span><span class="sc-id">{_esc(c['stock_id'])}</span>
    <div class="sc-streak">{c['limit_up_streak']}<span>連板</span></div>
    <div class="sc-vol">{vol_text}</div>
    {breakout_html}
  </div>""")
    return f'<div class="streak-strip">{"".join(items)}</div>'


def _resilience_section_html(candidates: dict) -> str:
    resilient = candidates.get("resilient", [])
    limit_down = candidates.get("limit_down", [])
    rows = []
    for r in resilient:
        rows.append(f"""
    <tr><td><div class="sr-name"><span class="id tabular">{_esc(r['stock_id'])}</span><span class="nm">{_esc(r['stock_name'])}</span></div></td>
        <td class="sr-pct tabular" style="color:{'var(--up)' if r['change_pct']>=0 else 'var(--down)'}">{r['change_pct']:+.1f}%</td>
        <td class="sr-pct tabular" style="color:var(--tier-strong)">{r['rs_market_score']:+.2f}pp</td>
        <td class="res-verdict">弱中透強·可換入</td></tr>""")
    for r in limit_down:
        rows.append(f"""
    <tr><td><div class="sr-name"><span class="id tabular">{_esc(r['stock_id'])}</span><span class="nm">{_esc(r['stock_name'])}</span></div></td>
        <td class="sr-pct tabular" style="color:var(--down)">{r['change_pct']:+.1f}%</td>
        <td class="sr-pct tabular" style="color:var(--tier-superweak)">{(r.get('rs_market_score') or 0):+.2f}pp</td>
        <td class="res-verdict" style="color:var(--tier-superweak)">跌停鎖死·立刻砍</td></tr>""")

    return f"""
<div class="selloff-section show" id="selloff-section">
  <div class="section-head"><span class="num">⚠</span><h2>大盤急殺，換股到哪？</h2><span class="count">僅大盤小跌/大跌時顯示</span></div>
  <div class="section-rule"></div>
  <div class="section-sub">相對大盤跌得更少＝真強勢。找抗跌的換進去，鎖跌停的立刻砍出——不是清倉不動，是資金重新集中。</div>
  <div class="resilience-table-wrap">
  <table class="resilience-table">
  <thead><tr><th>股票</th><th class="num">今日</th><th class="num">vs 大盤</th><th>判斷</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
  </table>
  </div>
  <div class="action-row"><b>換股邏輯：</b>賣出「跌停鎖死·立刻砍」的持股，資金集中換進「弱中透強·可換入」——同天執行，不分批猶豫。<span style="color:var(--ink-3);font-size:.72rem">（依據：筆記二十三換股實戰、三十三弱中透強接刀法）</span></div>
</div>"""


def generate(
    trade_date: date,
    market_regime: dict,
    momentum_results: list,
    bullish_new_high_results: list,
    limit_up_results: list,
    meta_perf: list,
    output_path: str = "docs/逆轟策略.html",
) -> bool:
    """回傳是否實際寫入了 output_path；momentum_results 為空時不寫檔、回傳 False，
    比照 chips_generator.py::generate() 既有慣例，讓呼叫端能區分「真的產生成功」跟「靜默跳過」。"""
    if not momentum_results:
        return False

    bullish_new_high_ids = {r["stock_id"] for r in bullish_new_high_results}
    banner = regime_banner_content(market_regime)
    pills = build_sector_pills(meta_perf)
    stock_table = build_stock_table(momentum_results, bullish_new_high_ids)
    streak_cards = build_streak_cards(limit_up_results)

    default_sector = pills[0]["meta_name"] if pills else ""

    # JS 消費的資料結構跟 mockup v5 的 SECTORS 物件同形狀（id/name/price/pct/rank/total/tier/actionText/entry/exit/ma/rs）
    sectors_js_data = {}
    for sector, stocks in stock_table.items():
        sectors_js_data[sector] = [
            {
                "id": s["stock_id"], "name": s["stock_name"], "price": s["close"],
                "pct": s["change_pct"], "rank": s["rank"], "total": s["total"],
                "tier": {"超強": "super", "強": "strong", "整理": "mid",
                         "弱": "weak", "超弱": "superweak"}.get(s["tier"], "mid"),
                "actionText": s["action_text"],
                "entry": s["entry"], "exit": s["exit"],
                "ma": s["ma"], "rs": s["rs"],
            }
            for s in stocks
        ]

    resilience = resilience_candidates(momentum_results) if banner["mode"] == "selloff" else None

    date_str = trade_date.strftime("%Y-%m-%d")
    total_stock_count = sum(len(v) for v in stock_table.values())
    default_sector_count = len(stock_table.get(default_sector, []))

    resilience_html = _resilience_section_html(resilience) if resilience is not None else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>逆轟策略 {date_str}</title>
  <style>{_CSS}</style>
</head>
<body>

<div class="topbar">
  <h1>逆轟策略</h1>
  <span class="kicker">MOMENTUM</span>
  <span class="sub">動能派選股決策</span>
  <span class="updated tabular">資料日 {date_str}</span>
  <button class="theme-btn" onclick="toggleTheme()">切換主題</button>
</div>

<div class="regime-banner mode-{banner['mode']}" id="regime-banner">
  <div class="regime-head">
    <span class="regime-tier {banner['tier_class']}" id="regime-tier-text">{_esc(banner['tier_text'])}</span>
    <span class="regime-meta tabular" id="regime-meta-text">{_esc(banner['meta_text'])}</span>
    <span class="regime-concentration" id="regime-concentration-text">{_esc(banner['concentration_text'])}</span>
  </div>
  <div class="regime-advice" id="regime-advice-text">
    {banner['advice_html']}
  </div>
</div>

<div class="philosophy-note">
  <b>本頁沒有停利/停損百分比欄位</b>——動能派不用固定%，出場三原則本身就是停損機制（跌破五日線+五日線下彎+重挫長黑，三者同時成立才出，不是價格跌到某%才砍）。倉位紀律取代停利：分批進場、往上加碼、絕不往下攤平，賺的時候讓它繼續跑，直到出場三原則觸發為止。
</div>

<div class="legend">
  <span class="lg-title">五級判斷＝動作，不是狀態標籤</span>
  <span class="lg-item"><span class="dot" style="background:var(--tier-super)"></span><b>超強</b><span class="lg-arrow">→</span>隨時加碼</span>
  <span class="lg-item"><span class="dot" style="background:var(--tier-strong)"></span><b>強</b><span class="lg-arrow">→</span>續抱</span>
  <span class="lg-item"><span class="dot" style="background:var(--tier-mid)"></span><b>整理</b><span class="lg-arrow">→</span>反彈可出</span>
  <span class="lg-item"><span class="dot" style="background:var(--tier-weak)"></span><b>弱</b><span class="lg-arrow">→</span>直接出清</span>
  <span class="lg-item"><span class="dot" style="background:var(--tier-superweak)"></span><b>超弱</b><span class="lg-arrow">→</span>跌停才放空*</span>
</div>
<div class="philosophy-note" style="margin-top:6px">
  *放空範圍比空頭排列窄：筆記三十四明講「不空漲停的股票，只空跌停的股票」——超弱不等於自動放空，頁面只在該股<b>當日實際跌停</b>時才會把「反手放空」列進動作文字，其餘超弱僅顯示「直接出清、觀望」。
</div>

<div class="section-head"><span class="num">①</span><h2>今天資金在哪？</h2><span class="count">點選族群篩選下方個股</span></div>
<div class="section-rule"></div>
<div class="section-sub">族群強度排名——先決定看哪個籃子，不分散，買最強的那一籃。</div>
<div class="sector-strip">{_sector_pills_html(pills)}</div>

{resilience_html}

<div class="section-head"><span class="num">②③④</span><h2 id="stock-sec-title">{_esc(default_sector)}族群 — 誰最強？能不能進？該不該出？</h2><span class="count tabular" id="stock-count">{default_sector_count} 檔</span></div>
<div class="section-rule"></div>
<div class="section-sub">同族群裡只選最強那一檔——次強買不到才考慮二軍。點列展開看命中哪幾條進出場條件。</div>

<div class="stock-table-wrap">
<table class="stock-table">
<thead>
<tr>
  <th>股票</th>
  <th class="num">現價</th>
  <th class="num">漲跌</th>
  <th class="num">族群內排名</th>
  <th>判斷 → 動作</th>
  <th></th>
</tr>
</thead>
<tbody id="stock-tbody">
</tbody>
</table>
</div>

<div class="section-head"><span class="num">⑤</span><h2>有沒有最強型態？</h2><span class="count">連續鎖漲停榜</span></div>
<div class="section-rule"></div>
<div class="section-sub">量縮鎖死＝最強型態，隔日大概率延續。不限於上面選中的族群，全市場掃描。<br>
起漲那天有沒有真的出量，決定這是真突破還是假突破——兩者是不同階段的量能訊號，分開標示。</div>
{_streak_cards_html(streak_cards)}

<footer>逆轟策略頁 · 資料來源：screener/signals.py 動能派掃描 · 共 {total_stock_count} 檔個股（{len(pills)} 個族群）</footer>

<script>
const SECTORS = {json.dumps(sectors_js_data, ensure_ascii=False)};
const DEFAULT_SECTOR = {json.dumps(default_sector, ensure_ascii=False)};
{_JS}
</script>
</body>
</html>
"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return True
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（全部，含 Task 2/3 的測試）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator generate() 主函式，CSS/JS沿用mockup v5定案版"
```

---

### Task 5: 掛進 `main.py::run()` 每日流程

**Files:**
- Modify: `main.py`（`run()` 函式內，`generate_chips_html(...)` 呼叫之後，約第857-861行之後）

**Interfaces:**
- Consumes: Task 1-4 的 `export.momentum_generator.generate`；既有 `screener.signals.scan_momentum_health`/`scan_bullish_alignment_new_high`/`scan_consecutive_limit_up`；`run()` 函式內已經算好的 `market_regime`（第668-692行）、`meta_perf`（第653行）。
- Produces: 每日執行 `python main.py` 時，`docs/逆轟策略.html` 跟著 `index.html`/`chips.html` 一起重新產生。

這個 Task 是純 CLI/pipeline 佈線，沒有對應的自動化測試（跟現有 `generate_patterns_html`/`generate_chips_html` 呼叫點一致，`tests/test_main.py` 本來就不覆蓋 `run()` 內部這層 pipeline 串接）。用語法檢查代替「執行確認通過」。

- [ ] **Step 1: 讀取 main.py 現有呼叫點確認行號未變**

Run: `grep -n "chips_html_written = generate_chips_html" main.py`
Expected: 確認 `generate_chips_html(...)` 呼叫仍在 `run()` 函式內、行號跟 spec 描述的區塊接近（如有偏移，以實際讀到的行號為準，不要假設行號沒變過）。

- [ ] **Step 2: 在 `chips_html_written` 區塊之後加入動能頁生成**

在 `main.py` 找到：

```python
        chips_html_written = generate_chips_html(
            trade_date, meta_chips, stock_chips,
            inst_scan=inst_results, margin_divergence=margin_div, cum_data=cum_data,
            meta_signals=meta_signals, shareholder_data=sh_rows, insider_data=insider_rows,
        )
        if chips_html_written:
            logger.info("HTML generated → docs/chips.html")
        else:
            logger.warning("docs/chips.html 沒有更新（meta_chips/stock_chips 皆為空，可能是資料源當天抓取失敗）")
```

在這段之後（`else:` 區塊結束後）加入：

```python
        try:
            from screener.signals import scan_momentum_health, scan_bullish_alignment_new_high, scan_consecutive_limit_up
            from export.momentum_generator import generate as generate_momentum_html

            momentum_results = scan_momentum_health(trade_date.isoformat())
            bullish_new_high_results = scan_bullish_alignment_new_high(trade_date.isoformat())
            limit_up_results = scan_consecutive_limit_up(trade_date.isoformat())

            momentum_html_written = generate_momentum_html(
                trade_date,
                market_regime or {},
                momentum_results,
                bullish_new_high_results,
                limit_up_results,
                meta_perf,
            )
            if momentum_html_written:
                logger.info("HTML generated → docs/逆轟策略.html")
            else:
                logger.warning("docs/逆轟策略.html 沒有更新（momentum_results 為空，可能是歷史資料不足65個交易日）")
        except Exception as exc:
            logger.warning("逆轟策略頁生成失敗，本次不影響其他頁面: %s", exc)
```

**設計說明**：整段包在獨立 `try/except Exception` 裡（比照緊接在後的 `scan_and_track`/`generate_patterns_html` 既有寫法，見第863-869行），任何失敗只記警告、不讓整個每日流程中斷，`index.html`/`chips.html` 已經在這之前產生完成不受影響。`market_regime` 用 `or {}` 防護——`market_regime` 在 TAIEX 抓取失敗時會是 `None`（第668行 `market_regime = None` 初始化，第689-692行的 `except` 只 log warning 不賦值），`regime_banner_content()` 內部用 `.get()` 讀取欄位、`market_regime={}` 時全部欄位落空值不會 crash，但這裡明確補一層 `or {}` 避免把 `None` 直接傳進去。

- [ ] **Step 3: 語法檢查**

Run: `python -m py_compile main.py`
Expected: 無輸出、exit code 0

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(main): 掛進逆轟策略頁每日生成流程"
```

---

## Self-Review（對照 spec 逐項檢查）

- **§3 頁面結構**：大盤橫幅(Task2+4)、停利停損提示(Task4靜態文字)、①族群pill(Task3+4)、換股警戒(Task2+3+4，僅selloff顯示)、②③④主表(Task2+3+4)、⑤最強型態(Task1+3+4)——全部對應到 Task，無遺漏。
- **§7.3/§7.4 五級動作映射+放空收斂**：`tier_action_text()` 精確對照表格逐一寫死映射，超弱另外檢查跌停常數，Task2 已覆蓋且有測試。
- **§7.5 展開面板三欄**：進場兩燈號＋出場三燈號（Task2 `entry_signals`/`exit_signals`）、均線數值（Task3 `build_stock_table` 的 `ma` 欄位）、相對強弱（`rs` 欄位）——三欄都有資料來源，JS 渲染沿用 mockup 不變。
- **§8.1 B5 起漲量能確認**：Task1 完整實作，含 None/True/False 三態測試。
- **§11.3 跌停常數**：Task2 在 `momentum_generator.py` 內定義 `_LIMIT_DOWN_PCT`，不跨模組 import 私有常數，理由已在 Task2 說明段落記錄。
- **§11.1 修正**：計畫開頭 Global Constraints 已明確記錄「scan_momentum_health() 不需要修改」這個 brainstorming 階段判斷有誤的地方，避免後續工程師照著舊 spec 文字去改一個其實不用改的函式。
- **§9 Out of scope**：Task 清單中沒有出現回測驗證、族群連續天數、盤中戰術、持股清單相關程式碼，確認沒有範圍外溢。

## 寫 Plan 過程中發現並修正的兩個問題（記錄，不是 spec 缺陷，是把 spec 轉成實際程式碼時才浮現的細節）

1. **`_JS` 留了一個沒被呼叫到的死函式 `tierLabel()`**——伺服端 `tier_action_text()` 已經算好完整動作文字直接透過 JSON 傳給前端（`actionText` 欄位），JS 端不需要再自己從 `tier` 反推文字，`tierLabel()` 純粹是照抄 mockup 時沒清乾淨的殘留，已從 Task4 的 `_JS` 常數移除。
2. **`_sector_pills_html()` 原本把族群名稱直接內插進 `onclick="selectSector(this,'{name}')"` 的 JS 字串常值**——`_esc()` 只做 HTML escape，不是 JS 字串 escape，名稱若含單引號會弄壞產生的 JS（雖然 `meta_name` 目前來自內部固定的 `META_SECTORS` 分類、不是外部可控輸入，實際被利用的風險低，但這是不精確、不該照抄的寫法）。已改成 `data-meta-name` 屬性 + `el.dataset.metaName` 讀取，`onclick` 只傳 `this`——這是 `export/html_generator.py`（`_meta_card`/`_sector_mini_card`）已經在用的既有安全慣例（用 `data-*` 屬性存實際文字、onclick 只傳合成 id 或 DOM 元素本身），這裡照抄既有模式，不是新發明一套。Task4 的 `_sector_pills_html()`/`_JS` 已同步改好。

## No Placeholder 掃描

全部 Task 的程式碼區塊都是可以直接貼上執行的完整程式碼（no `TODO`/`...`(除了 CSS 複製來源說明段落用省略號指示「這是複製區間」，程式碼本身完整貼出，不是可執行程式碼裡的省略號)），測試斷言皆為具體數值比對，無空泛「add error handling」字樣。

## Type Consistency 掃描

- `entry_signals`/`exit_signals` 回傳的 `list[tuple[str, bool]]` 形狀，Task2 定義、Task3 `build_stock_table` 直接呼叫、Task4 JS `s.entry`/`s.exit` 消費，三處欄位形狀一致（JSON 序列化後 tuple 變成 2-element array，JS 用 `[txt, met]` 解構，跟 Python tuple 序列化行為一致）。
- `resilience_candidates()` 回傳 `{"resilient":[...], "limit_down":[...]}`，Task4 `_resilience_section_html()` 讀取同樣的 key 名稱，一致。
- `build_sector_pills`/`build_stock_table`/`build_streak_cards` 的回傳欄位名稱（`meta_name`/`rank`/`stock_count`；`stock_id`/`rank`/`total`/`action_text`/`entry`/`exit`/`ma`/`rs`；`stock_id`/`limit_up_streak`/`volume_declining_streak`/`breakout_volume_confirmed`）在 Task4 `generate()` 內取用時逐一核對過，命名一致無漂移。
