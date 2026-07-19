# 逆轟策略 v2 Plan 3/3（generator + UI 整合）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `calc_meta_observation_scores()` 接進 `index.html` 族群卡片排序，並新增獨立頁面
`docs/momentum.html`（`export/momentum_generator.py`），呈現 v2 spec 的四層決策模型（市場操作
許可 → 主流族群優先序 → 個股技術狀態 → 最終決策標籤），全程使用非命令式文案。這是 v2 spec 三個
Plan 的最後一個：Plan 1（資料層，`screener/signals.py`）與 Plan 2（觀察分計算，
`processors/observation_scores.py`）皆已完成並 commit。

**Architecture:** 新增 `export/momentum_generator.py`（比照 `chips_generator.py`/`patterns_generator.py`
自成一檔慣例），純函式構成的業務邏輯層（市場許可判定、族群狀態分類、最終標籤決策、急殺風險區、
連續近漲停卡片）+ 一個 `generate()` 組裝成 HTML。所有互動用原生 `<details>/<summary>` 展開列與
錨點跳轉，不需要客戶端 JS 渲染資料（跟舊版 v1 mockup 的「JSON 序列化嵌入 + JS render」不同，改成
跟 `chips_generator.py`/`patterns_generator.py` 一致的「Python 直接產生完整 HTML 字串」）。
`export/html_generator.py` 新增一個可選參數，把既有「依 `avg_change_pct` 排序族群卡片」換成優先
使用 `calc_meta_observation_scores()` 的 `observation_score`（缺值時完全向後相容，退回原本排序）。
最後掛進 `main.py::run()` 既有每日流程，重用已經算好的 `market_regime`/`universe_df`，只新增呼叫
三個 v2 掃描函式與 `calc_meta_observation_scores()` 各一次。

**Tech Stack:** Python、pandas（既有依賴，無新套件）。不使用 Jinja2／前端框架，維持專案既有「純
Python f-string 產生 HTML」慣例。

---

## Global Constraints

- 對照 spec：`docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md`（下稱「spec」）。
  這份 spec 明文取代 `2026-07-14-momentum-strategy-page-design.md` 與
  `2026-07-15-momentum-strategy-page-visual-design.md`。
- **⚠️ 舊 plan 已作廢，不要參考其程式碼**：`docs/superpowers/plans/2026-07-16-momentum-strategy-page.md`
  是 v2 spec 定案**前**寫的，裡面的 `tier_action_text()`／`regime_banner_content()`／
  `resilience_candidates()` 全部使用 v2 spec §4.2 明文禁止的命令式文案（「隨時加碼」「直接出清」
  「反手放空」）且 `resilience_candidates()` 誤用 5 日 `rs_market_score` 而非 spec §3.1 要求的單日
  `daily_excess_pct`。那份 plan 保留作為歷史紀錄，**這次 Plan 3 是全新設計，函式名稱與簽章跟舊 plan
  完全不同，不要混用**。
- **依賴確認**（已完成，可直接使用，不需要重新實作或驗證）：
  - `screener/signals.py::scan_momentum_health()` 回傳欄位含 `below_ma5`/`ma5_slope_down`/
    `big_black_proxy`/`ma5_rising`/`ma10_rising`/`entry_confirmed`/`exit_3_rule_triggered`/
    `daily_excess_pct`/`rs_sample_count`/`rs_rank_pct`/`rs_market_score`/`strength_tier`。
  - `screener/signals.py::scan_bullish_alignment_new_high()` 回傳欄位含 `volume_ratio_20d`/
    `volume_confirmed`。
  - `screener/signals.py::scan_consecutive_limit_up()` 回傳欄位含 `limit_up_streak`/
    `volume_declining_streak`/`breakout_volume_confirmed`。
  - `processors/observation_scores.py::calc_meta_observation_scores(universe_df, db_path)` 回傳
    `{meta_name: {observation_score, score_coverage, rs_raw, breadth_raw, continuation_raw,
    volume_raw, chips_raw, partial_coverage}}`。**`universe_df` 必須含 `exchange` 欄位**，否則
    `_calc_chips_factor()` 內部 `KeyError` 會炸掉整支函式（見 `debug-tasks.md` 2026-07-18 條目的
    Plan 3 提醒）。
  - `processors/performance.py::classify_market_regime(taiex_change_pct, breadth_ratio, divergence,
    concentration_threshold=2.0)` 回傳 `{tier, is_concentrated, concentration_direction}`，
    `tier ∈ {大漲,小漲,持平,小跌,大跌}`。
- **草案門檻聲明**：本計畫新增的 `classify_sector_state()` 五級分類門檻（`_SECTOR_STATE_SCORE_STRONG`
  等常數）是 writing-plans 階段新增的草案切點，spec §2.2 只有質化描述「協助區分主升/轉強/急彈/等待
  確認/轉弱」沒有給精確數字。這些常數要在程式碼與頁面文案標記「草案，待回測」，不能包裝成 spec
  明文規定的數字，跟 spec §3.5b `unlock_stage` 2/3 天分界線同一類「新增草案，非 spec 原文」處理方式。
- **不做**：spec §3.5b `scan_limit_up_unlocked()`（漲停打開階段性解讀，spec 本文已明講「不阻擋 v2
  其餘部分先落地，可以晚一點再做」）、§2.4.1 紫圈／橘圈視覺徽章（spec 本文已明講「writing-plans
  階段可自行決定是否採用，不採用也不影響功能完整性」）、任何回測驗證（spec §5 獨立任務）。
- **禁用文案**（spec §4.2）：`export/momentum_generator.py::BANNED_PHRASES` 定義
  `("隨時加碼", "一定續抱", "直接出清", "立刻砍", "可換入", "反手放空")`，Task 5 的 `generate()`
  測試必須驗證輸出 HTML 不含任何一個字樣。
- 每個 Task 完成後跑對應測試檔確認沒有破壞既有測試（照專案慣例，最終驗證留給 Debugger）。

---

### Task 1：`export/html_generator.py` 族群卡片排序改用 `observation_score`（向後相容）

**Files:**
- Modify: `export/html_generator.py`（`generate()` 簽章 + 第 1049-1050 行排序邏輯）
- Test: `tests/test_html_generator.py`

**Interfaces:**
- `generate()` 新增可選參數 `observation_scores: dict = None`。有提供時依
  `observation_scores[meta_name]["observation_score"]` 降冪排序族群卡片（`None` 視為 `-1.0`，
  排最後，不 crash、不誤排最前）；沒提供（`None`／缺該族群 key）時完全維持原本
  `avg_change_pct` 排序，既有呼叫端與既有測試不需要修改。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_html_generator.py` 加入（放在檔案任何既有 `test_generate_*` 函式之後即可）：

```python
def test_generate_orders_meta_cards_by_observation_score_when_provided(tmp_path):
    """v2 spec §2.2/§6：首頁與逆轟頁共用 calc_meta_observation_scores() 決定族群展開順序。
    族群B漲幅較低但觀察分較高時，應該排在族群A前面（不是照avg_change_pct）。"""
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股A", "meta_sector": "族群A", "sub_sector": "族群A"},
        {"stock_id": "2000", "stock_name": "測試股B", "meta_sector": "族群B", "sub_sector": "族群B"},
    ])
    meta_perf = [
        {"meta_name": "族群A", "sub_names": ["族群A"], "avg_change_pct": 5.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["1000"]},
        {"meta_name": "族群B", "sub_names": ["族群B"], "avg_change_pct": 1.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["2000"]},
    ]
    observation_scores = {
        "族群A": {"observation_score": 40.0, "score_coverage": 1.0},
        "族群B": {"observation_score": 85.0, "score_coverage": 1.0},
    }

    generate(
        trade_date=date(2026, 7, 19), perf_df=pd.DataFrame(), meta_perf=meta_perf,
        universe_df=universe_df, observation_scores=observation_scores,
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    pos_a = html.index('data-meta-name="族群A"')
    pos_b = html.index('data-meta-name="族群B"')
    assert pos_b < pos_a


def test_generate_falls_back_to_avg_change_pct_when_observation_scores_missing(tmp_path):
    """observation_scores 未提供時維持既有 avg_change_pct 排序（向後相容，既有呼叫端不用改）。"""
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股A", "meta_sector": "族群A", "sub_sector": "族群A"},
        {"stock_id": "2000", "stock_name": "測試股B", "meta_sector": "族群B", "sub_sector": "族群B"},
    ])
    meta_perf = [
        {"meta_name": "族群A", "sub_names": ["族群A"], "avg_change_pct": 5.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["1000"]},
        {"meta_name": "族群B", "sub_names": ["族群B"], "avg_change_pct": 1.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["2000"]},
    ]

    generate(
        trade_date=date(2026, 7, 19), perf_df=pd.DataFrame(), meta_perf=meta_perf,
        universe_df=universe_df, output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    pos_a = html.index('data-meta-name="族群A"')
    pos_b = html.index('data-meta-name="族群B"')
    assert pos_a < pos_b  # avg_change_pct: A(5.0) > B(1.0)


def test_generate_treats_none_observation_score_as_lowest(tmp_path):
    """該族群 observation_score=None（5因子全不可用）時排最後，不能排最前或crash，
    即使該族群 avg_change_pct 數值比較高。"""
    output_path = tmp_path / "index.html"
    universe_df = pd.DataFrame([
        {"stock_id": "1000", "stock_name": "測試股A", "meta_sector": "族群A", "sub_sector": "族群A"},
        {"stock_id": "2000", "stock_name": "測試股B", "meta_sector": "族群B", "sub_sector": "族群B"},
    ])
    meta_perf = [
        {"meta_name": "族群A", "sub_names": ["族群A"], "avg_change_pct": 1.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["1000"]},
        {"meta_name": "族群B", "sub_names": ["族群B"], "avg_change_pct": 5.0,
         "up_count": 1, "down_count": 0, "flat_count": 0, "stock_ids": ["2000"]},
    ]
    observation_scores = {
        "族群A": {"observation_score": 60.0, "score_coverage": 1.0},
        "族群B": {"observation_score": None, "score_coverage": 0.0},
    }

    generate(
        trade_date=date(2026, 7, 19), perf_df=pd.DataFrame(), meta_perf=meta_perf,
        universe_df=universe_df, observation_scores=observation_scores,
        output_path=str(output_path),
    )
    html = output_path.read_text(encoding="utf-8")

    pos_a = html.index('data-meta-name="族群A"')
    pos_b = html.index('data-meta-name="族群B"')
    assert pos_a < pos_b
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_html_generator.py -k observation_score -q`
Expected: FAIL（`TypeError: generate() got an unexpected keyword argument 'observation_scores'`）

- [ ] **Step 3: 實作**

在 `export/html_generator.py` 的 `generate()` 簽章（約第 967-983 行）新增參數，加在
`market_regime: dict = None,` 之後：

```python
def generate(
    trade_date: date,
    perf_df: pd.DataFrame,
    sectors_df: pd.DataFrame = None,
    prices_df: pd.DataFrame = None,
    chips_df: pd.DataFrame = None,
    meta_perf: list = None,
    universe_df: pd.DataFrame = None,
    cum_data: list = None,
    meta_signals: dict = None,
    meta_chips: dict = None,
    stock_sparklines: dict = None,
    vol_turnover: list = None,
    rolling_returns: dict = None,
    market_regime: dict = None,
    observation_scores: dict = None,
    output_path: str = "docs/index.html",
) -> None:
```

找到第 1049-1050 行：

```python
    if meta_perf:
        meta_sorted = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
```

改成：

```python
    if meta_perf:
        if observation_scores:
            def _meta_sort_key(r):
                score = observation_scores.get(r["meta_name"], {}).get("observation_score")
                return score if score is not None else -1.0
            meta_sorted = sorted(meta_perf, key=_meta_sort_key, reverse=True)
        else:
            meta_sorted = sorted(meta_perf, key=lambda r: r["avg_change_pct"], reverse=True)
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_html_generator.py -q`
Expected: PASS（含全部既有測試 + 3 個新增）

- [ ] **Step 5: Commit**

```bash
git add export/html_generator.py tests/test_html_generator.py
git commit -m "feat(html_generator): 族群卡片排序改用observation_score(向後相容，缺值退回avg_change_pct)"
```

---

### Task 2：`export/momentum_generator.py` 業務邏輯層 I——RS樣本信心／市場操作許可／族群狀態／主流族群優先序

**Files:**
- Create: `export/momentum_generator.py`
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- `BANNED_PHRASES: tuple`（spec §4.2 禁用字樣，供 Task 5 頁面回歸測試使用）
- `rs_sample_confidence(rs_sample_count: int) -> str`：`"A"`(≥10) / `"B"`(5~9) / `"C"`(<5)（spec §3.2）
- `market_permission(market_regime: dict, index_date: str = None, price_date: str = None) -> dict`：
  回傳 `{permission, tier_text, divergence_text, advice_text}`，`permission ∈
  {"normal","selective","defensive","unknown"}`（spec §2.1）
- `classify_sector_state(observation_data: dict) -> str`：`{"主升","轉強","急彈","轉弱","等待確認"}`
  五選一（spec §2.2 prose，門檻為本計畫新增草案）
- `build_sector_priority(observation_scores: dict, top_n: int = 5) -> list`：Top N 族群卡片資料
  （spec §2.2/§4）

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_momentum_generator.py`：

```python
from export.momentum_generator import (
    rs_sample_confidence, market_permission, classify_sector_state, build_sector_priority,
)


def test_rs_sample_confidence_tiers():
    assert rs_sample_confidence(10) == "A"
    assert rs_sample_confidence(15) == "A"
    assert rs_sample_confidence(9) == "B"
    assert rs_sample_confidence(5) == "B"
    assert rs_sample_confidence(4) == "C"
    assert rs_sample_confidence(0) == "C"


def test_market_permission_normal_for_up_tiers():
    regime = {"tier": "大漲", "taiex_change_pct": 2.1, "breadth_ratio": 0.72, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "normal"
    assert result["tier_text"] == "大漲"
    assert result["divergence_text"] == ""


def test_market_permission_defensive_for_down_tiers():
    regime = {"tier": "大跌", "taiex_change_pct": -2.3, "breadth_ratio": 0.22, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "defensive"
    assert "反手放空" not in result["advice_text"]
    assert "立刻砍" not in result["advice_text"]


def test_market_permission_selective_for_flat_tier_no_divergence():
    regime = {"tier": "持平", "taiex_change_pct": 0.1, "breadth_ratio": 0.48, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "selective"
    assert result["divergence_text"] == ""


def test_market_permission_shows_divergence_text_when_index_directional_but_flat_tier():
    """指數有方向(+1.8%)但廣度不足(42%)導致 classify_market_regime 降級成「持平」時，
    必須額外顯示背離原因，不能簡化成一般持平（spec §2.1）。"""
    regime = {"tier": "持平", "taiex_change_pct": 1.8, "breadth_ratio": 0.42, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert result["permission"] == "selective"
    assert "上漲" in result["divergence_text"]
    assert "42%" in result["divergence_text"]


def test_market_permission_includes_concentration_direction_when_present():
    regime = {"tier": "小漲", "taiex_change_pct": 0.5, "breadth_ratio": 0.55, "concentration_direction": "權值股撐盤"}
    result = market_permission(regime, index_date="2026-07-19", price_date="2026-07-19")
    assert "權值股撐盤" in result["divergence_text"]


def test_market_permission_unknown_when_dates_mismatch():
    """指數資料日期與個股行情日期不同時，降級unknown，不輸出市場操作文案（spec §2.1）。"""
    regime = {"tier": "大漲", "taiex_change_pct": 2.0, "breadth_ratio": 0.7, "concentration_direction": None}
    result = market_permission(regime, index_date="2026-07-18", price_date="2026-07-19")
    assert result["permission"] == "unknown"
    assert result["advice_text"] == ""


def test_market_permission_skips_date_check_when_dates_not_provided():
    """呼叫端沒傳日期時（例如舊呼叫路徑），不做日期檢查，直接照 tier 判斷（向後相容）。"""
    regime = {"tier": "大漲", "taiex_change_pct": 2.0, "breadth_ratio": 0.7, "concentration_direction": None}
    result = market_permission(regime)
    assert result["permission"] == "normal"


def test_classify_sector_state_zhusheng_when_high_score_and_broad():
    data = {"observation_score": 80.0, "breadth_raw": 0.7, "continuation_raw": 4, "rs_raw": 3.0}
    assert classify_sector_state(data) == "主升"


def test_classify_sector_state_zhuanqiang_when_high_score_but_narrow():
    data = {"observation_score": 55.0, "breadth_raw": 0.3, "continuation_raw": 1, "rs_raw": 1.0}
    assert classify_sector_state(data) == "轉強"


def test_classify_sector_state_jitan_when_positive_rs_but_no_continuation():
    data = {"observation_score": 30.0, "breadth_raw": 0.4, "continuation_raw": 0, "rs_raw": 2.0}
    assert classify_sector_state(data) == "急彈"


def test_classify_sector_state_zhuanruo_when_negative_rs():
    data = {"observation_score": 20.0, "breadth_raw": 0.3, "continuation_raw": 0, "rs_raw": -1.5}
    assert classify_sector_state(data) == "轉弱"


def test_classify_sector_state_wait_when_score_none():
    data = {"observation_score": None, "breadth_raw": None, "continuation_raw": None, "rs_raw": None}
    assert classify_sector_state(data) == "等待確認"


def test_build_sector_priority_sorts_desc_and_limits_top_n():
    observation_scores = {
        "記憶體": {"observation_score": 82.0, "score_coverage": 1.0, "rs_raw": 4.1, "breadth_raw": 0.8,
                  "continuation_raw": 3, "volume_raw": 1.6, "chips_raw": 0.7, "partial_coverage": False},
        "航運": {"observation_score": 55.0, "score_coverage": 1.0, "rs_raw": 1.2, "breadth_raw": 0.6,
                "continuation_raw": 1, "volume_raw": 1.1, "chips_raw": 0.5, "partial_coverage": False},
        "金融": {"observation_score": 20.0, "score_coverage": 0.9, "rs_raw": -1.0, "breadth_raw": 0.2,
                "continuation_raw": 0, "volume_raw": 0.8, "chips_raw": None, "partial_coverage": True},
    }
    result = build_sector_priority(observation_scores, top_n=2)

    assert len(result) == 2
    assert result[0]["meta_name"] == "記憶體"
    assert result[0]["rank"] == 1
    assert result[1]["meta_name"] == "航運"
    assert result[1]["rank"] == 2


def test_build_sector_priority_none_score_sorts_last():
    observation_scores = {
        "A": {"observation_score": 10.0, "score_coverage": 1.0, "rs_raw": None, "breadth_raw": None,
              "continuation_raw": None, "volume_raw": None, "chips_raw": None, "partial_coverage": False},
        "B": {"observation_score": None, "score_coverage": 0.0, "rs_raw": None, "breadth_raw": None,
              "continuation_raw": None, "volume_raw": None, "chips_raw": None, "partial_coverage": False},
    }
    result = build_sector_priority(observation_scores, top_n=5)
    assert [r["meta_name"] for r in result] == ["A", "B"]
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'export.momentum_generator'`）

- [ ] **Step 3: 實作**

建立 `export/momentum_generator.py`：

```python
"""
生成 docs/momentum.html — 逆轟動能策略 v2 決策支援頁
資料來源：scan_momentum_health() + scan_bullish_alignment_new_high() +
         scan_consecutive_limit_up() + classify_market_regime() +
         calc_meta_observation_scores()
設計依據：docs/superpowers/specs/2026-07-16-momentum-strategy-page-v2-design.md（v2，取代
         2026-07-14/2026-07-15 兩份舊 spec）。

⚠️ docs/superpowers/plans/2026-07-16-momentum-strategy-page.md 是 v2 spec 定案前的舊 plan，
裡面的函式（tier_action_text/regime_banner_content/resilience_candidates）使用 v2 明文禁止
的命令式文案且誤用5日rs_market_score，本檔案函式名稱與邏輯跟那份舊 plan 完全不同、不相容，
不要混用。
"""
from html import escape as _html_escape

# v2 spec §4.2：上線前必須全文搜尋並禁止這些命令式字樣，generate() 的輸出不得含有任何一個。
BANNED_PHRASES = ("隨時加碼", "一定續抱", "直接出清", "立刻砍", "可換入", "反手放空")

# 跌停/重挫 proxy 門檻，跟 screener/signals.py 的同名私有常數同步維護（v2 spec §3.3/§3.6）。
_LIMIT_DOWN_PCT = -9.5
_EXIT_BIG_BLACK_PCT = -4.0

# classify_sector_state() 草案門檻——spec §2.2 只有質化描述，沒有精確切點，這些數字是
# writing-plans 階段新增的草案，待回測校準，見本計畫 Global Constraints 說明。
_SECTOR_STATE_SCORE_STRONG = 65.0
_SECTOR_STATE_SCORE_TURNING = 50.0
_SECTOR_STATE_BREADTH_BROAD = 0.5


def _esc(value) -> str:
    """HTML-escape 外部資料（股票/族群名稱等），比照 chips_generator.py::_esc() 同一防護。"""
    return _html_escape(str(value)) if value else ""


def rs_sample_confidence(rs_sample_count: int) -> str:
    """
    族群內 RS 樣本信心分級（v2 spec §3.2）。單一成分股必然 rs_rank_pct=1.0、兩檔股票最差
    也可能是0.5，會產生假精準，這裡分三級供消費端判斷是否能單靠 rs_rank_pct 升級成進場候選。

    ≥10 檔 → "A"；5~9 檔 → "B"；<5 檔 → "C"（低樣本，見 determine_final_label() 的
    § 3.4 進場閘門：C 時不能單靠 RS 排名升級成進場候選）。
    """
    if rs_sample_count >= 10:
        return "A"
    if rs_sample_count >= 5:
        return "B"
    return "C"


def market_permission(market_regime: dict, index_date: str = None, price_date: str = None) -> dict:
    """
    市場操作許可（v2 spec §2.1）。market_regime 是既有
    processors/performance.py::classify_market_regime() 的回傳 dict，外加呼叫端已合併的
    taiex_change_pct/breadth_ratio/concentration_direction（main.py::run() 既有合併方式）。

    index_date/price_date 由呼叫端傳入實際資料日期；兩者不同時降級為 "unknown"，不輸出市場
    操作文案（v2 spec §2.1：這個一致性檢查必須由呼叫端提供真實日期，這支函式只負責比較，不
    猜測資料是否新鮮）。任一為 None（呼叫端未提供）時跳過日期檢查，直接依 tier 判斷。

    Returns
    -------
    {permission, tier_text, divergence_text, advice_text}
    permission ∈ {"normal", "selective", "defensive", "unknown"}
    """
    if index_date is not None and price_date is not None and index_date != price_date:
        return {
            "permission": "unknown",
            "tier_text": "資料日期不一致",
            "divergence_text": f"指數資料日期 {index_date} 與個股行情日期 {price_date} 不同，暫不輸出市場操作許可。",
            "advice_text": "",
        }

    tier = market_regime.get("tier", "持平")
    if tier in ("大漲", "小漲"):
        permission = "normal"
    elif tier in ("小跌", "大跌"):
        permission = "defensive"
    else:
        permission = "selective"

    taiex_pct = market_regime.get("taiex_change_pct")
    breadth = market_regime.get("breadth_ratio")
    concentration_direction = market_regime.get("concentration_direction")

    divergence_text = ""
    if tier == "持平" and taiex_pct is not None and abs(taiex_pct) >= 0.3:
        direction = "上漲" if taiex_pct > 0 else "下跌"
        breadth_str = f"{breadth * 100:.0f}%" if breadth is not None else "─"
        divergence_text = (
            f"指數{direction} {taiex_pct:+.2f}%，但個股上漲家數比僅 {breadth_str}，"
            f"廣度未確認方向，暫列為持平／選擇性操作。"
        )
    if concentration_direction:
        prefix = f"{divergence_text} " if divergence_text else ""
        divergence_text = f"{prefix}資金集中診斷：{concentration_direction}。"

    if permission == "normal":
        advice_text = "市場許可正常尋找進場候選；仍須逐項確認個股進場閘門，非全面買進。"
    elif permission == "selective":
        advice_text = "只看條件完整的強勢候選；訊號不足的個股維持觀察，不追價。"
    else:
        advice_text = "停止一般追價，優先檢視抗跌個股與持有風險；本區不建議任何放空操作。"

    return {
        "permission": permission,
        "tier_text": tier,
        "divergence_text": divergence_text,
        "advice_text": advice_text,
    }


def classify_sector_state(observation_data: dict) -> str:
    """
    族群狀態五級分類（v2 spec §2.2 prose 描述，草案門檻，見 Global Constraints）。
    只用來決定 determine_final_label() 的進場閘門（sector_state in {主升,轉強}）及頁面顯示
    文字，不直接產生買賣動作。

    observation_data 是 calc_meta_observation_scores() 回傳 dict 裡單一族群的 value。
    """
    score = observation_data.get("observation_score")
    breadth = observation_data.get("breadth_raw")
    continuation = observation_data.get("continuation_raw")
    rs_raw = observation_data.get("rs_raw")

    if score is None:
        return "等待確認"
    if score >= _SECTOR_STATE_SCORE_STRONG and breadth is not None and breadth >= _SECTOR_STATE_BREADTH_BROAD:
        return "主升"
    if score >= _SECTOR_STATE_SCORE_TURNING:
        return "轉強"
    if rs_raw is not None and rs_raw > 0 and (continuation is None or continuation <= 1):
        return "急彈"
    if rs_raw is not None and rs_raw < 0:
        return "轉弱"
    return "等待確認"


def build_sector_priority(observation_scores: dict, top_n: int = 5) -> list:
    """
    主流族群 Top N（v2 spec §2.2/§4）。observation_scores 是既有
    processors/observation_scores.py::calc_meta_observation_scores() 的回傳 dict。

    observation_score 為 None 的族群排最後（5因子全不可用，見該函式邊界情況），依
    observation_score 降冪排列，回傳前 top_n 筆，每筆含 rank（1-based，只在回傳的
    top_n 筆內編號，不是全族群排名）。
    """
    rows = []
    for meta_name, data in observation_scores.items():
        rows.append({
            "meta_name": meta_name,
            "observation_score": data.get("observation_score"),
            "score_coverage": data.get("score_coverage", 0.0),
            "rs_raw": data.get("rs_raw"),
            "breadth_raw": data.get("breadth_raw"),
            "continuation_raw": data.get("continuation_raw"),
            "volume_raw": data.get("volume_raw"),
            "chips_raw": data.get("chips_raw"),
            "partial_coverage": data.get("partial_coverage", False),
            "sector_state": classify_sector_state(data),
        })
    rows.sort(key=lambda r: r["observation_score"] if r["observation_score"] is not None else -1.0, reverse=True)
    top_rows = rows[:top_n]
    for i, row in enumerate(top_rows):
        row["rank"] = i + 1
    return top_rows
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（15 passed）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator 業務邏輯層I(RS樣本信心/市場許可/族群狀態/主流族群優先序)"
```

---

### Task 3：`export/momentum_generator.py` 業務邏輯層 II——最終決策標籤／個股決策主表

**Files:**
- Modify: `export/momentum_generator.py`（新增函式，加在 Task 2 函式之後）
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- `determine_final_label(stock_row: dict, market_permission_state: str, sector_state: str, bullish_new_high_map: dict) -> str`：
  六選一（spec §2.4）：`進場候選`／`續強觀察`／`等待確認`／`風險升高`／`出場條件命中`／`跌停風險`
- `build_decision_table(momentum_results: list, bullish_new_high_results: list, market_permission_state: str, sector_states: dict) -> list`：
  組合成個股決策主表（spec §4.1），依族群最強個股排序分組、組內依技術狀態強弱＋族群內RS排名排序

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_momentum_generator.py` 加入（先加一行 import）：

```python
from export.momentum_generator import determine_final_label, build_decision_table


def _base_stock_row(**overrides):
    row = {
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
        "close": 900.0, "change_pct": 2.0, "ma5": 890.0, "ma10": 870.0, "ma20": 850.0, "ma60": 800.0,
        "ma_alignment": "多頭排列", "ma5_slope_down": False, "below_ma5": False, "big_black_proxy": False,
        "ma5_rising": True, "ma10_rising": True, "exit_3_rule_triggered": False, "entry_confirmed": True,
        "rs_score": 3.0, "rs_rank_pct": 0.9, "rs_market_score": 4.0, "rs_sample_count": 12,
        "daily_excess_pct": 1.5, "strength_tier": "超強",
    }
    row.update(overrides)
    return row


def test_determine_final_label_limit_down_takes_top_priority():
    """跌停風險優先權最高：即使同時符合出場條件命中，也只顯示跌停風險（流動性風險最急迫）。"""
    row = _base_stock_row(change_pct=-9.6, exit_3_rule_triggered=True, strength_tier="超弱")
    label = determine_final_label(row, "defensive", "轉弱", {})
    assert label == "跌停風險"


def test_determine_final_label_exit_condition_hit():
    row = _base_stock_row(change_pct=-5.0, exit_3_rule_triggered=True, strength_tier="超弱")
    label = determine_final_label(row, "normal", "主升", {})
    assert label == "出場條件命中"


def test_determine_final_label_entry_candidate_when_all_gates_pass():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label == "進場候選"


def test_determine_final_label_blocked_by_low_rs_confidence():
    """RS樣本信心是C（<5檔）時，即使其他閘門都成立，也不能升級成進場候選（spec §3.2/§3.4）。"""
    row = _base_stock_row(rs_sample_count=3)
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label != "進場候選"
    assert label == "續強觀察"


def test_determine_final_label_blocked_by_missing_volume_confirmed():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": False}}
    label = determine_final_label(row, "normal", "主升", bullish_map)
    assert label != "進場候選"


def test_determine_final_label_blocked_when_not_in_bullish_new_high_list():
    row = _base_stock_row()
    label = determine_final_label(row, "normal", "主升", {})  # 2330不在B3清單
    assert label != "進場候選"


def test_determine_final_label_blocked_when_market_defensive():
    row = _base_stock_row()
    bullish_map = {"2330": {"stock_id": "2330", "volume_confirmed": True}}
    label = determine_final_label(row, "defensive", "主升", bullish_map)
    assert label == "風險升高"


def test_determine_final_label_risk_elevated_for_weak_tier():
    row = _base_stock_row(strength_tier="弱", ma_alignment="空頭排列", entry_confirmed=False)
    label = determine_final_label(row, "normal", "轉弱", {})
    assert label == "風險升高"


def test_determine_final_label_continued_strength_watch_when_gate_incomplete():
    """超強/強但進場閘門不完整（例如不在B3清單）時，顯示續強觀察，不是進場候選。"""
    row = _base_stock_row(strength_tier="強")
    label = determine_final_label(row, "normal", "轉強", {})
    assert label == "續強觀察"


def test_determine_final_label_wait_for_confirmation_default():
    row = _base_stock_row(strength_tier="整理", ma_alignment="糾結", entry_confirmed=False, rs_rank_pct=None)
    label = determine_final_label(row, "selective", "等待確認", {})
    assert label == "等待確認"


def test_build_decision_table_groups_by_sector_strength_and_sorts():
    momentum_results = [
        _base_stock_row(stock_id="2330", stock_name="台積電", meta_sector="半導體", rs_rank_pct=0.9, strength_tier="超強"),
        _base_stock_row(stock_id="2454", stock_name="聯發科", meta_sector="半導體", rs_rank_pct=0.5, strength_tier="強"),
        _base_stock_row(stock_id="2603", stock_name="長榮", meta_sector="航運", rs_rank_pct=0.3, strength_tier="整理", ma_alignment="糾結"),
    ]
    sector_states = {"半導體": "主升", "航運": "等待確認"}
    table = build_decision_table(momentum_results, [], "normal", sector_states)

    ids = [r["stock_id"] for r in table]
    assert ids == ["2330", "2454", "2603"]  # 半導體(較強族群)優先，組內2330>2454
    assert table[0]["sector_state"] == "主升"
    assert table[0]["rs_confidence"] == "A"  # rs_sample_count=12


def test_build_decision_table_includes_entry_and_exit_evidence():
    momentum_results = [_base_stock_row()]
    bullish_results = [{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
                         "close": 900.0, "change_pct": 2.0, "ma5": 890.0, "ma10": 870.0, "ma60": 800.0,
                         "lookback_days": 60, "volume_ratio_20d": 1.8, "volume_confirmed": True}]
    sector_states = {"半導體": "主升"}
    table = build_decision_table(momentum_results, bullish_results, "normal", sector_states)

    row = table[0]
    assert row["final_label"] == "進場候選"
    assert ("多頭排列＋創新高（B3清單內）", True) in row["entry_evidence"]
    assert ("量能確認（B3量比≥1.5）", True) in row["entry_evidence"]
    assert ("跌破五日線", False) in row["exit_evidence"]
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py -k "final_label or decision_table" -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

在 `export/momentum_generator.py` 加入（`build_sector_priority()` 之後）：

```python
_RS_CONFIDENCE_BLOCKING = "C"

_TIER_ORDER = {"超強": 0, "強": 1, "整理": 2, "弱": 3, "超弱": 4}


def determine_final_label(
    stock_row: dict,
    market_permission_state: str,
    sector_state: str,
    bullish_new_high_map: dict,
) -> str:
    """
    最終決策標籤（v2 spec §2.4），六選一，全部為非命令式狀態描述。stock_row 是
    scan_momentum_health() 單筆輸出。bullish_new_high_map 是
    {stock_id: scan_bullish_alignment_new_high()單筆輸出}，供判斷 B3 清單成員資格與
    volume_confirmed（不能只傳一個 set，因為還需要讀 volume_confirmed 的值）。

    優先序（由上到下，符合就回傳，不繼續往下判斷）：
    1. 跌停風險：change_pct <= _LIMIT_DOWN_PCT（流動性風險最急迫，跟其他狀態互斥，
       即使同時符合出場條件命中或其他狀態也只顯示這個）
    2. 出場條件命中：exit_3_rule_triggered
    3. 進場候選：spec §3.4 六項閘門同時成立
    4. 風險升高：strength_tier=="弱" 或 market_permission_state=="defensive"
    5. 續強觀察：strength_tier in {"超強","強"}（但進場閘門未全部成立）
    6. 等待確認：其餘情況（整理、急彈、資料不足）
    """
    change_pct = stock_row.get("change_pct")
    if change_pct is not None and change_pct <= _LIMIT_DOWN_PCT:
        return "跌停風險"

    if stock_row.get("exit_3_rule_triggered"):
        return "出場條件命中"

    sid = stock_row.get("stock_id")
    confidence = rs_sample_confidence(stock_row.get("rs_sample_count", 0))
    b3_row = bullish_new_high_map.get(sid)
    entry_gate = (
        market_permission_state in ("normal", "selective")
        and sector_state in ("主升", "轉強")
        and stock_row.get("strength_tier") in ("超強", "強")
        and bool(stock_row.get("entry_confirmed"))
        and b3_row is not None
        and bool(b3_row.get("volume_confirmed"))
        and confidence != _RS_CONFIDENCE_BLOCKING
    )
    if entry_gate:
        return "進場候選"

    if stock_row.get("strength_tier") == "弱" or market_permission_state == "defensive":
        return "風險升高"

    if stock_row.get("strength_tier") in ("超強", "強"):
        return "續強觀察"

    return "等待確認"


def build_decision_table(
    momentum_results: list,
    bullish_new_high_results: list,
    market_permission_state: str,
    sector_states: dict,
) -> list:
    """
    個股決策主表（v2 spec §4/§4.1）。組合 scan_momentum_health() +
    scan_bullish_alignment_new_high() + 族群狀態 + 市場許可 → 每檔股票的最終標籤與證據。

    sector_states：{meta_name: sector_state_str}，呼叫端先對 calc_meta_observation_scores()
    的**全量**輸出（不只 build_sector_priority() 的 top_n）逐族群跑過 classify_sector_state()——
    個股不會因為所屬族群沒排進首頁Top5就被排除在主表外。

    排序：先依族群內最強個股的技術狀態排序分組（族群整體越強，組別排越前面），組內再依
    strength_tier（超強>強>整理>弱>超弱）與 rs_rank_pct 降冪排列。
    """
    bullish_map = {r["stock_id"]: r for r in bullish_new_high_results}

    rows = []
    for row in momentum_results:
        meta_name = row.get("meta_sector")
        sector_state = sector_states.get(meta_name, "等待確認")
        label = determine_final_label(row, market_permission_state, sector_state, bullish_map)
        confidence = rs_sample_confidence(row.get("rs_sample_count", 0))
        b3_row = bullish_map.get(row["stock_id"])
        rows.append({
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "meta_sector": meta_name,
            "sector_state": sector_state,
            "close": row["close"],
            "change_pct": row["change_pct"],
            "strength_tier": row["strength_tier"],
            "rs_rank_pct": row["rs_rank_pct"],
            "rs_sample_count": row.get("rs_sample_count", 0),
            "rs_confidence": confidence,
            "rs_market_score": row.get("rs_market_score"),
            "daily_excess_pct": row.get("daily_excess_pct"),
            "final_label": label,
            "entry_evidence": [
                ("多頭排列＋創新高（B3清單內）", b3_row is not None),
                ("量能確認（B3量比≥1.5）", bool(b3_row.get("volume_confirmed")) if b3_row else False),
                ("動能確認：MA5/MA10皆上揚", bool(row.get("entry_confirmed"))),
            ],
            "exit_evidence": [
                ("跌破五日線", bool(row.get("below_ma5"))),
                ("五日線下彎", bool(row.get("ma5_slope_down"))),
                ("重挫proxy（單日跌幅近似，非完整K棒長黑）", bool(row.get("big_black_proxy"))),
            ],
            "ma": {"ma5": row["ma5"], "ma10": row["ma10"], "ma20": row["ma20"], "ma60": row["ma60"]},
        })

    sector_best_rank: dict = {}
    for row in rows:
        combo = (_TIER_ORDER.get(row["strength_tier"], 5), -(row["rs_rank_pct"] or 0))
        s = row["meta_sector"]
        if s not in sector_best_rank or combo < sector_best_rank[s]:
            sector_best_rank[s] = combo

    rows.sort(key=lambda r: (
        sector_best_rank[r["meta_sector"]],
        _TIER_ORDER.get(r["strength_tier"], 5),
        -(r["rs_rank_pct"] or 0),
    ))
    return rows
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（27 passed）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator 業務邏輯層II(最終決策標籤/個股決策主表)"
```

---

### Task 4：`export/momentum_generator.py` 業務邏輯層 III——急殺風險區／連續近漲停卡片

**Files:**
- Modify: `export/momentum_generator.py`（新增函式，加在 Task 3 函式之後）
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- `selloff_risk_zone(momentum_results: list) -> dict`：`{"resilient": [...], "limit_down": [...]}`
  （spec §3.1/§3.6，急殺模式候選**必須用 `daily_excess_pct`**，不能用 `rs_market_score`）
- `build_streak_cards(limit_up_results: list) -> list`：連續收近漲停卡片資料（spec §3.5）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_momentum_generator.py` 加入（先加一行 import）：

```python
from export.momentum_generator import selloff_risk_zone, build_streak_cards


def test_selloff_risk_zone_uses_daily_excess_pct_not_rs_market_score():
    """關鍵回歸：急殺風險區必須用daily_excess_pct（單日抗跌），不能誤用5日rs_market_score
    （v2 spec §3.1 明訂，這是舊plan犯過的錯）。這檔股票今日抗跌(daily_excess_pct>0)但
    5日相對大盤是負的(rs_market_score<0)，應該被列入抗跌候選。"""
    momentum_results = [
        {"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
         "change_pct": -0.5, "daily_excess_pct": 1.2, "rs_market_score": -2.0},
    ]
    result = selloff_risk_zone(momentum_results)
    assert [r["stock_id"] for r in result["resilient"]] == ["2609"]


def test_selloff_risk_zone_splits_resilient_and_limit_down():
    momentum_results = [
        {"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
         "change_pct": 1.2, "daily_excess_pct": 3.0, "rs_market_score": 1.0},
        {"stock_id": "2617", "stock_name": "台航", "meta_sector": "航運",
         "change_pct": -0.4, "daily_excess_pct": 1.4, "rs_market_score": 0.5},
        {"stock_id": "2023", "stock_name": "燁輝", "meta_sector": "鋼鐵",
         "change_pct": -9.7, "daily_excess_pct": -8.0, "rs_market_score": -7.0},
        {"stock_id": "9999", "stock_name": "無關股", "meta_sector": "其他",
         "change_pct": -1.0, "daily_excess_pct": -0.5, "rs_market_score": -0.2},
    ]
    result = selloff_risk_zone(momentum_results)

    resilient_ids = [r["stock_id"] for r in result["resilient"]]
    limit_down_ids = [r["stock_id"] for r in result["limit_down"]]
    assert resilient_ids == ["2609", "2617"]  # daily_excess_pct>0，依分數降冪
    assert limit_down_ids == ["2023"]
    assert "9999" not in resilient_ids and "9999" not in limit_down_ids


def test_selloff_risk_zone_limit_down_takes_precedence_over_resilient():
    momentum_results = [
        {"stock_id": "1111", "stock_name": "極端股", "meta_sector": "測試",
         "change_pct": -9.6, "daily_excess_pct": 2.0, "rs_market_score": 3.0},
    ]
    result = selloff_risk_zone(momentum_results)
    assert [r["stock_id"] for r in result["limit_down"]] == ["1111"]
    assert result["resilient"] == []


def test_build_streak_cards_carries_breakout_volume_confirmed():
    limit_up_results = [
        {"stock_id": "6770", "stock_name": "力積電", "meta_sector": "半導體", "close": 50.0,
         "change_pct": 9.8, "volume": 100000, "limit_up_streak": 4,
         "volume_declining_streak": True, "breakout_volume_confirmed": True},
        {"stock_id": "1560", "stock_name": "中砂", "meta_sector": "工具機", "close": 80.0,
         "change_pct": 9.9, "volume": 50000, "limit_up_streak": 3,
         "volume_declining_streak": True, "breakout_volume_confirmed": False},
    ]
    cards = build_streak_cards(limit_up_results)

    assert cards[0]["stock_id"] == "6770"
    assert cards[0]["breakout_volume_confirmed"] is True
    assert cards[1]["breakout_volume_confirmed"] is False
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py -k "risk_zone or streak_cards" -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 實作**

在 `export/momentum_generator.py` 加入（`build_decision_table()` 之後）：

```python
def selloff_risk_zone(momentum_results: list) -> dict:
    """
    急殺風險區資料（v2 spec §3.1/§3.6/§4「僅defensive顯示」）。這支函式本身不檢查市場
    許可狀態，純資料整理，呼叫端（generate()）決定要不要渲染這個區塊。

    抗跌候選：daily_excess_pct > 0（今日抗跌優於大盤單日均值），依 daily_excess_pct 降冪
    排列。**必須用 daily_excess_pct，不能用 rs_market_score**（v2 spec §3.1：急殺模式候選
    條件使用單日 daily_excess_pct，rs_market_score 是5日週期，兩者不可互相代替）。
    跌停風險：change_pct <= _LIMIT_DOWN_PCT，優先權高於抗跌候選（同時符合兩邊時只算跌停
    風險，流動性風險比抗跌排名更急迫）。
    """
    limit_down = [
        r for r in momentum_results
        if r.get("change_pct") is not None and r["change_pct"] <= _LIMIT_DOWN_PCT
    ]
    limit_down_ids = {r["stock_id"] for r in limit_down}

    resilient = [
        r for r in momentum_results
        if r.get("daily_excess_pct") is not None and r["daily_excess_pct"] > 0
        and r["stock_id"] not in limit_down_ids
    ]
    resilient.sort(key=lambda r: r["daily_excess_pct"], reverse=True)

    return {
        "resilient": [
            {"stock_id": r["stock_id"], "stock_name": r["stock_name"], "meta_sector": r["meta_sector"],
             "change_pct": r["change_pct"], "daily_excess_pct": r["daily_excess_pct"]}
            for r in resilient
        ],
        "limit_down": [
            {"stock_id": r["stock_id"], "stock_name": r["stock_name"], "meta_sector": r["meta_sector"],
             "change_pct": r["change_pct"]}
            for r in limit_down
        ],
    }


def build_streak_cards(limit_up_results: list) -> list:
    """
    連續收近漲停卡片資料（v2 spec §3.5，顯示名稱固定用「連續收近漲停」，不再稱「鎖死」，
    因為現有資料無法證明盤中全程鎖死）。直接沿用 scan_consecutive_limit_up() 既有降冪排序。
    """
    return [
        {
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "meta_sector": row["meta_sector"],
            "limit_up_streak": row["limit_up_streak"],
            "volume_declining_streak": row["volume_declining_streak"],
            "breakout_volume_confirmed": row["breakout_volume_confirmed"],
        }
        for row in limit_up_results
    ]
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（31 passed）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator 業務邏輯層III(急殺風險區用daily_excess_pct/連續近漲停卡片)"
```

---

### Task 5：`generate()` HTML 頁面生成（CSS/HTML + 禁用文案回歸測試）

**Files:**
- Modify: `export/momentum_generator.py`（新增 `generate()` 及 CSS 常數，加在檔案最後）
- Test: `tests/test_momentum_generator.py`

**Interfaces:**
- `generate(trade_date, market_permission_data: dict, sector_priority: list, decision_table: list, risk_zone: dict, streak_cards: list, index_date: str = None, price_date: str = None, chips_date: str = None, output_path: str = "docs/momentum.html") -> bool`：
  回傳是否實際寫入（`decision_table` 為空時不寫檔、回傳 `False`，比照 `chips_generator.py::generate()`
  既有慣例）。急殺風險區只在 `market_permission_data["permission"] == "defensive"` 時渲染。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_momentum_generator.py` 加入（先加一行 import）：

```python
from export.momentum_generator import generate, BANNED_PHRASES


def _sample_decision_row(**overrides):
    row = {
        "stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體", "sector_state": "主升",
        "close": 900.0, "change_pct": 2.0, "strength_tier": "超強", "rs_rank_pct": 0.9,
        "rs_sample_count": 12, "rs_confidence": "A", "rs_market_score": 4.0, "daily_excess_pct": 1.5,
        "final_label": "進場候選",
        "entry_evidence": [("多頭排列＋創新高（B3清單內）", True), ("量能確認（B3量比≥1.5）", True),
                            ("動能確認：MA5/MA10皆上揚", True)],
        "exit_evidence": [("跌破五日線", False), ("五日線下彎", False), ("重挫proxy（單日跌幅近似，非完整K棒長黑）", False)],
        "ma": {"ma5": 890.0, "ma10": 870.0, "ma20": 850.0, "ma60": 800.0},
    }
    row.update(overrides)
    return row


def test_generate_returns_false_and_skips_write_when_decision_table_empty(tmp_path):
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "normal", "tier_text": "小漲", "divergence_text": "", "advice_text": "正常尋找進場候選"}

    result = generate(date(2026, 7, 19), permission, [], [], {}, [], output_path=str(output_path))

    assert result is False
    assert not output_path.exists()


def test_generate_writes_page_with_core_sections(tmp_path):
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "normal", "tier_text": "小漲", "divergence_text": "", "advice_text": "正常尋找進場候選"}
    sector_priority = [{"meta_name": "半導體", "rank": 1, "observation_score": 82.0, "score_coverage": 1.0,
                        "sector_state": "主升", "partial_coverage": False}]
    decision_table = [_sample_decision_row()]

    result = generate(date(2026, 7, 19), permission, sector_priority, decision_table, {}, [], output_path=str(output_path))

    assert result is True
    html = output_path.read_text(encoding="utf-8")
    assert "台積電" in html
    assert "進場候選" in html
    assert "半導體" in html


def test_generate_never_contains_banned_command_phrases(tmp_path):
    """v2 spec §4.2 上線前全文搜尋禁止字樣的回歸測試——這是最終驗收條件的核心測試。"""
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "defensive", "tier_text": "大跌", "divergence_text": "資金集中診斷：中小型輪動。",
                  "advice_text": "停止一般追價，優先檢視抗跌個股與持有風險；本區不建議任何放空操作。"}
    sector_priority = [{"meta_name": "半導體", "rank": 1, "observation_score": 30.0, "score_coverage": 1.0,
                        "sector_state": "轉弱", "partial_coverage": False}]
    decision_table = [_sample_decision_row(final_label="出場條件命中", strength_tier="超弱")]
    risk_zone = {
        "resilient": [{"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
                       "change_pct": 1.2, "daily_excess_pct": 3.0}],
        "limit_down": [{"stock_id": "2023", "stock_name": "燁輝", "meta_sector": "鋼鐵", "change_pct": -9.7}],
    }

    generate(date(2026, 7, 19), permission, sector_priority, decision_table, risk_zone, [], output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    for phrase in BANNED_PHRASES:
        assert phrase not in html, f"頁面出現禁用命令式文案：{phrase}"


def test_generate_escapes_malicious_stock_name(tmp_path):
    """股票名稱來自 universe.csv，頁面會發布到 GitHub Pages，比照 chips_generator.py 既有防護。"""
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "normal", "tier_text": "小漲", "divergence_text": "", "advice_text": ""}
    decision_table = [_sample_decision_row(stock_name="<script>alert(1)</script>")]

    generate(date(2026, 7, 19), permission, [], decision_table, {}, [], output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html


def test_generate_renders_risk_zone_only_when_defensive(tmp_path):
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "normal", "tier_text": "小漲", "divergence_text": "", "advice_text": ""}
    decision_table = [_sample_decision_row()]
    risk_zone = {"resilient": [{"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
                                "change_pct": 1.2, "daily_excess_pct": 3.0}], "limit_down": []}

    generate(date(2026, 7, 19), permission, [], decision_table, risk_zone, [], output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "陽明" not in html  # market_permission=normal，急殺風險區不渲染


def test_generate_renders_risk_zone_when_defensive(tmp_path):
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "defensive", "tier_text": "大跌", "divergence_text": "", "advice_text": ""}
    decision_table = [_sample_decision_row()]
    risk_zone = {"resilient": [{"stock_id": "2609", "stock_name": "陽明", "meta_sector": "航運",
                                "change_pct": 1.2, "daily_excess_pct": 3.0}], "limit_down": []}

    generate(date(2026, 7, 19), permission, [], decision_table, risk_zone, [], output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "陽明" in html


def test_generate_unknown_permission_suppresses_advice_text(tmp_path):
    output_path = tmp_path / "momentum.html"
    permission = {"permission": "unknown", "tier_text": "資料日期不一致",
                  "divergence_text": "指數資料日期 2026-07-18 與個股行情日期 2026-07-19 不同，暫不輸出市場操作許可。",
                  "advice_text": ""}
    decision_table = [_sample_decision_row()]

    generate(date(2026, 7, 19), permission, [], decision_table, {}, [], output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "資料日期不一致" in html
```

- [ ] **Step 2: 執行確認失敗**

Run: `python -m pytest tests/test_momentum_generator.py -k generate -q`
Expected: FAIL（`ImportError: cannot import name 'generate'`）

- [ ] **Step 3: 實作**

在 `export/momentum_generator.py` 開頭 import 區塊補上：

```python
import json
from datetime import date
from pathlib import Path
```

在檔案最後加入：

```python
_CSS = """
:root{--bg:#080B12;--panel:#0F1420;--panel-2:#161D2C;--border:#293346;
  --ink:#DADFE8;--ink-2:#98A0B4;--ink-3:#636B80;--up:#E6432F;--down:#37B25C;
  --accent:#F0BB55;--tier-super:#F0BB55;--tier-strong:#4FC46A;--tier-mid:#8B94AC;
  --tier-weak:#E08A3E;--tier-superweak:#E6432F;
  --sans:"Public Sans",-apple-system,"PingFang TC","Microsoft JhengHei","Segoe UI",sans-serif;
  --mono:ui-monospace,"IBM Plex Mono","Cascadia Code","Roboto Mono",monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55;padding:0 0 80px}
.tabular{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:inherit}
.skip-link{position:absolute;left:-999px;top:0;background:var(--panel);color:var(--ink);padding:8px 14px;z-index:100}
.skip-link:focus{left:8px;top:8px}
.topbar{display:flex;align-items:baseline;gap:16px;padding:18px 24px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.topbar h1{font-size:1.2rem;font-weight:700;margin:0}
.topbar .sub{font-size:.72rem;color:var(--ink-3)}
.nav-links{display:flex;gap:8px;margin-left:auto}
.nav-link{font-size:.78rem;padding:5px 14px;border-radius:6px;border:1px solid var(--border);color:var(--ink-2);text-decoration:none}
.nav-link:hover{border-color:var(--ink-2);color:var(--ink)}
.nav-link.active{border-color:var(--accent);color:var(--ink);background:var(--panel-2)}
.nav-link:focus-visible,button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.notice{margin:16px 24px;padding:10px 16px;border:1px solid var(--border);border-radius:8px;color:var(--ink-2);font-size:.8rem}
.permission-banner{margin:0 24px 20px;padding:18px 20px;border-radius:10px;border:1px solid var(--border);border-left:4px solid var(--tier-mid)}
.permission-banner[data-permission="normal"]{border-left-color:var(--tier-strong)}
.permission-banner[data-permission="selective"]{border-left-color:var(--accent)}
.permission-banner[data-permission="defensive"]{border-left-color:var(--tier-superweak)}
.permission-banner[data-permission="unknown"]{border-left-color:var(--ink-3)}
.permission-banner h2{margin:0 0 6px;font-size:1.1rem}
.permission-banner p{margin:4px 0;color:var(--ink-2);font-size:.85rem}
.section-head{margin:28px 24px 10px}
.section-head h2{font-size:1rem;margin:0}
.sector-grid{display:flex;gap:10px;flex-wrap:wrap;margin:0 24px}
.sector-card{border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--panel);min-width:150px}
.sector-card .rank{color:var(--accent);font-weight:700;font-family:var(--mono)}
.sector-card .state{font-size:.72rem;color:var(--ink-2)}
table.decision-table{width:100%;border-collapse:collapse;margin:0 24px;max-width:calc(100% - 48px)}
.decision-table th,.decision-table td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;font-size:.82rem}
.decision-table th{color:var(--ink-3);font-weight:600;font-size:.72rem;text-transform:uppercase}
.tier-badge{padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:600}
.tier-badge[data-tier="超強"]{color:var(--tier-super)}
.tier-badge[data-tier="強"]{color:var(--tier-strong)}
.tier-badge[data-tier="整理"]{color:var(--tier-mid)}
.tier-badge[data-tier="弱"]{color:var(--tier-weak)}
.tier-badge[data-tier="超弱"]{color:var(--tier-superweak)}
.label-badge{padding:3px 10px;border-radius:12px;font-size:.72rem;font-weight:600;border:1px solid var(--border)}
.up{color:var(--up)}.down{color:var(--down)}
details.evidence{margin-top:4px}
details.evidence summary{cursor:pointer;font-size:.76rem;color:var(--ink-2)}
.evidence-list{margin:6px 0 0;padding-left:18px;font-size:.78rem;color:var(--ink-2)}
.evidence-list li[data-pass="true"]{color:var(--tier-strong)}
.evidence-list li[data-pass="false"]{color:var(--ink-3)}
.risk-zone{margin:28px 24px;padding:16px 20px;border:1px solid var(--tier-superweak);border-radius:10px}
.risk-zone h2{margin:0 0 10px;font-size:1rem}
.streak-grid{display:flex;gap:10px;flex-wrap:wrap;margin:0 24px}
.streak-card{border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--panel)}
.overflow-wrap{overflow-x:auto}
"""


def _pct_str(value) -> str:
    if value is None:
        return "─"
    cls = "up" if value > 0 else ("down" if value < 0 else "")
    sign = "+" if value > 0 else ""
    return f'<span class="tabular {cls}">{sign}{value:.2f}%</span>'


def _evidence_list(items: list) -> str:
    lis = "".join(
        f'<li data-pass="{"true" if passed else "false"}">{"✓" if passed else "✗"} {_esc(label)}</li>'
        for label, passed in items
    )
    return f'<ul class="evidence-list">{lis}</ul>'


def _sector_priority_html(sector_priority: list) -> str:
    if not sector_priority:
        return ""
    cards = []
    for row in sector_priority:
        score = row.get("observation_score")
        score_str = f"{score:.1f}" if score is not None else "─"
        coverage = row.get("score_coverage", 0.0)
        cards.append(
            f'<div class="sector-card" id="sector-{_esc(row["meta_name"])}">'
            f'<span class="rank">#{row["rank"]}</span> '
            f'<strong>{_esc(row["meta_name"])}</strong>'
            f'<div class="state">觀察分 {score_str}（涵蓋率 {coverage*100:.0f}%）· {_esc(row.get("sector_state", ""))}</div>'
            f'</div>'
        )
    return (
        '<div class="section-head"><h2>主流族群 Top 5</h2>'
        '<p style="color:var(--ink-3);font-size:.78rem">觀察分為實驗性分數，用於決定優先展開順序，不直接產生買賣動作。</p></div>'
        f'<div class="sector-grid">{"".join(cards)}</div>'
    )


def _decision_table_html(decision_table: list) -> str:
    rows = []
    for row in decision_table:
        rs_cell = (
            f'<td class="tabular">{row["rs_rank_pct"]:.2f}（{_esc(row["rs_confidence"])}）</td>'
            if row["rs_rank_pct"] is not None else '<td>─</td>'
        )
        rows.append(
            "<tr>"
            f'<td><strong>{_esc(row["stock_name"])}</strong> {_esc(row["stock_id"])}'
            f'<div style="color:var(--ink-3);font-size:.72rem">{_esc(row["meta_sector"])} · {_esc(row["sector_state"])}</div></td>'
            f'<td><span class="tier-badge" data-tier="{_esc(row["strength_tier"])}">{_esc(row["strength_tier"])}</span></td>'
            + rs_cell
            + f'<td>{_pct_str(row.get("daily_excess_pct"))}</td>'
            f'<td><span class="label-badge">{_esc(row["final_label"])}</span></td>'
            "<td><details class=\"evidence\"><summary>展開證據</summary>"
            f'<strong style="font-size:.76rem">進場</strong>{_evidence_list(row["entry_evidence"])}'
            f'<strong style="font-size:.76rem">出場</strong>{_evidence_list(row["exit_evidence"])}'
            f'<div style="font-size:.74rem;color:var(--ink-3);margin-top:6px" class="tabular">'
            f'MA5 {row["ma"]["ma5"]} · MA10 {row["ma"]["ma10"]} · MA20 {row["ma"]["ma20"]} · MA60 {row["ma"]["ma60"]}</div>'
            "</details></td></tr>"
        )
    return "".join(rows)


def _risk_zone_html(risk_zone: dict) -> str:
    resilient = risk_zone.get("resilient", [])
    limit_down = risk_zone.get("limit_down", [])
    if not resilient and not limit_down:
        return ""
    resilient_rows = "".join(
        f'<li>{_esc(r["stock_name"])} {_esc(r["stock_id"])}（{_esc(r["meta_sector"])}）'
        f'今日抗跌差 {_pct_str(r["daily_excess_pct"])}</li>'
        for r in resilient
    )
    limit_down_rows = "".join(
        f'<li>{_esc(r["stock_name"])} {_esc(r["stock_id"])}（{_esc(r["meta_sector"])}）'
        f'{_pct_str(r["change_pct"])}</li>'
        for r in limit_down
    )
    return (
        '<div class="risk-zone"><h2>急殺風險區</h2>'
        '<p style="color:var(--ink-2);font-size:.8rem">僅市場許可為防禦模式時顯示。以下為抗跌候選與流動性風險提醒，'
        '不代表放空或出場委託指令。</p>'
        f'<div><strong>抗跌候選（今日抗跌差 &gt; 0）</strong><ul class="evidence-list">{resilient_rows or "<li>無</li>"}</ul></div>'
        f'<div><strong>跌停風險（流動性受限，實際委託可能無法成交）</strong><ul class="evidence-list">{limit_down_rows or "<li>無</li>"}</ul></div>'
        '</div>'
    )


def _streak_cards_html(streak_cards: list) -> str:
    if not streak_cards:
        return ""
    cards = "".join(
        f'<div class="streak-card"><strong>{_esc(c["stock_name"])}</strong> {_esc(c["stock_id"])}'
        f'<div class="tabular" style="font-size:.78rem;color:var(--ink-2)">連續收近漲停 {c["limit_up_streak"]} 天'
        f' · 量縮 {"是" if c["volume_declining_streak"] else ("否" if c["volume_declining_streak"] is False else "─")}'
        f' · 起漲量能確認 {"是" if c["breakout_volume_confirmed"] else ("否" if c["breakout_volume_confirmed"] is False else "─")}</div></div>'
        for c in streak_cards
    )
    return f'<div class="section-head"><h2>連續收近漲停</h2></div><div class="streak-grid">{cards}</div>'


def generate(
    trade_date: date,
    market_permission_data: dict,
    sector_priority: list,
    decision_table: list,
    risk_zone: dict,
    streak_cards: list,
    index_date: str = None,
    price_date: str = None,
    chips_date: str = None,
    output_path: str = "docs/momentum.html",
) -> bool:
    """
    產生 docs/momentum.html。decision_table 為空時不寫檔、回傳 False（比照
    chips_generator.py::generate() 既有慣例，代表本次每日流程 momentum 相關資料源失敗）。
    """
    if not decision_table:
        return False

    date_str = trade_date.strftime("%Y-%m-%d")
    permission = market_permission_data.get("permission", "unknown")
    tier_text = _esc(market_permission_data.get("tier_text", ""))
    divergence_text = _esc(market_permission_data.get("divergence_text", ""))
    advice_text = _esc(market_permission_data.get("advice_text", ""))

    freshness_bits = []
    if index_date:
        freshness_bits.append(f"指數 {index_date}")
    if price_date:
        freshness_bits.append(f"個股行情 {price_date}")
    if chips_date:
        freshness_bits.append(f"籌碼 {chips_date}")
    freshness_text = "　·　".join(freshness_bits) if freshness_bits else date_str

    risk_zone_html = _risk_zone_html(risk_zone) if permission == "defensive" else ""

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>逆轟動能策略 {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip-link" href="#main-content">跳到主要內容</a>
<header class="topbar">
  <h1>逆轟動能策略</h1>
  <span class="sub">{freshness_text}</span>
  <nav class="nav-links" aria-label="主要功能">
    <a class="nav-link" href="index.html">族群績效</a>
    <a class="nav-link" href="chips.html">籌碼分析</a>
    <a class="nav-link" href="patterns.html">形態掃描</a>
    <a class="nav-link active" href="momentum.html" aria-current="page">逆轟策略</a>
  </nav>
</header>
<div class="notice">本頁為全市場動能掃描與決策支援，不是自動交易或個人化投資建議。所有分數與門檻標記為實驗性，尚未回測校準。</div>
<main id="main-content">
<div class="permission-banner" data-permission="{permission}">
  <h2>市場操作許可：{tier_text}</h2>
  {f'<p>{divergence_text}</p>' if divergence_text else ''}
  {f'<p>{advice_text}</p>' if advice_text else ''}
</div>
{_sector_priority_html(sector_priority)}
<div class="section-head"><h2>個股決策主表</h2></div>
<div class="overflow-wrap">
<table class="decision-table">
<thead><tr><th>股票</th><th>技術狀態</th><th>族群內RS（信心）</th><th>今日抗跌差</th><th>最終標籤</th><th>證據</th></tr></thead>
<tbody>{_decision_table_html(decision_table)}</tbody>
</table>
</div>
{risk_zone_html}
{_streak_cards_html(streak_cards)}
</main>
</body></html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return True
```

- [ ] **Step 4: 執行確認通過**

Run: `python -m pytest tests/test_momentum_generator.py -q`
Expected: PASS（38 passed）

- [ ] **Step 5: Commit**

```bash
git add export/momentum_generator.py tests/test_momentum_generator.py
git commit -m "feat(export): momentum_generator generate()產生docs/momentum.html(禁用文案回歸測試)"
```

---

### Task 6：`main.py` 每日流程掛接 + nav 互連 + `_push_html` 納入 `docs/momentum.html`

**Files:**
- Modify: `main.py`（`run()` 函式，加在既有 `generate_patterns_html` 呼叫之後、`_push_html(trade_date)` 之前；`_push_html()` 函式本體）
- Modify: `export/html_generator.py`、`export/chips_generator.py`、`export/patterns_generator.py`（各自 nav 區塊新增一個連結，3 處皆為單行新增）

**Interfaces:**
- 無新函式，純接線：呼叫 `scan_momentum_health`/`scan_bullish_alignment_new_high`/
  `scan_consecutive_limit_up`/`calc_meta_observation_scores` 各一次，組出 Task 2-5 函式需要的
  輸入，呼叫 `momentum_generator.generate()`，並把 Task 1 的 `observation_scores` 一併傳給
  `generate_html()`。

- [ ] **Step 1: 為 3 個既有 generator 的 nav 加上「逆轟策略」連結**

`export/html_generator.py` 第 1366-1369 行，原本：

```python
    <div class="nav-links">
      <a class="nav-link active" href="index.html">族群績效</a>
      <a class="nav-link" href="chips.html">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
```

改成：

```python
    <div class="nav-links">
      <a class="nav-link active" href="index.html">族群績效</a>
      <a class="nav-link" href="chips.html">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
      <a class="nav-link" href="momentum.html">逆轟策略</a>
```

`export/chips_generator.py` 第 1122-1126 行（`<nav class="nav-links" aria-label="主要功能">` 區塊），原本：

```python
    <nav class="nav-links" aria-label="主要功能">
      <a class="nav-link" href="index.html">族群績效</a>
      <a class="nav-link active" href="chips.html" aria-current="page">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
    </nav>
```

改成：

```python
    <nav class="nav-links" aria-label="主要功能">
      <a class="nav-link" href="index.html">族群績效</a>
      <a class="nav-link active" href="chips.html" aria-current="page">籌碼分析</a>
      <a class="nav-link" href="patterns.html">形態掃描</a>
      <a class="nav-link" href="momentum.html">逆轟策略</a>
    </nav>
```

`export/patterns_generator.py` 第 462-465 行，原本：

```python
<div class="nav-links">
  <a class="nav-link" href="index.html">族群績效</a>
  <a class="nav-link" href="chips.html">籌碼分析</a>
  <a class="nav-link active" href="patterns.html">形態掃描</a>
```

改成：

```python
<div class="nav-links">
  <a class="nav-link" href="index.html">族群績效</a>
  <a class="nav-link" href="chips.html">籌碼分析</a>
  <a class="nav-link active" href="patterns.html">形態掃描</a>
  <a class="nav-link" href="momentum.html">逆轟策略</a>
```

- [ ] **Step 2: `_push_html()` 納入 `docs/momentum.html`**

`main.py` 第 239-245 行，原本：

```python
def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        subprocess.run(["git", "add"] + files_to_add, check=True)
```

改成：

```python
def _push_html(trade_date: date) -> None:
    try:
        import os
        files_to_add = ["docs/index.html", "docs/chips.html"]
        if os.path.exists("docs/patterns.html"):
            files_to_add.append("docs/patterns.html")
        if os.path.exists("docs/momentum.html"):
            files_to_add.append("docs/momentum.html")
        subprocess.run(["git", "add"] + files_to_add, check=True)
```

- [ ] **Step 3: `main.py::run()` 掛接 momentum 資料流程**

在 `main.py` 頂部 import 區塊（`from export.chips_generator import generate as generate_chips_html`
之後）新增：

```python
from export.momentum_generator import (
    market_permission, classify_sector_state, build_sector_priority,
    build_decision_table, selloff_risk_zone, build_streak_cards,
    generate as generate_momentum_html,
)
from processors.observation_scores import calc_meta_observation_scores
from screener.signals import scan_momentum_health, scan_bullish_alignment_new_high, scan_consecutive_limit_up
```

找到 `generate_patterns_html(trade_date, pattern_results, "docs/patterns.html")` 那個 `try` 區塊
（約第 863-875 行）之後、`_push_html(trade_date)` 之前，新增：

```python
        try:
            # universe_df 必須含 exchange 欄位，否則 calc_meta_observation_scores() 內部
            # _calc_chips_factor() 會 KeyError（見 debug-tasks.md 2026-07-18 條目提醒）。
            obs_universe_df = pd.read_csv(
                UNIVERSE_PATH, dtype=str,
                usecols=["stock_id", "stock_name", "meta_sector", "exchange"],
            )
            observation_scores = calc_meta_observation_scores(obs_universe_df)
        except Exception as exc:
            logger.warning("觀察分計算失敗，index.html 排序退回avg_change_pct、momentum頁本次不產生: %s", exc)
            observation_scores = {}

        momentum_html_written = False
        if observation_scores:
            try:
                momentum_results = scan_momentum_health(trade_date.isoformat())
                bullish_results = scan_bullish_alignment_new_high(trade_date.isoformat())
                limit_up_results = scan_consecutive_limit_up(trade_date.isoformat())

                permission_data = market_permission(
                    market_regime or {},
                    index_date=market_regime.get("taiex_date") if market_regime else None,
                    price_date=trade_date.isoformat(),
                )
                sector_states = {
                    meta_name: classify_sector_state(data)
                    for meta_name, data in observation_scores.items()
                }
                sector_priority = build_sector_priority(observation_scores, top_n=5)
                decision_table = build_decision_table(
                    momentum_results, bullish_results, permission_data["permission"], sector_states,
                )
                risk_zone = (
                    selloff_risk_zone(momentum_results)
                    if permission_data["permission"] == "defensive" else {}
                )
                streak_cards = build_streak_cards(limit_up_results)

                momentum_html_written = generate_momentum_html(
                    trade_date, permission_data, sector_priority, decision_table,
                    risk_zone, streak_cards,
                    index_date=market_regime.get("taiex_date") if market_regime else None,
                    price_date=trade_date.isoformat(),
                    chips_date=trade_date.isoformat(),
                )
            except Exception as exc:
                logger.warning("逆轟策略頁產生失敗: %s", exc)

        if momentum_html_written:
            logger.info("HTML generated → docs/momentum.html")
```

把 `generate_html(...)` 呼叫（約第 720-732 行）加上 `observation_scores` 參數：

```python
        generate_html(trade_date, pd.DataFrame(perf) if perf else pd.DataFrame(),
                      sectors_df=sectors_df,
                      prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                      chips_df=chips_df,
                      meta_perf=meta_perf,
                      universe_df=universe_df,
                      cum_data=cum_data,
                      meta_signals=meta_signals,
                      meta_chips=meta_chips,
                      stock_sparklines=stock_sparklines,
                      vol_turnover=vol_signals,
                      rolling_returns=rolling_returns,
                      market_regime=market_regime,
                      observation_scores=observation_scores)
```

⚠️ 這行改動需要把「產生 observation_scores」的程式碼區塊移到 `generate_html(...)` 呼叫**之前**
（目前草稿把它寫在 `generate_patterns_html` 之後，需要在實作時往前搬到 `generate_html(...)` 呼叫
前，讓同一個 `observation_scores` 變數能同時餵給 `generate_html()` 與 momentum 區塊，避免算兩次
——`calc_meta_observation_scores()` 開一條 DuckDB 連線查 3 張表，重複呼叫是不必要的效能浪費）。

- [ ] **Step 4: 手動驗證（無自動化測試，main.py 本身無單元測試覆蓋既有慣例）**

Run: `python -m pytest tests/ -q`
Expected: 全部既有測試維持通過（這一步只改 wiring，不改任何函式邏輯，不應該有測試壞掉）。

實際資料驗證交給 Debugger（比照 CLAUDE.md 既有分工，Developer 不自己跑 `python main.py`）。

- [ ] **Step 5: Commit**

```bash
git add main.py export/html_generator.py export/chips_generator.py export/patterns_generator.py
git commit -m "feat(main): 掛接逆轟策略v2每日流程(observation_scores/momentum_generator/nav互連/push清單)"
```

---

## Self-Review（對照 spec 逐項檢查）

- **四層決策模型**（spec §2）：Task 2 覆蓋第一層（`market_permission`）+ 第二層（`build_sector_priority`/
  `classify_sector_state`）；Task 3 覆蓋第三層（既有 `strength_tier`，本計畫不重新判斷）+ 第四層
  （`determine_final_label`），四層分開保存、沒有把單一分數當最終動作。
- **非命令式標籤**（spec §2.4）：`determine_final_label()` 只回傳 spec 定義的 6 個標籤；Task 5
  `BANNED_PHRASES` 回歸測試覆蓋 §4.2 全部 6 個禁用字樣。
- **daily_excess_pct vs rs_market_score 不可混用**（spec §3.1）：`selloff_risk_zone()` 明確用
  `daily_excess_pct`，Task 4 測試 `test_selloff_risk_zone_uses_daily_excess_pct_not_rs_market_score`
  直接驗證（這是舊 plan 犯過的錯，這次特別針對這點寫回歸測試）。
- **RS樣本信心**（spec §3.2）：`rs_sample_confidence()` 三級門檻對應，`determine_final_label()`
  的進場閘門吃這個信心分級，`<5` 時不能升級成進場候選（`test_determine_final_label_blocked_by_low_rs_confidence`）。
- **進場閘門六條件**（spec §3.4）：`determine_final_label()` 的 `entry_gate` 逐項對應 market_permission／
  sector_state／strength_tier／entry_confirmed／B3清單／volume_confirmed／RS信心，Task 3 測試逐項
  覆蓋阻擋情境。
- **連續近漲停顯示名稱**（spec §3.5）：`build_streak_cards()` docstring 與頁面文案固定用「連續收近
  漲停」，不稱「鎖死」。
- **跌停處理**（spec §3.6）：`market_permission`/`determine_final_label`/`selloff_risk_zone` 皆只
  產生「跌停風險」標籤與非命令提示文字，`_risk_zone_html()` 文案明確聲明「不代表放空或出場委託指令」
  （避免踩到自己的禁用文案回歸測試——原草稿在這裡的免責文案字面上包含「反手放空」子字串，已修正）。
- **資料日期不一致 → unknown**（spec §2.1/§6）：`market_permission()` 的日期比對邏輯 +
  `test_market_permission_unknown_when_dates_mismatch`；main.py 傳入 `taiex_date`/`trade_date`
  兩個實際日期，不猜測。
- **首頁與逆轟頁共用觀察分**（spec §2.2/§6）：Task 1 讓 `index.html` 消費
  `calc_meta_observation_scores()`；Task 2/6 讓 momentum 頁也消費同一份輸出，同一次 main.py 呼叫
  只算一次（Task 6 Step 3 註記說明）。
- **禁用文案全文掃描**（spec §4.2）：Task 5 `BANNED_PHRASES` 常數 + 回歸測試。
- **`universe_df` 需要 `exchange` 欄位**（debug-tasks.md Plan 3 提醒）：Task 6 Step 3
  `obs_universe_df` 明確 `usecols` 包含 `exchange`。

## No Placeholder 掃描

六個 Task 的程式碼區塊皆為可直接貼上執行的完整程式碼，測試斷言皆為具體值比對（例如
`assert result["sectorB"]["rs_raw"] == 4.11` 風格的具體數值/字串比對），Task 6 的 wiring 因為要
插入既有 940 行的 `main.py`，用「找到 XX 行，原本 YY，改成 ZZ」的精確 diff 描述法，不是空泛敘述。

## Type Consistency 掃描

- Task 2 定義的 `rs_sample_confidence()`/`market_permission()`/`classify_sector_state()`/
  `build_sector_priority()` 在 Task 3/6 的呼叫處逐字沿用相同函式名稱與回傳鍵名
  （`permission`/`sector_state`/`rank` 等）。
- Task 3 `determine_final_label()`/`build_decision_table()` 定義的欄位名稱
  （`rs_confidence`/`final_label`/`entry_evidence`/`exit_evidence`/`ma`）在 Task 5 `generate()`
  的 render 函式（`_decision_table_html()`）逐字對應使用。
- Task 4 `selloff_risk_zone()` 回傳鍵 `resilient`/`limit_down` 與 Task 5 `_risk_zone_html()`
  讀取鍵一致。
- Task 6 呼叫 `generate_momentum_html()`（即 momentum_generator.py 的 `generate`）位置參數順序
  跟 Task 5 定義的簽章（`trade_date, market_permission_data, sector_priority, decision_table,
  risk_zone, streak_cards`）逐一對應。

## Out of scope（本次不做，spec §7/§8 已列，或 spec 本文明講可延後）

- `screener/signals.py::scan_limit_up_unlocked()`（spec §3.5b 漲停打開階段性解讀，spec 明講不
  阻擋這次落地）。
- spec §2.4.1 紫圈／橘圈視覺徽章（spec 明講 writing-plans 階段可自行決定不採用）。
- 回測驗證 5 因子權重、進場閘門六條件、市場許可分級門檻是否有效（spec §5 獨立任務）。
- 個人持股成本、倉位、損益追蹤、自動下單（spec §8）。
- 視覺精修（配色/排版的第二輪細節打磨）：這次 Task 5 的 CSS 是功能完整、可存取（`<details>`/
  `aria-current`/`focus-visible`/tabular-nums）的實用版本，不是比照舊 v1 mockup 5 輪視覺定案的
  精緻度。如果 Cody 之後想再打磨視覺，屬於獨立的 `ui-ux-pro-max` skill 任務，不阻擋這次功能落地。
