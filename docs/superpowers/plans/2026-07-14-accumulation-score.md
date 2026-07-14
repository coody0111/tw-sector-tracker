# 進貨分（Accumulation Score）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一個 per-stock 純函式 `calc_accumulation_score()`，把外資/投信連買日數、大戶持股連增週數與張數變化、近期股價報酬，綜合成單一 0-100「進貨分」+ 狀態旗標（`price_confirmed`/`weakening`/`label`），供未來消費端（個股卡片、籌碼排行）使用。

**Architecture:** 純函式，位置 `screener/patterns.py`（跟既有 `calc_composite_score` 同檔、同「純函式吃值回分」慣例）。不連 DB、不依賴 UI，輸入純量、輸出 dict，方便單元測試。本 plan **只做這個函式本身**——不整合進 `export/html_generator.py`、`export/chips_generator.py` 或任何排序/渲染邏輯（spec 明確排除）。

**Tech Stack:** Python, pandas（`pd.isna` 缺值檢查）, pytest。

---

## Spec 對照（依據 `docs/superpowers/specs/2026-07-14-accumulation-score-design.md`）

- 公式：`foreign_pts = min(max(foreign_streak, 0) * 8, 40)`、`trust_pts = min(max(trust_streak, 0) * 6, 30)`、`holder_pts = min(max(sh_streak, 0) * 7, 20)`，三者相加 `accumulation`（0~90）。
- 價格閘門：`price_confirmed = (recent_return is not None) and (recent_return > 0)`，`gate = 1.0 if price_confirmed else 0.5`。
- 最終分數：`score = round(min(accumulation, 100) * gate)`（0~100）。
- `weakening`：外資與投信 streak 皆 ≤ 0，**或** 大戶當週由增轉減（`holder_net_lots is not None and holder_net_lots < 0`）。weakening 為真時 `holder_pts` 記 0（覆蓋掉原本用 `sh_streak` 算出的值）。
- `label` 導出優先序：`weakening` 真 → `'轉弱'`；否則 `price_confirmed` 假 → `'整理'`；否則 `score >= 40` → `'進貨'`；否則 → `'整理'`。
- 缺值防呆：`recent_return` 為 `None` → 視為未 confirm（`gate=0.5`，不當作 confirmed）。`holder_net_lots` 為 `None` → `holder_pts` 仍走 `sh_streak` 計算（不因此歸零），但 weakening 判斷裡「大戶由增轉減」那一條件視為不成立（無法判斷，不觸發）。`sh_streak` 為 `None` → `holder_pts=0`（`max(None, 0)` 會炸，需要先擋 `None`）。

---

## Task 1: `calc_accumulation_score()` 基本公式（進貨分數，不含 weakening/label）

**Files:**
- Modify: `screener/patterns.py`（緊接在 `calc_composite_score` 函式之後，約第 1361 行之後新增）
- Test: `tests/test_patterns.py`（緊接在既有 `calc_composite_score` 測試之後，約第 461 行之後新增）

- [ ] **Step 1: 寫失敗測試——只算進貨、連賣不倒扣**

在 `tests/test_patterns.py` 頂部 `from screener.patterns import calc_composite_score, scan_and_track` 那行下方新增 import，並在該檔案 `test_calc_composite_score_margin_divergence_overrides_alert_pct_branch` 測試之後加入：

```python
from screener.patterns import calc_accumulation_score


def _base_acc_kwargs(**overrides):
    kwargs = dict(
        foreign_streak=0, trust_streak=0, sh_streak=0,
        holder_net_lots=0, recent_return=1.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_calc_accumulation_score_only_counts_buying_not_selling():
    """只算進貨、不猜出貨：連賣（streak<0）不倒扣分，foreign_pts 應為 0（不是負數）。"""
    selling = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=-5))
    baseline = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=0))
    assert selling["score"] == baseline["score"], "連賣(-5)跟不買(0)的外資貢獻應該一樣，都是 0 分，不倒扣"
    assert selling["foreign_buy_days"] == 0
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_patterns.py::test_calc_accumulation_score_only_counts_buying_not_selling -v`
Expected: FAIL，錯誤訊息 `ImportError: cannot import name 'calc_accumulation_score'`

- [ ] **Step 3: 寫最小實作**

在 `screener/patterns.py` 的 `calc_composite_score` 函式結尾（`return max(0, min(100, score))` 那行）之後新增：

```python
def calc_accumulation_score(
    foreign_streak: int,
    trust_streak: int,
    sh_streak: int | None,
    holder_net_lots: int | None,
    recent_return: float | None,
) -> dict:
    """
    進貨分（法人進貨強度綜合分）0-100，只算進貨、不猜出貨（連賣不倒扣分）。
    價格閘門：法人在買但價格沒動 = 外強中乾，分數打對折（籌碼是配角，見設計 spec
    docs/superpowers/specs/2026-07-14-accumulation-score-design.md）。

    純函式：不連 DB、不依賴 UI，呼叫端已從 DB 撈好純量餵進來。

    回傳 dict：
        score            進貨分 0-100
        foreign_buy_days 外資連買日數（max(foreign_streak, 0)）
        trust_buy_days   投信連買日數（max(trust_streak, 0)）
        holder_net_lots  大戶當週淨增減張數（可負，原樣回傳供消費端顯示）
        price_confirmed  bool，價格是否 confirm 進貨
        weakening        bool，進貨轉弱訊號
        label            '進貨'/'整理'/'轉弱'，導出規則見 _accumulation_label()
    """
    foreign_buy_days = max(foreign_streak, 0)
    trust_buy_days = max(trust_streak, 0)
    sh_buy_weeks = max(sh_streak, 0) if sh_streak is not None else 0

    foreign_pts = min(foreign_buy_days * 8, 40)
    trust_pts = min(trust_buy_days * 6, 30)
    holder_pts = min(sh_buy_weeks * 7, 20)

    weakening = (foreign_streak <= 0 and trust_streak <= 0) or (
        holder_net_lots is not None and holder_net_lots < 0
    )
    if weakening:
        holder_pts = 0

    accumulation = foreign_pts + trust_pts + holder_pts

    price_confirmed = recent_return is not None and recent_return > 0
    gate = 1.0 if price_confirmed else 0.5

    score = round(min(accumulation, 100) * gate)

    return {
        "score": score,
        "foreign_buy_days": foreign_buy_days,
        "trust_buy_days": trust_buy_days,
        "holder_net_lots": holder_net_lots,
        "price_confirmed": price_confirmed,
        "weakening": weakening,
        "label": _accumulation_label(score, price_confirmed, weakening),
    }
```

先加一個暫時的 stub（Task 3 才會實作真正的 `_accumulation_label`）讓這個測試先能跑：

```python
def _accumulation_label(score: int, price_confirmed: bool, weakening: bool) -> str:
    return "整理"  # 暫時 stub，Task 3 補完整導出規則
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_patterns.py::test_calc_accumulation_score_only_counts_buying_not_selling -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "feat: calc_accumulation_score 基本公式——只算進貨、連賣不倒扣"
```

---

## Task 2: 價格閘門 + 封頂

**Files:**
- Modify: `screener/patterns.py`（無需新增函式，Task 1 的實作已含邏輯，這裡是補測試驗證）
- Test: `tests/test_patterns.py`

- [ ] **Step 1: 寫失敗測試——價格閘門**

在 `tests/test_patterns.py` 緊接 Task 1 的測試之後新增：

```python
def test_calc_accumulation_score_price_gate_halves_score_when_not_confirmed():
    """同樣的進貨強度，recent_return<=0（未 confirm）分數應是 confirm 時的一半，
    price_confirmed 旗標要對應正確。"""
    confirmed = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=1.0))
    not_confirmed = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=-1.0))

    assert confirmed["price_confirmed"] is True
    assert not_confirmed["price_confirmed"] is False
    assert not_confirmed["score"] == round(confirmed["score"] / 2)


def test_calc_accumulation_score_recent_return_none_is_not_confirmed():
    """recent_return 為 None（新股/資料不足）要視為未 confirm，不是當作 confirmed。"""
    result = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=None))
    assert result["price_confirmed"] is False


def test_calc_accumulation_score_caps_foreign_trust_holder_points():
    """封頂：foreign_streak=10 時 foreign_pts 應封頂在 40（不是 10*8=80）。
    用 foreign_streak=5(40分,封頂) vs foreign_streak=10(仍40分,封頂) 比較分數相同來驗證。"""
    at_cap = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=5, recent_return=1.0))
    over_cap = calc_accumulation_score(**_base_acc_kwargs(foreign_streak=10, recent_return=1.0))
    assert at_cap["score"] == over_cap["score"], "foreign_streak 超過封頂對應的日數，分數不該再增加"
    assert over_cap["foreign_buy_days"] == 10, "foreign_buy_days 本身如實回傳，只有算分時封頂"
```

- [ ] **Step 2: 執行測試確認通過**

Run: `pytest tests/test_patterns.py -k "price_gate or recent_return_none or caps_foreign" -v`
Expected: PASS（Task 1 的實作已經涵蓋這些邏輯，這裡純粹補測試驗證正確性）

若有任何一個 FAIL，回去檢查 Task 1 `calc_accumulation_score` 的 `min(..., 40)` / `min(..., 30)` / `min(..., 20)` 封頂數字跟 `gate` 邏輯是否跟本 plan 開頭「Spec 對照」章節一致。

- [ ] **Step 3: Commit**

```bash
git add tests/test_patterns.py
git commit -m "test: calc_accumulation_score 價格閘門與封頂驗證"
```

---

## Task 3: `weakening` 旗標 + `label` 導出規則

**Files:**
- Modify: `screener/patterns.py:_accumulation_label`（把 Task 1 的 stub 換成真正實作）
- Test: `tests/test_patterns.py`

- [ ] **Step 1: 寫失敗測試——weakening 旗標**

```python
def test_calc_accumulation_score_weakening_when_both_streaks_non_positive():
    """外資與投信 streak 皆 <= 0 時應標記 weakening=True，holder_pts 也應被歸零
    （即使 sh_streak 本身是正數）。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=0, trust_streak=0, sh_streak=3, holder_net_lots=100, recent_return=1.0,
    ))
    assert result["weakening"] is True


def test_calc_accumulation_score_weakening_when_holder_net_lots_turns_negative():
    """大戶當週由增轉減（holder_net_lots < 0）應標記 weakening=True，
    即使外資/投信仍在連買。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=3, sh_streak=2, holder_net_lots=-500, recent_return=1.0,
    ))
    assert result["weakening"] is True


def test_calc_accumulation_score_not_weakening_when_any_source_buying_and_holder_not_negative():
    """外資或投信有連買、且大戶張數沒有轉負，不該標記 weakening。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=0, sh_streak=2, holder_net_lots=100, recent_return=1.0,
    ))
    assert result["weakening"] is False


def test_calc_accumulation_score_label_progression():
    """label 導出優先序：weakening 最優先覆蓋一切；其次未 confirm 是「整理」；
    否則依 score>=40 分「進貨」或「整理」。"""
    weakening_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=0, trust_streak=0, sh_streak=0, holder_net_lots=0, recent_return=1.0,
    ))
    assert weakening_case["label"] == "轉弱"

    not_confirmed_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=5, trust_streak=5, sh_streak=2, holder_net_lots=100, recent_return=-1.0,
    ))
    assert not_confirmed_case["weakening"] is False
    assert not_confirmed_case["label"] == "整理"

    strong_buy_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=5, trust_streak=5, sh_streak=2, holder_net_lots=100, recent_return=1.0,
    ))
    assert strong_buy_case["score"] >= 40
    assert strong_buy_case["label"] == "進貨"

    weak_buy_case = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=1, trust_streak=0, sh_streak=0, holder_net_lots=100, recent_return=1.0,
    ))
    assert weak_buy_case["weakening"] is False
    assert weak_buy_case["score"] < 40
    assert weak_buy_case["label"] == "整理"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_patterns.py -k "weakening or label_progression" -v`
Expected: `test_calc_accumulation_score_label_progression` 的部分斷言 FAIL（stub `_accumulation_label` 永遠回傳 `"整理"`，`strong_buy_case["label"] == "進貨"` 那條會失敗）；weakening 相關測試應該已經 PASS（Task 1 的公式已經算對 weakening，只是 label 導出還是 stub）。

- [ ] **Step 3: 實作 `_accumulation_label`**

把 Task 1 加的 stub：

```python
def _accumulation_label(score: int, price_confirmed: bool, weakening: bool) -> str:
    return "整理"  # 暫時 stub，Task 3 補完整導出規則
```

換成：

```python
def _accumulation_label(score: int, price_confirmed: bool, weakening: bool) -> str:
    """進貨分 label 導出，優先序（見設計 spec 第 92-96 行）：
    1. weakening 為真 → '轉弱'
    2. 否則 price_confirmed 為假 → '整理'（有進貨動作但價格沒 confirm，可能外強中乾）
    3. 否則 score >= 40 → '進貨'
    4. 否則 → '整理'
    """
    if weakening:
        return "轉弱"
    if not price_confirmed:
        return "整理"
    if score >= 40:
        return "進貨"
    return "整理"
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_patterns.py -k "weakening or label_progression" -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "feat: calc_accumulation_score weakening 旗標與 label 導出規則"
```

---

## Task 4: 缺值防呆（None/NaN 不 crash）

**Files:**
- Modify: `screener/patterns.py:calc_accumulation_score`
- Test: `tests/test_patterns.py`

**背景**：`sh_streak`/`holder_net_lots`/`recent_return` 從真實 DB 撈出時可能是 Python `None`，也可能是 DuckDB NULL 經 pandas 讀回變成 `float('nan')`（這是本專案已知的老雷，`scrapers/shareholder.py` 的 `recompute_all_history` 才剛修過同類 bug）。Task 1-3 的實作目前只判斷 `is None`，`max(sh_streak, 0)` 遇到 `nan` 不會拋例外但會算出錯誤結果（`nan` 跟任何數比較都是 `False`，`max(nan, 0)` 視 Python 版本行為不一致，必須明確擋掉）。

- [ ] **Step 1: 寫失敗測試**

```python
import math


def test_calc_accumulation_score_handles_none_sh_streak_without_crash():
    """sh_streak 為 None（新股，集保資料還沒有這檔）不該 crash，holder_pts 當 0 貢獻。"""
    result = calc_accumulation_score(**_base_acc_kwargs(sh_streak=None, recent_return=1.0))
    assert result["score"] is not None
    assert not (isinstance(result["score"], float) and math.isnan(result["score"]))


def test_calc_accumulation_score_handles_nan_sh_streak_without_crash():
    """sh_streak 為 NaN（DuckDB NULL 經 pandas 讀回）不該 crash，等同 None 處理。"""
    result = calc_accumulation_score(**_base_acc_kwargs(sh_streak=float("nan"), recent_return=1.0))
    assert result["score"] is not None
    assert not (isinstance(result["score"], float) and math.isnan(result["score"]))


def test_calc_accumulation_score_handles_none_holder_net_lots():
    """holder_net_lots 為 None（還沒有兩週大戶資料可比較）：holder_pts 仍走 sh_streak
    正常計算，但 weakening 的『大戶由增轉減』判斷略過（不因為 None 就觸發或跳過整體 weakening，
    只是那個 OR 分支不成立）。"""
    result = calc_accumulation_score(**_base_acc_kwargs(
        foreign_streak=3, trust_streak=3, sh_streak=2, holder_net_lots=None, recent_return=1.0,
    ))
    assert result["weakening"] is False
    assert result["holder_net_lots"] is None
    assert result["score"] > 0, "holder_net_lots=None 不該讓 holder_pts 被歸零，sh_streak 仍要計分"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_patterns.py -k "handles_none or handles_nan" -v`
Expected: `test_calc_accumulation_score_handles_nan_sh_streak_without_crash` 可能 PASS 或產生非預期結果（`max(nan, 0)` 在 Python 是 `nan`，`min(nan*7, 20)` 也是 `nan`，最終 `score` 會是 NaN 而不是報錯——測試斷言 `not isinstance(...isnan)` 應該抓到這個問題並 FAIL）。

- [ ] **Step 3: 補上 NaN 防呆**

修改 `screener/patterns.py` 的 `calc_accumulation_score`，在函式開頭新增 `pd.isna` 檢查（`pd` 已經是模組層級 import，見檔案第 6 行）：

```python
def calc_accumulation_score(
    foreign_streak: int,
    trust_streak: int,
    sh_streak: int | None,
    holder_net_lots: int | None,
    recent_return: float | None,
) -> dict:
    """
    進貨分（法人進貨強度綜合分）0-100，只算進貨、不猜出貨（連賣不倒扣分）。
    價格閘門：法人在買但價格沒動 = 外強中乾，分數打對折（籌碼是配角，見設計 spec
    docs/superpowers/specs/2026-07-14-accumulation-score-design.md）。

    純函式：不連 DB、不依賴 UI，呼叫端已從 DB 撈好純量餵進來。

    NaN guard：sh_streak/holder_net_lots/recent_return 從 DB 撈出時可能是 Python None，
    也可能是 DuckDB NULL 經 pandas 讀回變成 float('nan')（本專案已知模式，見
    scrapers/shareholder.py 的 pd.isna 防呆）。兩者都視為缺值處理，不能讓 nan 混進
    max()/min() 算出 nan 分數卻不報錯。

    回傳 dict：
        score            進貨分 0-100
        foreign_buy_days 外資連買日數（max(foreign_streak, 0)）
        trust_buy_days   投信連買日數（max(trust_streak, 0)）
        holder_net_lots  大戶當週淨增減張數（可負，原樣回傳供消費端顯示）
        price_confirmed  bool，價格是否 confirm 進貨
        weakening        bool，進貨轉弱訊號
        label            '進貨'/'整理'/'轉弱'，導出規則見 _accumulation_label()
    """
    if sh_streak is None or pd.isna(sh_streak):
        sh_streak = None
    if holder_net_lots is None or pd.isna(holder_net_lots):
        holder_net_lots = None
    if recent_return is None or pd.isna(recent_return):
        recent_return = None

    foreign_buy_days = max(foreign_streak, 0)
    trust_buy_days = max(trust_streak, 0)
    sh_buy_weeks = max(sh_streak, 0) if sh_streak is not None else 0

    foreign_pts = min(foreign_buy_days * 8, 40)
    trust_pts = min(trust_buy_days * 6, 30)
    holder_pts = min(sh_buy_weeks * 7, 20)

    weakening = (foreign_streak <= 0 and trust_streak <= 0) or (
        holder_net_lots is not None and holder_net_lots < 0
    )
    if weakening:
        holder_pts = 0

    accumulation = foreign_pts + trust_pts + holder_pts

    price_confirmed = recent_return is not None and recent_return > 0
    gate = 1.0 if price_confirmed else 0.5

    score = round(min(accumulation, 100) * gate)

    return {
        "score": score,
        "foreign_buy_days": foreign_buy_days,
        "trust_buy_days": trust_buy_days,
        "holder_net_lots": holder_net_lots,
        "price_confirmed": price_confirmed,
        "weakening": weakening,
        "label": _accumulation_label(score, price_confirmed, weakening),
    }
```

（這裡整段覆蓋 Task 1/3 的實作，把 NaN guard 加在函式最前面，其餘邏輯不變。）

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_patterns.py -k "accumulation" -v`
Expected: 全部 PASS（包含 Task 1-4 累計的所有 `calc_accumulation_score` 測試）

- [ ] **Step 5: Commit**

```bash
git add screener/patterns.py tests/test_patterns.py
git commit -m "fix: calc_accumulation_score 加 NaN guard，防止 DuckDB NULL 讀回混入計算"
```

---

## Task 5: 全專案回歸測試 + debug-tasks.md 記錄

**Files:**
- Modify: `debug-tasks.md`（頂部新增進度記錄，照專案既有慣例）

- [ ] **Step 1: 跑全專案測試**

Run: `pytest -q`
Expected: 全部 PASS（現有 204 筆 + 這次新增約 13 筆 `calc_accumulation_score` 測試）

- [ ] **Step 2: 在 `debug-tasks.md` 頂部新增進度記錄**

在檔案最上方（第一行之前）插入：

```markdown
## [DATE] ✅ 進貨分 calc_accumulation_score() 完成（spec: docs/superpowers/specs/2026-07-14-accumulation-score-design.md）

新增純函式 `screener/patterns.py::calc_accumulation_score()`，把外資/投信連買日數、
大戶持股連增週數與當週張數變化、近5日股價報酬，綜合成 0-100 進貨分 + 狀態旗標
（`price_confirmed`/`weakening`/`label`）。只算進貨不倒扣連賣分數、價格閘門讓
「法人買但價格沒動」的分數打對折——依據逆轟動能派筆記「籌碼是配角、只給50分」的
設計原則。

### 範圍
- 只做這個純函式本身，**不整合進任何消費端**（`export/html_generator.py`、
  `export/chips_generator.py` 都未修改）——spec 明確排除 UI/視覺整合，那是後續
  `ui-ux-pro-max` 的另一關。
- 純函式不連 DB、不依賴任何全域狀態，單元測試用合成值即可涵蓋所有分支。

### 測試
`tests/test_patterns.py` 新增約 13 個測試，涵蓋：只算進貨不倒扣、價格閘門（含
`recent_return=None` 視為未 confirm）、三個來源各自封頂、weakening 兩種觸發條件
（外資投信皆非正 / 大戶轉負）、label 四種導出情境、`sh_streak`/`holder_net_lots` 為
None 或 NaN 不 crash。全專案 `pytest -q`：[填入實際數字] passed。

### 請 Debugger 驗證
- [ ] `calc_accumulation_score()` 公式對照 spec（`docs/superpowers/specs/2026-07-14-accumulation-score-design.md` 第 57-96 行）逐項核對，特別是封頂數字（40/30/20）跟 weakening 的兩個觸發條件
- [ ] NaN guard 邏輯正確（`pd.isna` 對 None 也會回 True，這裡刻意先判斷 `is None` 再判斷 `pd.isna` 是因為 `pd.isna(None)` 本身也是合法的，純粹是防禦性寫兩層判斷，確認沒有邏輯上的遺漏）
- [ ] 沒有影響其他既有的 `screener/patterns.py` 函式（`calc_composite_score`、`_calc_streak` 等），這次是純新增函式，不動既有程式碼

### 特別注意
- 這次**沒有消費端整合**，`calc_accumulation_score()` 目前沒有任何呼叫端在用它——這是刻意的（spec 範圍如此），之後要接進畫面時（個股卡片 payload、籌碼進貨排行）需要另開 plan，不在本次範圍。
- 公式裡的封頂數字（8/6/7 分、40/30/20 封頂、0.5 閘門）都是 spec 標注的「草案切點」，之後要用 `screener/backtest.py`（另一個尚未開工的 `2026-07-14-backtest-framework` plan）對真實歷史資料驗證校準，不是最終定論。

---
```

（`[DATE]` 換成實際執行日期，`[填入實際數字]` 換成 Step 1 實測的通過數。）

- [ ] **Step 3: Commit**

```bash
git add debug-tasks.md
git commit -m "docs(debug): 進貨分 calc_accumulation_score 完成，待 Debugger 驗證"
```

---

## Out of scope（本次不做，跟 spec 一致）

- 消費端整合（個股卡片 payload、籌碼進貨排行渲染/排序）——spec 明確排除，UI 無關。
- 族群強度、持股清單、Telegram 推播——spec 列為後續 follow-up，不在本次範圍。
- 回測校準（用 `backtest.py` 驗證封頂數字/閘門切點是否合理）——依賴另一個尚未動工的 `backtest-framework` plan，數字目前是「先落地、之後校準」的草案值。
- 不改任何抓取端程式碼，只消費 DB 裡已有的資料（純函式甚至不連 DB，呼叫端自己撈值餵進來）。
