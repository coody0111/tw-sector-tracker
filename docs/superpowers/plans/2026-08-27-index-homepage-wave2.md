# 首頁（index.html）第二波大改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply confidence-tiering (real numbers solid, unbacktested draft classifications dashed/muted) across `docs/index.html`, and restructure the page around a new merged "今日/本週異動" section that pulls in two individual-stock signals (`get_margin_divergence()`, `scan_consecutive_limit_up()`) never before shown on this page.

**Architecture:** Same as Wave 1 — all HTML/CSS/JS lives as an f-string template in `export/index_generator.py`; backend calculations live in `processors/performance.py`/`screener/signals.py`; `main.py` wires DB queries into `generate_index_html()`. This wave reuses two functions already used by `momentum.html`/`patterns.html` (see `docs/adr/0006-index-reuses-cross-page-signal-functions.md`) rather than recomputing anything.

**Tech Stack:** Python (pandas, duckdb), vanilla JS/CSS embedded in Python f-strings, pytest.

**Decisions this plan implements:** `CONTEXT.md` (詞彙), `docs/adr/0005-confidence-tiering-across-index-page.md`, `docs/adr/0006-index-reuses-cross-page-signal-functions.md`.

**Baseline:** `pytest -q` → 501 passed before this plan starts (Wave 1 + unrelated dip_buy/stealth_buy feature). Every task must keep the suite green with only new tests added.

---

### Task 1: `main.py` — fetch `scan_consecutive_limit_up()`, wire both new signals into `generate_index_html()`

**Files:**
- Modify: `main.py:769` (margin_div already computed here, just needs passing through)
- Modify: `main.py:840-861` (add limit_up fetch, add both to the `generate_index_html(...)` call)

- [ ] **Step 1: Add the `scan_consecutive_limit_up()` fetch**

In `main.py`, find (right before the `if universe_df is not None:` block that calls `generate_index_html`):

```python
        try:
            vol_turnover_signals = scan_volume_turnover(trade_date.isoformat()) if universe_df is not None else []
        except Exception as exc:
            logger.warning("巨量換手訊號計算失敗，index.html本次不顯示: %s", exc)
            vol_turnover_signals = []

        if universe_df is not None:
            generate_index_html(trade_date, meta_perf, universe_df,
```

Change to:

```python
        try:
            vol_turnover_signals = scan_volume_turnover(trade_date.isoformat()) if universe_df is not None else []
        except Exception as exc:
            logger.warning("巨量換手訊號計算失敗，index.html本次不顯示: %s", exc)
            vol_turnover_signals = []

        try:
            index_limit_up_results = scan_consecutive_limit_up(trade_date.isoformat()) if universe_df is not None else []
        except Exception as exc:
            logger.warning("連續漲停鎖死掃描失敗，index.html「今日/本週異動」本次不顯示這項: %s", exc)
            index_limit_up_results = []

        if universe_df is not None:
            generate_index_html(trade_date, meta_perf, universe_df,
```

Note: `scan_consecutive_limit_up` is already imported at the top of `main.py`
(`from screener.signals import scan_volume_turnover, scan_momentum_health, scan_bullish_alignment_new_high, scan_consecutive_limit_up`) — no new import needed. `margin_div` is already computed earlier at `main.py:769` (`margin_div = get_margin_divergence(universe_df) if universe_df is not None else {}`), reused as-is.

- [ ] **Step 2: Pass both into the `generate_index_html(...)` call**

Find:

```python
            generate_index_html(trade_date, meta_perf, universe_df,
                                 meta_signals=meta_signals,
                                 meta_chips=meta_chips,
                                 prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                                 heatgrid_windows=heatgrid_windows,
                                 stock_sparklines=stock_sparklines,
                                 rolling_returns=rolling_returns,
                                 chips_df=index_chips_df,
                                 cum_data=cum_data,
                                 market_regime=market_regime,
                                 vol_turnover_signals=vol_turnover_signals,
                                 rank_history=rank_history,
                                 total_shares_df=total_shares_df,
                                 avg20_map=avg20_map,
                                 shareholder_df=index_shareholder_df)
```

Change to:

```python
            generate_index_html(trade_date, meta_perf, universe_df,
                                 meta_signals=meta_signals,
                                 meta_chips=meta_chips,
                                 prices_df=prices_df if prices_df is not None else pd.DataFrame(),
                                 heatgrid_windows=heatgrid_windows,
                                 stock_sparklines=stock_sparklines,
                                 rolling_returns=rolling_returns,
                                 chips_df=index_chips_df,
                                 cum_data=cum_data,
                                 market_regime=market_regime,
                                 vol_turnover_signals=vol_turnover_signals,
                                 rank_history=rank_history,
                                 total_shares_df=total_shares_df,
                                 avg20_map=avg20_map,
                                 shareholder_df=index_shareholder_df,
                                 margin_divergence=margin_div,
                                 limit_up_results=index_limit_up_results)
```

(This will fail until Task 2 adds the two new parameters to `generate()` — that's expected and fine; Task 2 makes this call valid.)

- [ ] **Step 3: Sanity-check `main.py` still parses**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read())"`
Expected: no output, no exception (confirms valid Python syntax — this does NOT check that `generate()` accepts the new kwargs yet, that's Task 2's job; don't run `import main` yet since `generate_index_html`'s signature doesn't have these params until Task 2 lands, and `import main` only parses/binds at module level, not call time, so it will succeed either way — this step is just a syntax check).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(index): main.py接上連續漲停鎖死掃描+融資背離,傳給generate_index_html"
```

## Context

This is Task 1 of a 12-task plan (Wave 2 of the homepage redesign). Wave 1 (13 tasks, already merged) reordered the page and wired 4 new data fields. This wave adds confidence-tiering visuals plus 2 brand-new individual-stock signals borrowed from `momentum.html`'s scan functions (see `docs/adr/0006-index-reuses-cross-page-signal-functions.md`).

`margin_div` (the output of `get_margin_divergence(universe_df)`) is ALREADY computed at `main.py:769`, well before the `generate_index_html(...)` call — it's just never been passed to it. This task adds the ONE missing fetch (`scan_consecutive_limit_up`) and threads both through.

You are on branch `master` in the main working tree at `C:\Users\Cody\Desktop\tw-sector-tracker` — this project's convention (per CLAUDE.md) is direct commits to `master`.

**IMPORTANT — DO NOT sync any other git worktree.** Debug-worktree syncing is reserved for the final task of this plan. Do not `cd` into or touch `../tw-sector-tracker-debug`.

## Before You Begin

If the current `main.py` content around these line numbers differs meaningfully from what's shown (main.py changes over time), find the actual current location of the `vol_turnover_signals` fetch block and the `generate_index_html(...)` call and apply the equivalent edit there.

## Your Job

1. Add the `scan_consecutive_limit_up()` fetch block (matching the existing try/except/logger.warning style of its neighbors)
2. Add both new kwargs to the `generate_index_html(...)` call
3. Sanity-check syntax
4. Commit
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `main.py`. Don't touch `export/index_generator.py` in this task — that's Task 2.

## When You're in Over Your Head

STOP and escalate if `main.py`'s current structure around this area differs substantially from what's described, or if `margin_div`/`scan_consecutive_limit_up` aren't where this task expects.

## Before Reporting Back: Self-Review

- Does the new try/except block match the exact style of its neighbors (variable naming, log message tone)?
- Did you pass `margin_div` (the EXISTING variable, not create a new fetch for it)?
- Did you avoid touching anything else in `main.py`?

## Report Format

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented
- Syntax check result
- Files changed
- Commit SHA
- Self-review findings

---

### Task 2: `export/index_generator.py::generate()` — accept `margin_divergence`/`limit_up_results` params

**Files:**
- Modify: `export/index_generator.py:1198-1236` (`generate()` signature + docstring)
- Test: `tests/test_index_generator.py` (append a signature-acceptance test)

- [ ] **Step 1: Write the failing test**

```python
def test_generate_accepts_margin_divergence_and_limit_up_results_params(tmp_path):
    """generate()要能吃margin_divergence/limit_up_results兩個新參數，不crash——
    這一步只確認簽章接受，實際渲染邏輯是後面Task 8才做。"""
    output_path = tmp_path / "index.html"
    margin_divergence = {"bearish": [{"stock_id": "1101", "stock_name": "台泥", "meta_sector": "水泥",
                                       "margin_pct": 5.2, "price_pct": -3.1, "days": 10, "close": 30.5}],
                          "bullish": [], "days_used": 10}
    limit_up_results = [{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
                          "close": 1080.0, "change_pct": 9.9, "volume": 50000,
                          "limit_up_streak": 2, "volume_declining_streak": True,
                          "breakout_volume_confirmed": True}]

    generate(date(2026, 8, 27), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             margin_divergence=margin_divergence, limit_up_results=limit_up_results,
             output_path=str(output_path))

    assert output_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "accepts_margin_divergence_and_limit_up_results" -v`
Expected: FAIL with `TypeError: generate() got an unexpected keyword argument 'margin_divergence'`.

- [ ] **Step 3: Add the two parameters**

In `export/index_generator.py`, find the `generate()` signature:

```python
def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    cum_data: Optional[List[Dict[str, Any]]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    vol_turnover_signals: Optional[List[Dict[str, Any]]] = None,
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    shareholder_df: Optional[pd.DataFrame] = None,
    output_path: str = "docs/index.html",
) -> None:
```

Change to:

```python
def generate(
    trade_date: date,
    meta_perf: List[Dict[str, Any]],
    universe_df: pd.DataFrame,
    meta_signals: Dict[str, Dict[str, Any]],
    meta_chips: Dict[str, Dict[str, Any]],
    prices_df: pd.DataFrame,
    heatgrid_windows: Dict[str, Dict[str, Any]],
    stock_sparklines: Optional[Dict[str, dict]] = None,
    rolling_returns: Optional[Dict[str, dict]] = None,
    chips_df: Optional[pd.DataFrame] = None,
    cum_data: Optional[List[Dict[str, Any]]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    vol_turnover_signals: Optional[List[Dict[str, Any]]] = None,
    rank_history: Optional[Dict[str, Dict[str, Any]]] = None,
    total_shares_df: Optional[pd.DataFrame] = None,
    avg20_map: Optional[Dict[str, float]] = None,
    shareholder_df: Optional[pd.DataFrame] = None,
    margin_divergence: Optional[Dict[str, Any]] = None,
    limit_up_results: Optional[List[Dict[str, Any]]] = None,
    output_path: str = "docs/index.html",
) -> None:
```

Add docstring lines in the "有就顯示、沒有就不顯示" list (after the `shareholder_df` line):

```python
    - margin_divergence：get_margin_divergence() 輸出（{bearish, bullish, days_used}），
      個股融資餘額趨勢 vs 股價趨勢背離警示，「今日/本週異動」區塊今日層用。
    - limit_up_results：scan_consecutive_limit_up() 輸出(list)，連續鎖漲停個股，
      「今日/本週異動」區塊今日層用。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "accepts_margin_divergence_and_limit_up_results" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): generate()新增margin_divergence/limit_up_results參數"
```

## Context

Task 2 of 12. Task 1 (main.py wiring) is done. This task only adds the two parameters to `generate()`'s signature — no rendering logic yet (that's Tasks 4, 5, 8). This is deliberately a thin, isolated step so the plumbing lands independently of the rendering work.

You are on branch `master`. **DO NOT sync any other git worktree** — reserved for the final task.

## Before You Begin

If `generate()`'s current signature differs from what's shown, ask before proceeding.

## Your Job

Write the test, confirm it fails, add the two params + docstring lines, confirm it passes, commit.

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. Don't add any rendering logic that USES these new params yet — later tasks do that.

## When You're in Over Your Head

STOP and escalate if `generate()`'s signature has changed substantially from what's described.

## Before Reporting Back: Self-Review

- Are the two new params `Optional` with `None` default, consistent with every other optional param in this signature?
- Did you add them in the position shown (after `shareholder_df`, before `output_path`)?

## Report Format

Same format as Task 1.

---

### Task 3: `.badge-weak` CSS + apply confidence-tiering to heatgrid tier/temp badges

**Files:**
- Modify: `export/index_generator.py` `_CSS` block (new `.badge-weak` rule)
- Modify: `export/index_generator.py:1015-1035` (`_heatgrid_html` — tier_html/temp_html rendering)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_heatgrid_tier_and_temp_badges_use_confidence_tiering(tmp_path):
    """五級動能(tier)/溫度(temp)標籤是未回測草案分類(見docs/adr/0005)，要用badge-weak
    降噪樣式(虛線框+透明底)呈現，且標籤文字要帶「（草案）」字樣誠實揭露，不能再用
    實色圓角膠囊(舊版ht-tier inline style帶background/color)。"""
    output_path = tmp_path / "index.html"
    meta_perf = [{"meta_name": "超強族群", "avg_change_pct": 6.0, "up_count": 1, "down_count": 0, "flat_count": 0}]
    universe_df = pd.DataFrame([{"stock_id": "1", "stock_name": "股票一", "meta_sector": "超強族群"}])
    prices_df = pd.DataFrame([{"stock_id": "1", "close": 100.0, "change_pct": 6.0}])
    heatgrid_windows = {
        "超強族群": {"streak_today": 3, "last_week_pct_today": 1.0, "this_week_pct_today": 6.0,
                    "streak_5d_ago": None, "last_week_pct_5d_ago": None},
    }

    generate(date(2026, 8, 27), meta_perf, universe_df, {}, {}, prices_df, heatgrid_windows,
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "class=\"ht-tier badge-weak\"" in html
    assert "超強（草案）" in html
    assert "class=\"ht-temp badge-weak\"" in html
    assert "加速" in html and "（草案）" in html
    # 舊版寫死顏色的inline style不該再出現在tier_html裡
    assert 'style="background:var(--tier-super)22' not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "confidence_tiering" -v`
Expected: FAIL — current output has `class="ht-tier"` with inline `style="background:...;color:..."`, no `badge-weak` class, no「（草案）」suffix.

- [ ] **Step 3: Add `.badge-weak` CSS**

In `export/index_generator.py`'s `_CSS` block, find (added in Wave 1 Task 10, right after `.heat-tile.tier-super:hover`):

```css
.heat-tile.tier-super:hover{box-shadow:0 0 26px color-mix(in srgb, var(--accent) 24%, transparent), var(--shadow-2)}
```

Add right after it:

```css
/* 信心分層(docs/adr/0005)：真數字(排名/%/連漲跌天數/週對比等)維持實色強調；未回測的
   草案分類(五級動能/溫度/族群近況5組門檻/轉折點/排名進出榜)一律用這個降噪樣式──
   虛線框+透明底+比真數字小一號字級，標籤文字統一加「（草案）」字樣誠實揭露信心等級。
   是chips.html既有.evid-weak的精簡延伸(空間小的場景不放完整證據卡/banner)。*/
.badge-weak{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:9px;
  font-size:.6rem;font-weight:600;background:transparent;border:1px dashed var(--border-2);
  color:var(--ink-3)}
```

- [ ] **Step 4: Apply to heatgrid tier/temp badges**

In `_heatgrid_html`, find:

```python
        tier_html = ""
        if tier is not None:
            color = _TIER_COLOR_VAR[tier["key"]]
            tier_html = (
                f'<div class="ht-tier" style="background:{color}22;color:{color}">'
                f'<span class="dot" style="background:{color}"></span>{tier["label"]}</div>'
            )
        else:
            tier_html = '<div class="ht-tier" style="color:var(--ink-3)">資料不足</div>'

        if temp is not None:
            temp_html = f'<div class="ht-temp {temp["key"]}">{temp["label"]}</div>'
        elif c["accel"] is not None:
            temp_html = f'<div class="ht-temp flat tabular">→ {c["accel"]:+.1f}pt</div>'
        else:
            temp_html = ""
```

Change to:

```python
        tier_html = ""
        if tier is not None:
            tier_html = f'<div class="ht-tier badge-weak">{tier["label"]}（草案）</div>'
        else:
            tier_html = '<div class="ht-tier badge-weak">資料不足</div>'

        if temp is not None:
            temp_html = f'<div class="ht-temp badge-weak">{temp["label"]}（草案）</div>'
        elif c["accel"] is not None:
            temp_html = f'<div class="ht-temp badge-weak tabular">→ {c["accel"]:+.1f}pt（草案）</div>'
        else:
            temp_html = ""
```

(The `.dot` color hint and the per-tier/per-temp color variables `_TIER_COLOR_VAR`/`.ht-temp.hot`/`.ht-temp.cold` are deliberately dropped from this rendering path — `badge-weak`'s uniform muted styling IS the point; keeping a colored dot or colored background would partially defeat the de-emphasis. `_TIER_COLOR_VAR` itself is still used elsewhere in this file — e.g. the tier legend and turning-point pills — so don't remove the constant, only stop using it here.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "confidence_tiering" -v`
Expected: PASS.

- [ ] **Step 6: Run the broader heatgrid test group to catch regressions**

Run: `python -m pytest tests/test_index_generator.py -k "heatgrid or classify_tier or classify_temp or tier_super" -v`
Expected: check output carefully — `test_generate_renders_populated_tier_temp_badges_and_recap_data` (an existing Wave-1-era test) may assert the OLD tier/temp HTML format and will need updating. If it fails, open `tests/test_index_generator.py`, find that test, and update its assertions to match the new `badge-weak` +「（草案）」format (same spirit as this task's Step 1 test) — do not weaken the test to just check for absence of a crash; assert the actual new expected substrings.

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 熱區格五級動能/溫度標籤套信心分層(badge-weak+草案字樣)"
```

## Context

Task 3 of 12. This is the first visible confidence-tiering change (ADR 0005). `_TIER_COLOR_VAR` is a module-level dict mapping tier keys to CSS color variables — it's used in multiple places in this file (heatgrid tier badges being de-emphasized here, but also the tier legend at the top of the page and the turning-point transition pills later in the page) — do NOT delete `_TIER_COLOR_VAR` itself, only stop referencing it in `_heatgrid_html`'s tier/temp rendering.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If `_heatgrid_html`'s current tier_html/temp_html construction differs from what's shown, ask before proceeding.

## Your Job

1. Write the test, confirm it fails
2. Add the CSS rule
3. Change tier_html/temp_html construction
4. Confirm the new test passes
5. Run the broader regression group — if `test_generate_renders_populated_tier_temp_badges_and_recap_data` fails, update its assertions (don't skip or weaken it)
6. Commit
7. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`.

## When You're in Over Your Head

STOP and escalate if `_TIER_COLOR_VAR` turns out to be used in a way that makes it unsafe to stop referencing it in `_heatgrid_html` (e.g. if some other code path expects `_heatgrid_html`'s output to contain the old color-coded format).

## Before Reporting Back: Self-Review

- Does EVERY tier/temp badge in `_heatgrid_html`'s output now use `badge-weak` with no leftover inline `background`/`color` style?
- Did you update (not delete/skip) any pre-existing test that asserted the old badge format?
- Did you leave `_TIER_COLOR_VAR` intact for its other use sites?

## Report Format

Same format as Task 1.

---

### Task 4: `_margin_divergence_html()` — render 融資背離警示 table

**Files:**
- Modify: `export/index_generator.py` (new function, place near `_vol_turnover_html` for pattern consistency)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_margin_divergence_html_renders_bearish_and_bullish_tables():
    """融資背離警示是真數字(融資餘額趨勢vs股價趨勢，個股層級)，不套badge-weak，
    用跟_vol_turnover_html()一致的table樣式。bearish/bullish各自最多顯示5檔。"""
    from export.index_generator import _margin_divergence_html
    margin_divergence = {
        "bearish": [
            {"stock_id": "1101", "stock_name": "台泥", "meta_sector": "水泥",
             "margin_pct": 5.2, "price_pct": -3.1, "days": 10, "close": 30.5},
        ],
        "bullish": [
            {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
             "margin_pct": -4.0, "price_pct": 6.5, "days": 10, "close": 1080.0},
        ],
        "days_used": 10,
    }
    html = _margin_divergence_html(margin_divergence)
    assert "1101" in html and "台泥" in html
    assert "2330" in html and "台積電" in html
    assert "融資背離" in html
    assert "badge-weak" not in html  # 真數字不套草案樣式


def test_margin_divergence_html_returns_empty_string_when_no_signals():
    from export.index_generator import _margin_divergence_html
    assert _margin_divergence_html({"bearish": [], "bullish": [], "days_used": 10}) == ""
    assert _margin_divergence_html(None) == ""
    assert _margin_divergence_html({}) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "margin_divergence_html" -v`
Expected: FAIL with `ImportError: cannot import name '_margin_divergence_html'`.

- [ ] **Step 3: Implement `_margin_divergence_html()`**

In `export/index_generator.py`, add this function right after `_vol_turnover_html` (before `def build_heatgrid_cards`):

```python
def _margin_divergence_html(margin_divergence: Optional[Dict[str, Any]]) -> str:
    """
    融資背離警示（get_margin_divergence() 輸出）：個股融資餘額趨勢 vs 股價趨勢背離，
    真實成交數字（不是門檻草案分類），套實色強調，不套badge-weak（見docs/adr/0005）。
    bearish/bullish各自最多顯示5檔（該函式本身回傳最多20檔，這裡只取UI要顯示的前5）。
    兩邊都沒資料時回空字串，不顯示這個子區塊。
    """
    if not margin_divergence:
        return ""
    bearish = (margin_divergence.get("bearish") or [])[:5]
    bullish = (margin_divergence.get("bullish") or [])[:5]
    if not bearish and not bullish:
        return ""

    def _rows(items: List[Dict[str, Any]]) -> str:
        return "".join(
            '<tr>'
            f'<td><span class="tabular" style="color:var(--ink-3)">{_esc(r["stock_id"])}</span> '
            f'<span>{_esc(r.get("stock_name", ""))}</span></td>'
            f'<td class="vt-sector">{_esc(r.get("meta_sector", ""))}</td>'
            f'<td class="tabular" style="color:var(--accent);font-weight:700">{r["margin_pct"]:+.1f}%</td>'
            f'<td class="tabular" style="color:{"var(--up)" if r["price_pct"] >= 0 else "var(--down)"};font-weight:700">{r["price_pct"]:+.1f}%</td>'
            f'<td class="tabular" style="color:var(--ink-3)">{r["days"]}日</td>'
            '</tr>'
            for r in items
        )

    bearish_html = (
        f'<div class="mdiv-col"><div class="mdiv-col-head bearish">警訊：融資增、股價跌</div>'
        '<div class="overflow-wrap"><table class="vt-table">'
        '<thead><tr><th>代號 / 名稱</th><th>族群</th><th>融資變化</th><th>股價變化</th><th>天數</th></tr></thead>'
        f'<tbody>{_rows(bearish)}</tbody></table></div></div>'
    ) if bearish else ""
    bullish_html = (
        f'<div class="mdiv-col"><div class="mdiv-col-head bullish">健康：融資減、股價漲</div>'
        '<div class="overflow-wrap"><table class="vt-table">'
        '<thead><tr><th>代號 / 名稱</th><th>族群</th><th>融資變化</th><th>股價變化</th><th>天數</th></tr></thead>'
        f'<tbody>{_rows(bullish)}</tbody></table></div></div>'
    ) if bullish else ""

    return (
        '<div class="mdiv-wrap">'
        f'<div class="mdiv-head">融資背離 · 近{margin_divergence.get("days_used", 0)}個交易日</div>'
        f'<div class="mdiv-cols">{bearish_html}{bullish_html}</div>'
        '</div>'
    )
```

- [ ] **Step 4: Add CSS for `.mdiv-*`**

In `_CSS`, find the `.vt-sector{...}` rule (part of `_vol_turnover_html`'s existing styling) and add right after it:

```css
.mdiv-wrap{margin-top:10px}
.mdiv-head{font-family:var(--mono);font-size:.68rem;font-weight:700;color:var(--ink-3);margin-bottom:8px}
.mdiv-cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:700px){.mdiv-cols{grid-template-columns:1fr}}
.mdiv-col-head{font-size:.74rem;font-weight:700;margin-bottom:6px}
.mdiv-col-head.bearish{color:var(--down)}
.mdiv-col-head.bullish{color:var(--up)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "margin_divergence_html" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 新增_margin_divergence_html()渲染融資背離警示表格"
```

## Context

Task 4 of 12. This function is not wired into the page yet — it's built and tested standalone first (matching this codebase's established pattern of building renderer functions independently, then assembling them in `generate()` later — see how `_vol_turnover_html`/`_anomaly_cards_html`/`_sector_recap_html` are all separately testable functions). Task 8 wires this into the new combined section.

`get_margin_divergence()`'s exact return shape (from `processors/performance.py:362-466`): `{"bearish": [...], "bullish": [...], "days_used": int}`, each item a dict with `stock_id`, `stock_name`, `meta_sector`, `margin_pct` (float, % change in margin balance over the period), `price_pct` (float, % change in price over the same period), `days` (int), `close` (float), `change_pct` (always `None` — deliberately unused field, don't reference it).

This is a REAL-NUMBER signal (per ADR 0005), so it does NOT get `badge-weak` styling — it reuses the same table pattern as `_vol_turnover_html()` (`.vt-table`/`.vt-sector` CSS classes, already defined) for visual consistency with the other "real transacted data" table on this page.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

Ask if anything about `_vol_turnover_html`'s current implementation (used as the style reference here) looks different from what's described.

## Your Job

1. Write both tests, confirm they fail
2. Implement `_margin_divergence_html()` + CSS
3. Confirm tests pass
4. Commit
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. This function stands alone — don't wire it into `generate()`'s HTML body yet.

## When You're in Over Your Head

STOP and escalate if `get_margin_divergence()`'s actual return shape (check `processors/performance.py:362-466` yourself if unsure) differs from what's described here.

## Before Reporting Back: Self-Review

- Does the function return `""` for all three "no data" cases tested (empty bearish+bullish, `None` input, `{}` input)?
- Are bearish/bullish each correctly capped at 5 items even if the input has more?
- Is there NO `badge-weak` class anywhere in this function's output (real numbers, not draft classifications)?

## Report Format

Same format as Task 1.

---

### Task 5: `_limit_up_html()` — render 連續漲停鎖死 table

**Files:**
- Modify: `export/index_generator.py` (new function, place right after `_margin_divergence_html`)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_limit_up_html_renders_table_with_streak_and_volume_flags():
    """連續漲停鎖死是真數字(連續鎖漲停天數是既成事實)，不套badge-weak。
    量能遞減/起漲爆量兩個bool|None旗標要各自有清楚的視覺標示。"""
    from export.index_generator import _limit_up_html
    limit_up_results = [
        {"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
         "close": 1080.0, "change_pct": 9.9, "volume": 50000,
         "limit_up_streak": 3, "volume_declining_streak": True, "breakout_volume_confirmed": True},
        {"stock_id": "1101", "stock_name": "台泥", "meta_sector": "水泥",
         "close": 30.5, "change_pct": 9.8, "volume": 12000,
         "limit_up_streak": 1, "volume_declining_streak": None, "breakout_volume_confirmed": None},
    ]
    html = _limit_up_html(limit_up_results)
    assert "2330" in html and "台積電" in html
    assert "連續漲停" in html
    assert "3" in html  # limit_up_streak
    assert "badge-weak" not in html


def test_limit_up_html_returns_empty_string_when_no_results():
    from export.index_generator import _limit_up_html
    assert _limit_up_html([]) == ""
    assert _limit_up_html(None) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "limit_up_html" -v`
Expected: FAIL with `ImportError: cannot import name '_limit_up_html'`.

- [ ] **Step 3: Implement `_limit_up_html()`**

In `export/index_generator.py`, add right after `_margin_divergence_html`:

```python
def _limit_up_html(limit_up_results: Optional[List[Dict[str, Any]]]) -> str:
    """
    連續漲停鎖死（scan_consecutive_limit_up() 輸出）：連續鎖漲停天數是既成事實，真實
    成交數字，套實色強調，不套badge-weak（見docs/adr/0005）。量能遞減/起漲爆量兩個
    旗標是bool|None（None=資料不足無法判定，不是False），要分三態顯示，不能把None
    當False處理。最多顯示前10檔（函式本身已依limit_up_streak降冪排序）。
    """
    if not limit_up_results:
        return ""
    rows = []
    for r in limit_up_results[:10]:
        vd = r.get("volume_declining_streak")
        vd_html = (
            '<span style="color:var(--up)">量縮鎖死</span>' if vd is True
            else '<span style="color:var(--ink-3)">量未縮</span>' if vd is False
            else '<span style="color:var(--ink-3)">─</span>'
        )
        bc = r.get("breakout_volume_confirmed")
        bc_html = (
            '<span class="badge foreign">起漲爆量</span>' if bc is True
            else '' if bc is False
            else '<span style="color:var(--ink-3)">─</span>'
        )
        rows.append(
            '<tr>'
            f'<td><span class="tabular" style="color:var(--ink-3)">{_esc(r["stock_id"])}</span> '
            f'<span>{_esc(r.get("stock_name", ""))}</span></td>'
            f'<td class="vt-sector">{_esc(r.get("meta_sector", ""))}</td>'
            f'<td class="tabular" style="color:var(--up);font-weight:700">{r["limit_up_streak"]}天</td>'
            f'<td>{vd_html}</td>'
            f'<td>{bc_html}</td>'
            '</tr>'
        )
    return (
        '<div class="mdiv-wrap">'
        f'<div class="mdiv-head">連續漲停鎖死 · 共 {len(limit_up_results)} 檔</div>'
        '<div class="overflow-wrap"><table class="vt-table">'
        '<thead><tr><th>代號 / 名稱</th><th>族群</th><th>連續天數</th><th>量能</th><th>起漲確認</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></div>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "limit_up_html" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 新增_limit_up_html()渲染連續漲停鎖死表格"
```

## Context

Task 5 of 12. Same pattern as Task 4 — standalone, tested independently, wired into the page in Task 8. Reuses `.mdiv-wrap`/`.mdiv-head` CSS from Task 4 (same visual family, just a single table instead of two side-by-side).

`scan_consecutive_limit_up()`'s exact return shape (from `screener/signals.py:438-556`): list of dicts sorted by `limit_up_streak` descending, each with `stock_id`, `stock_name`, `meta_sector`, `close`, `change_pct`, `volume` (int|None), `limit_up_streak` (int), `volume_declining_streak` (bool|None — **None means "can't determine", not False** — a stock with `streak < 2` always has `None` here since the calculation needs at least 2 days), `breakout_volume_confirmed` (bool|None — same three-state semantics, None when insufficient pre-breakout history or missing volume data).

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

Ask if `scan_consecutive_limit_up()`'s actual return shape differs from what's described (check `screener/signals.py:438-556` if unsure).

## Your Job

1. Write both tests, confirm they fail
2. Implement `_limit_up_html()`
3. Confirm tests pass
4. Commit
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. Don't wire this into `generate()` yet.

## When You're in Over Your Head

STOP and escalate if the three-state (`True`/`False`/`None`) semantics of `volume_declining_streak`/`breakout_volume_confirmed` are unclear from the actual code — this is exactly the kind of subtle bug class (`None` treated as falsy) this file's own comments repeatedly warn about (see the extensive comments in `screener/signals.py` around these two fields).

## Before Reporting Back: Self-Review

- Does the function correctly distinguish `True`/`False`/`None` for both flags (not just `if vd:`)?
- Does it return `""` for empty/`None` input?
- Is the list correctly capped at 10 items while `len(limit_up_results)` in the header still reports the TRUE total (not the capped count)?

## Report Format

Same format as Task 1.

---

### Task 6: Extract 今日爆發 out of `_sector_recap_html()`, leave 5 categories

**Files:**
- Modify: `export/index_generator.py:1109-1195` (`_sector_recap_html`)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sector_recap_html_no_longer_renders_today_breakout():
    """今日爆發移到「今日/本週異動」區塊(今日層)，族群近況不再顯示它，
    也不再顯示轉折點/排名進出榜(Task 9才會確認這兩個也搬走)——這裡先鎖今日爆發。"""
    from export.index_generator import _sector_recap_html
    recap = {
        "hot_top5": [], "cold_top5": [],
        "today_breakout": [{"meta_name": "衝刺族群", "pct": 3.0, "rank_delta": 12}],
        "foreign_stealth": [], "trust_stealth": [], "volume_anomaly": [],
        "turning_points": [], "rank_crossings": {"just_in": [], "just_out": []},
    }
    html = _sector_recap_html(recap)
    assert "今日爆發" not in html
    assert "衝刺族群" not in html


def test_today_breakout_html_renders_real_number_rows():
    """新的_today_breakout_html()渲染函式：今日爆發是真數字(排名跳動+今日漲跌%)，
    不套badge-weak。"""
    from export.index_generator import _today_breakout_html
    today_breakout = [{"meta_name": "衝刺族群", "pct": 3.2, "rank_delta": 15}]
    html = _today_breakout_html(today_breakout)
    assert "衝刺族群" in html
    assert "今日爆發" in html
    assert "badge-weak" not in html


def test_today_breakout_html_returns_empty_string_when_no_items():
    from export.index_generator import _today_breakout_html
    assert _today_breakout_html([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "today_breakout" -v`
Expected: `test_sector_recap_html_no_longer_renders_today_breakout` FAILS (今日爆發 still rendered); the two `_today_breakout_html` tests FAIL with `ImportError` (function doesn't exist).

- [ ] **Step 3: Extract a standalone `_today_breakout_html()` function**

In `export/index_generator.py`, add this new function right after `_limit_up_html` (from Task 5):

```python
def _today_breakout_html(today_breakout: List[Dict[str, Any]]) -> str:
    """
    今日爆發（族群層級，今日排名跳動≥門檻且上漲，不要求同時爆量）：真數字，不套
    badge-weak。從舊版_sector_recap_html()的status-cols其中一欄抽出來，現在是
    「今日/本週異動」區塊今日層的一部分（見docs/adr/0005/CONTEXT.md「今日/本週異動」
    詞條——這是唯一族群層級的今日層項目，其餘三個(異動族群/融資背離/連續漲停)都是
    個股層級）。
    """
    if not today_breakout:
        return ""
    rows = "".join(
        f'<div class="status-row"><span class="sr-name">{_esc(r["meta_name"])}</span>'
        f'<span class="sr-today tabular" style="color:{"var(--up)" if r["pct"] >= 0 else "var(--down)"}">{_pct_str(r["pct"])}</span>'
        f'<span class="sr-pt tabular" style="color:var(--up)">↑{r["rank_delta"]}</span></div>'
        for r in today_breakout
    )
    return (
        '<div class="mdiv-wrap">'
        f'<div class="mdiv-head">今日爆發 · {len(today_breakout)} 個族群</div>'
        f'<div>{rows}</div>'
        '</div>'
    )
```

- [ ] **Step 4: Remove today_breakout rendering from `_sector_recap_html()`**

In `export/index_generator.py`, find (inside `_sector_recap_html`):

```python
    breakout_html = _col(recap["today_breakout"], lambda r: _status_row(
        r["meta_name"], r["pct"], f'↑{r["rank_delta"]}', "var(--up)"))
    foreign_html = _col(recap["foreign_stealth"], lambda r: _status_row(
```

Change to (delete the `breakout_html` line entirely):

```python
    foreign_html = _col(recap["foreign_stealth"], lambda r: _status_row(
```

Find the `<div class="status-cols">` block:

```python
<div class="status-cols">
  <div><div class="status-col-head hot">近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head cold">近期退燒 Top 5</div><div>{cold_html}</div></div>
  <div><div class="status-col-head breakout">今日爆發 Top 5</div><div>{breakout_html}</div>
    <div class="status-col-note">今日排名跳動≥{_BREAKOUT_RANK_JUMP_MIN}名且上漲，不要求同時爆量——單日單一事件，跟下面「退燒」互斥</div></div>
  <div><div class="status-col-head foreign">外資悄悄佈局 Top 5</div><div>{foreign_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但外資連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head trust">投信悄悄佈局 Top 5</div><div>{trust_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但投信連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head volume">量能異常 Top 5</div><div>{volume_html}</div>
    <div class="status-col-note">今日量能≥{_VOL_ANOMALY_RATIO_MIN}x5日均量，但股價還沒明顯反應（±{_VOL_ANOMALY_PRICE_FLAT_MAX}%內）</div></div>
</div>
```

Change to (breakout column removed):

```python
<div class="status-cols">
  <div><div class="status-col-head hot">近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head cold">近期退燒 Top 5</div><div>{cold_html}</div></div>
  <div><div class="status-col-head foreign">外資悄悄佈局 Top 5</div><div>{foreign_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但外資連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head trust">投信悄悄佈局 Top 5</div><div>{trust_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但投信連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head volume">量能異常 Top 5</div><div>{volume_html}</div>
    <div class="status-col-note">今日量能≥{_VOL_ANOMALY_RATIO_MIN}x5日均量，但股價還沒明顯反應（±{_VOL_ANOMALY_PRICE_FLAT_MAX}%內）</div></div>
</div>
```

Also update the section header (still in `_sector_recap_html`'s return statement), find:

```python
<div class="section-head"><h2>族群近況</h2><span class="count">6大類排行・轉折點</span></div>
```

Change to:

```python
<div class="section-head"><h2>族群近況</h2><span class="count">5大類排行・持續觀察</span></div>
```

(This task does NOT yet remove `turning_points`/`rank_crossings` rendering from `_sector_recap_html()` — that's Task 9, after the new "今日/本週異動" section exists in Task 8 to hold them. Leaving them in place for now keeps the page functional between tasks.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "today_breakout" -v`
Expected: PASS.

- [ ] **Step 6: Run the broader `build_sector_recap`/`_sector_recap_html` test group**

Run: `python -m pytest tests/test_index_generator.py -k "sector_recap or build_sector_recap" -v`
Expected: `test_build_sector_recap_*` tests (which test the DATA function, not the HTML function) should all still pass unchanged — `build_sector_recap()` itself is untouched, `today_breakout` is still computed and present in the `recap` dict, just no longer rendered by `_sector_recap_html()`. If any HTML-rendering test in this group asserts `今日爆發`/breakout text appears in `_sector_recap_html()`'s output, update it to match the new expectation (not rendered there anymore).

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "refactor(index): 今日爆發抽成獨立_today_breakout_html(),族群近況剩5大類"
```

## Context

Task 6 of 12. `build_sector_recap()` (the DATA function that computes `today_breakout`/`hot_top5`/etc.) is NOT changed — only `_sector_recap_html()` (the HTML RENDERING function) stops using `recap["today_breakout"]`. The data is still there in the `recap` dict; Task 8 will pass it to the new `_today_breakout_html()` function instead.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If the current `_sector_recap_html`/`build_sector_recap` code differs from what's shown, ask before proceeding.

## Your Job

1. Write the 3 tests, confirm the expected failures
2. Add `_today_breakout_html()`
3. Remove breakout rendering from `_sector_recap_html()`, update the H2 count text
4. Confirm tests pass, run the broader group and fix any test expecting the old behavior
5. Commit
6. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. Don't touch `build_sector_recap()` — only `_sector_recap_html()`.

## When You're in Over Your Head

STOP and escalate if removing the breakout column breaks something unexpected in the status-cols grid CSS, or if `build_sector_recap()`'s actual output shape differs from what's described.

## Before Reporting Back: Self-Review

- Is `today_breakout` still computed by `build_sector_recap()` (check you didn't touch that function)?
- Does `_sector_recap_html()`'s output genuinely no longer contain 今日爆發 content?
- Does the new `_today_breakout_html()` correctly return `""` for empty input?

## Report Format

Same format as Task 1.

---

### Task 7: Convert 異動族群 cards from horizontal scroll strip to grid

**Files:**
- Modify: `export/index_generator.py:764-765` (`.anomaly-wrap`/`.anomaly-strip` CSS)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_anomaly_strip_css_uses_grid_not_horizontal_scroll(tmp_path):
    """異動族群卡片現在放進滿版寬的「今日/本週異動」今日層(Task 8)，不再需要橫向
    捲動——改成grid全部展開，有幾張顯幾張。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 27), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert ".anomaly-strip{display:grid" in html.replace(" ", "").replace("\n", "")
    assert "overflow-x:auto" not in html[html.index(".anomaly-strip"):html.index(".anomaly-strip") + 200]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_generator.py -k "anomaly_strip_css_uses_grid" -v`
Expected: FAIL — current `.anomaly-strip` uses `display:flex;gap:14px;overflow-x:auto;padding:2px 2px 6px`.

- [ ] **Step 3: Change the CSS**

In `export/index_generator.py`'s `_CSS` block, find:

```css
.anomaly-wrap{position:relative;margin:0 26px}
.anomaly-strip{display:flex;gap:14px;overflow-x:auto;padding:2px 2px 6px}
.anomaly-wrap::after{content:"";position:absolute;top:0;right:0;bottom:6px;width:44px;pointer-events:none;background:linear-gradient(to right, transparent, var(--bg) 88%)}
.anomaly-card{flex:0 0 240px;background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:15px 17px;position:relative;cursor:pointer;transition:box-shadow .2s,transform .2s,border-color .2s}
```

Change to:

```css
.anomaly-wrap{position:relative}
.anomaly-strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;padding:2px 2px 6px}
.anomaly-card{background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:15px 17px;position:relative;cursor:pointer;transition:box-shadow .2s,transform .2s,border-color .2s}
```

(Dropped `.anomaly-wrap::after` — that was the fade-out gradient hinting "more cards to scroll right", no longer needed once it's a wrapping grid instead of a horizontal strip. Dropped `flex:0 0 240px` from `.anomaly-card` since grid items don't need a flex-basis; `minmax(220px,1fr)` on the grid template controls sizing instead. `.anomaly-wrap`'s `margin:0 26px` is also dropped here — Task 8 will place `.anomaly-wrap` inside the new full-width section which manages its own margins, so a hardcoded `26px` here would double up; if Task 8's container doesn't already handle the gutter, re-add appropriate spacing there, not here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index_generator.py -k "anomaly_strip_css_uses_grid" -v`
Expected: PASS.

- [ ] **Step 5: Run the anomaly-card test group to catch regressions**

Run: `python -m pytest tests/test_index_generator.py -k "anomaly" -v`
Expected: all pass — `_anomaly_cards_html()` itself (the function building each `.anomaly-card` div) is unchanged, only the CSS wrapping them changed.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "style(index): 異動族群卡片改grid全展開,不再橫向捲動"
```

## Context

Task 7 of 12. Purely a CSS change — `_anomaly_cards_html()` (the function that builds each individual `.anomaly-card` div's content) is completely untouched, only the CONTAINER (`.anomaly-strip`/`.anomaly-wrap`) styling changes from a horizontal-scroll flex row to a wrapping CSS grid. This anticipates Task 8, where the anomaly strip moves inside a new full-width section (no longer squeezed into a half-width column, so there's no more need to scroll horizontally).

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If the current `.anomaly-wrap`/`.anomaly-strip`/`.anomaly-card` CSS differs from what's shown, ask before proceeding.

## Your Job

1. Write the test, confirm it fails
2. Change the CSS
3. Confirm it passes, run the broader anomaly test group
4. Commit
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py`'s `_CSS` block and `tests/test_index_generator.py`. Do NOT touch `_anomaly_cards_html()`'s function body.

## When You're in Over_Your Head

STOP and escalate if the current CSS differs substantially from what's described.

## Before Reporting Back: Self-Review

- Is `_anomaly_cards_html()` genuinely untouched (check `git diff` only shows CSS lines changed)?
- Does the new CSS use `display:grid` (not `flex`) with `auto-fill`/`minmax` for responsive wrapping?

## Report Format

Same format as Task 1.

---

### Task 8: New `_today_week_movements_html()` — assemble the merged「今日/本週異動」section

**Files:**
- Modify: `export/index_generator.py` (new function, place right after `_sector_recap_html`)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_today_week_movements_html_assembles_today_and_week_layers():
    """新的_today_week_movements_html()把今日層(異動族群卡片grid+今日爆發+融資背離+
    連續漲停鎖死)跟本週層(轉折點+排名進出榜並排二欄，套badge-weak)組裝成一個區塊，
    今日層在前、本週層在後，開頭有一次性揭露文案。"""
    from export.index_generator import _today_week_movements_html
    anomaly_cards = [{"kind": "burst", "meta_name": "爆量族群", "pct": 5.0, "reason": "測試理由"}]
    today_breakout = [{"meta_name": "衝刺族群", "pct": 3.0, "rank_delta": 12}]
    margin_divergence = {"bearish": [{"stock_id": "1101", "stock_name": "台泥", "meta_sector": "水泥",
                                       "margin_pct": 5.2, "price_pct": -3.1, "days": 10, "close": 30.5}],
                          "bullish": [], "days_used": 10}
    limit_up_results = [{"stock_id": "2330", "stock_name": "台積電", "meta_sector": "半導體",
                          "close": 1080.0, "change_pct": 9.9, "volume": 50000,
                          "limit_up_streak": 2, "volume_declining_streak": True,
                          "breakout_volume_confirmed": True}]
    turning_points = [{"meta_name": "轉折族群", "prev_key": "weak", "prev_label": "弱",
                        "cur_key": "strong", "cur_label": "強", "direction": "轉強"}]
    rank_crossings = {"just_in": [{"meta_name": "進榜族群", "prev_rank": 15, "cur_rank": 8}], "just_out": []}

    html = _today_week_movements_html(
        anomaly_cards, today_breakout, margin_divergence, limit_up_results,
        turning_points, rank_crossings,
    )

    today_pos = html.index("今日")
    week_pos = html.index("本週")
    assert today_pos < week_pos, "今日層要在本週層前面"
    assert "爆量族群" in html
    assert "衝刺族群" in html
    assert "台泥" in html
    assert "台積電" in html
    assert "轉折族群" in html
    assert "進榜族群" in html
    # 本週層的轉折點/排名進出榜要套badge-weak，今日層的東西不要
    week_section = html[week_pos:]
    assert "badge-weak" in week_section


def test_today_week_movements_html_includes_one_time_disclosure_for_week_layer():
    """揭露文案只針對本週層(草案門檻)出現一次，不是每張卡片重複。"""
    from export.index_generator import _today_week_movements_html
    html = _today_week_movements_html([], [], {}, [], [], {"just_in": [], "just_out": []})
    assert "未回測" in html or "草案" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "today_week_movements" -v`
Expected: FAIL with `ImportError: cannot import name '_today_week_movements_html'`.

- [ ] **Step 3: Implement `_today_week_movements_html()`**

In `export/index_generator.py`, add this function right after `_sector_recap_html` (before `def generate`):

```python
def _today_week_movements_html(
    anomaly_cards: List[Dict[str, Any]],
    today_breakout: List[Dict[str, Any]],
    margin_divergence: Optional[Dict[str, Any]],
    limit_up_results: Optional[List[Dict[str, Any]]],
    turning_points: List[Dict[str, Any]],
    rank_crossings: Dict[str, List[Dict[str, Any]]],
) -> str:
    """
    「今日/本週異動」區塊（見CONTEXT.md詞條、docs/adr/0006）：合併原本分散在「異動族群」
    「族群近況」兩處、但本質都是「族群層級發生了變化，值得注意」的訊號。依時間尺度分兩層：

    今日層（4項，都是今日單日事件，真數字實色強調，不套badge-weak）：
      異動族群（族群層級：爆量暴衝/連續噴出）、今日爆發（族群層級：排名跳動+上漲）、
      融資背離警示（個股層級，NEW）、連續漲停鎖死（個股層級，NEW）。

    本週層（2項並排二欄，門檻未回測，套badge-weak）：
      轉折點（左）、排名進出榜（右）——兩者依docs/adr/0003維持獨立訊號，只是搬到
      同一個新區塊裡相鄰呈現，不合併成一個指標。
    """
    anomaly_html = _anomaly_cards_html(anomaly_cards)
    breakout_html = _today_breakout_html(today_breakout)
    mdiv_html = _margin_divergence_html(margin_divergence)
    limitup_html = _limit_up_html(limit_up_results)

    today_parts = "".join(
        f'<div class="tw-today-item">{part}</div>'
        for part in (anomaly_html, breakout_html, mdiv_html, limitup_html) if part
    )
    today_section = (
        '<div class="tw-today-grid">'
        f'<div class="anomaly-wrap"><div class="anomaly-strip">{anomaly_html}</div></div>'
        f'{"".join(p for p in (breakout_html, mdiv_html, limitup_html) if p)}'
        '</div>'
    ) if (anomaly_html or today_parts) else '<div class="detail-empty">今天沒有族群或個股符合異動條件</div>'

    if turning_points:
        turning_html = "".join(
            f'<div class="turning-row"><span class="turning-name">{_esc(tp["meta_name"])}</span>'
            f'<span class="turning-transition">'
            f'<span class="turning-pill badge-weak">{tp["prev_label"]}</span>'
            f'<span class="turning-arrow">→</span>'
            f'<span class="turning-pill badge-weak">{tp["cur_label"]}</span>'
            f'</span><span class="turning-desc">{tp["direction"]}</span></div>'
            for tp in turning_points
        )
    else:
        turning_html = '<div class="detail-empty">本週沒有族群發生等級翻轉</div>'

    def _rankmove_col(items: List[Dict[str, Any]], direction: str) -> str:
        if not items:
            return '<div class="rankmove-empty">目前沒有族群{}</div>'.format(
                "剛進榜" if direction == "in" else "剛掉出榜"
            )
        return "".join(
            f'<div class="rankmove-item"><span class="rm-name">{_esc(r["meta_name"])}</span>'
            f'<span class="rm-shift tabular">#{r["prev_rank"]}→#{r["cur_rank"]}</span></div>'
            for r in items
        )

    week_section = f"""
<div class="tw-week-cols">
  <div class="tw-week-col">
    <div class="mdiv-head badge-weak">轉折點（草案）</div>
    <div class="tw-week-sub">上週的等級跟這週的等級是否真的換了一級（不是看誰漲最多）。</div>
    <div>{turning_html}</div>
  </div>
  <div class="tw-week-col">
    <div class="mdiv-head badge-weak">排名進出榜（草案）</div>
    <div class="tw-week-sub">這週剛擠進/掉出前10名、且自身報酬方向一致的族群。</div>
    <div class="rankmove-cols">
      <div class="rankmove-col in"><h4>剛進榜</h4>{_rankmove_col(rank_crossings.get("just_in", []), "in")}</div>
      <div class="rankmove-col out"><h4>剛掉出榜</h4>{_rankmove_col(rank_crossings.get("just_out", []), "out")}</div>
    </div>
  </div>
</div>"""

    return f"""
<div class="section-head"><h2>今日/本週異動</h2><span class="count">今日事件 + 本週趨勢</span></div>
<div class="section-rule"></div>
<div class="section-sub">今日層：爆量暴衝/連續噴出、排名跳動上漲、融資背離、連續鎖漲停——都是今日已發生的真實數字。
本週層：等級翻轉、排名進出榜——門檻是經驗法則草案，尚未回測驗證，僅供參考，不是投資建議。</div>
<div class="tw-today-label">今日</div>
{today_section}
<div class="tw-week-label">本週（草案，未回測）</div>
{week_section}
"""
```

- [ ] **Step 4: Add CSS for `.tw-*`**

In `_CSS`, add right after the `.mdiv-col-head.bullish{color:var(--up)}` rule (from Task 4):

```css
.tw-today-label,.tw-week-label{font-family:var(--mono);font-size:.62rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:16px 0 8px}
.tw-today-grid{display:flex;flex-direction:column;gap:16px}
.tw-week-cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media (max-width:760px){.tw-week-cols{grid-template-columns:1fr}}
.tw-week-col{background:var(--panel);border:1px solid var(--border-2);border-radius:5px;padding:16px 18px}
.tw-week-sub{font-size:.72rem;color:var(--ink-3);margin:4px 0 12px}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "today_week_movements" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 新增_today_week_movements_html()合併今日/本週異動區塊"
```

## Context

Task 8 of 12. This is the big assembly function combining everything built in Tasks 4-7. It's NOT wired into `generate()`'s HTML body yet — that's Task 10. `turning_points`/`rank_crossings` are STILL rendered by `_sector_recap_html()` too at this point (Task 6 said Task 9 removes them from there) — that's fine, this task only builds the new function; Task 9 will remove the now-duplicate rendering from `_sector_recap_html()` and Task 10 will place both functions correctly in the page.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If `_anomaly_cards_html`, `_today_breakout_html`, `_margin_divergence_html`, `_limit_up_html` (all built in prior tasks) don't exist yet or have different signatures than described, STOP — this task depends on all four being complete. Verify each exists before starting.

## Your Job

1. Write both tests, confirm they fail
2. Implement `_today_week_movements_html()` + CSS
3. Confirm tests pass
4. Commit
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. This function calls the four renderer functions from Tasks 4-7 — don't reimplement their logic inline.

## When You're in Over Your Head

STOP and escalate if any of the four dependency functions (`_anomaly_cards_html`, `_today_breakout_html`, `_margin_divergence_html`, `_limit_up_html`) don't exist or have signatures different from what prior tasks specified.

## Before Reporting Back: Self-Review

- Does the "今日" label genuinely appear before "本週" in the output (test this, don't assume)?
- Do BOTH `turning_points` and `rank_crossings` in the 本週層 use `badge-weak` styling?
- Is the disclosure text ("未回測"/"草案") present exactly once per call, not duplicated per card?
- Does `docs/adr/0003`'s "keep turning-point and rank-crossing separate" decision hold — are they still two visually distinct blocks (not merged into one list)?

## Report Format

Same format as Task 1.

---

### Task 9: Remove turning_points/rank_crossings from `_sector_recap_html()`, badge-weak the remaining 5 categories

**Files:**
- Modify: `export/index_generator.py:1109-1195` (`_sector_recap_html`)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sector_recap_html_no_longer_renders_turning_points_or_rank_crossings():
    """轉折點/排名進出榜移到_today_week_movements_html()(Task 8)，族群近況不再顯示，
    避免同一份資料被畫兩次。"""
    from export.index_generator import _sector_recap_html
    recap = {
        "hot_top5": [], "cold_top5": [], "today_breakout": [],
        "foreign_stealth": [], "trust_stealth": [], "volume_anomaly": [],
        "turning_points": [{"meta_name": "轉折族群", "prev_key": "weak", "prev_label": "弱",
                             "cur_key": "strong", "cur_label": "強", "direction": "轉強"}],
        "rank_crossings": {"just_in": [{"meta_name": "進榜族群", "prev_rank": 15, "cur_rank": 8}], "just_out": []},
    }
    html = _sector_recap_html(recap)
    assert "轉折族群" not in html
    assert "進榜族群" not in html
    assert "turning-wrap" not in html
    assert "rankmove-wrap" not in html


def test_sector_recap_html_remaining_5_categories_use_badge_weak():
    """族群近況剩下的5大類(升溫/退燒/外資/投信/量能)門檻同樣未回測，這次也套badge-weak
    (原本這5類是靠status-col-head的彩色底線區分類別，不是badge-weak——這裡改成整個
    status-col-head也降噪)。"""
    from export.index_generator import _sector_recap_html
    recap = {
        "hot_top5": [{"meta_name": "熱族群", "pct": 5.0, "accel": 3.2}],
        "cold_top5": [], "today_breakout": [],
        "foreign_stealth": [], "trust_stealth": [], "volume_anomaly": [],
        "turning_points": [], "rank_crossings": {"just_in": [], "just_out": []},
    }
    html = _sector_recap_html(recap)
    assert "badge-weak" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "sector_recap_html_no_longer_renders_turning or remaining_5_categories" -v`
Expected: FAIL — turning_points/rank_crossings are still rendered; no `badge-weak` class anywhere in `_sector_recap_html()`'s output yet.

- [ ] **Step 3: Remove turning/rankmove rendering, add badge-weak to category headers**

In `export/index_generator.py`, find the full `_sector_recap_html` function body (after Task 6's edits already removed `breakout_html`). Find:

```python
    turning = recap["turning_points"]
    if turning:
        turning_html = "".join(
            f'<div class="turning-row"><span class="turning-name">{_esc(tp["meta_name"])}</span>'
            f'<span class="turning-transition">'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["prev_key"]]}22;color:{_TIER_COLOR_VAR[tp["prev_key"]]}">{tp["prev_label"]}</span>'
            f'<span class="turning-arrow">→</span>'
            f'<span class="turning-pill" style="background:{_TIER_COLOR_VAR[tp["cur_key"]]}22;color:{_TIER_COLOR_VAR[tp["cur_key"]]}">{tp["cur_label"]}</span>'
            f'</span><span class="turning-desc">{tp["direction"]}</span></div>'
            for tp in turning
        )
    else:
        turning_html = '<div class="detail-empty">本週沒有族群發生等級翻轉</div>'

    def _rankmove_col(items: List[Dict[str, Any]], direction: str) -> str:
        if not items:
            return '<div class="rankmove-empty">目前沒有族群{}</div>'.format(
                "剛進榜" if direction == "in" else "剛掉出榜"
            )
        return "".join(
            f'<div class="rankmove-item"><span class="rm-name">{_esc(r["meta_name"])}</span>'
            f'<span class="rm-shift tabular">#{r["prev_rank"]}→#{r["cur_rank"]}</span></div>'
            for r in items
        )

    rank_crossings = recap.get("rank_crossings", {"just_in": [], "just_out": []})
    rankmove_html = f"""
<div class="rankmove-wrap">
  <div class="rankmove-head">排名進出榜</div>
  <div class="rankmove-sub">這週剛擠進/掉出前10名、且自身報酬方向一致的族群（單純排名進步但自身仍是負報酬、或退步但自身仍是正報酬不算——跟上面「轉折點」是不同角度的訊號）</div>
  <div class="rankmove-cols">
    <div class="rankmove-col in"><h4>剛進榜</h4>{_rankmove_col(rank_crossings["just_in"], "in")}</div>
    <div class="rankmove-col out"><h4>剛掉出榜</h4>{_rankmove_col(rank_crossings["just_out"], "out")}</div>
  </div>
</div>"""

    return f"""
<div class="section-head"><h2>族群近況</h2><span class="count">5大類排行・持續觀察</span></div>
<div class="section-rule"></div>
<div class="role-note">
  <span><b>族群近況</b>＝週度趨勢+單日事件+籌碼訊號的綜合面板</span>
  <span><b>異動族群</b>（頁面最上方）只看爆量+排名跳動同時成立，門檻比這裡的「今日爆發」嚴格</span>
  <span>兩者角色不同，故意分開兩個區塊，不是重複資訊</span>
</div>
<div class="status-cols">
  <div><div class="status-col-head hot">近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head cold">近期退燒 Top 5</div><div>{cold_html}</div></div>
  <div><div class="status-col-head foreign">外資悄悄佈局 Top 5</div><div>{foreign_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但外資連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head trust">投信悄悄佈局 Top 5</div><div>{trust_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但投信連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head volume">量能異常 Top 5</div><div>{volume_html}</div>
    <div class="status-col-note">今日量能≥{_VOL_ANOMALY_RATIO_MIN}x5日均量，但股價還沒明顯反應（±{_VOL_ANOMALY_PRICE_FLAT_MAX}%內）</div></div>
</div>
<div class="turning-wrap">
  <div class="turning-head">轉折點：等級真的翻轉的族群</div>
  <div class="turning-sub">不是看誰漲最多，是看「上週的等級」跟「這週的等級」是否真的換了一級。</div>
  <div>{turning_html}</div>
</div>
{rankmove_html}"""
```

Change to (delete the `turning`/`turning_html`/`_rankmove_col`/`rank_crossings`/`rankmove_html` local variables entirely — they're no longer used here; add `badge-weak` to each `.status-col-head`; drop the `role-note` comparison text that referenced 異動族群's position, since that comparison now lives in the new section's own copy; remove the `.turning-wrap`/`rankmove_html` blocks from the return statement):

```python
    return f"""
<div class="section-head"><h2>族群近況</h2><span class="count">5大類排行・持續觀察（草案，未回測）</span></div>
<div class="section-rule"></div>
<div class="role-note">
  <span><b>族群近況</b>＝週度趨勢+籌碼訊號的持續觀察面板，門檻是經驗法則草案，尚未回測驗證</span>
</div>
<div class="status-cols">
  <div><div class="status-col-head badge-weak hot">近期增溫 Top 5</div><div>{hot_html}</div></div>
  <div><div class="status-col-head badge-weak cold">近期退燒 Top 5</div><div>{cold_html}</div></div>
  <div><div class="status-col-head badge-weak foreign">外資悄悄佈局 Top 5</div><div>{foreign_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但外資連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head badge-weak trust">投信悄悄佈局 Top 5</div><div>{trust_html}</div>
    <div class="status-col-note">股價還沒明顯反應（±{_STEALTH_PRICE_FLAT_MAX}%內）但投信連買≥{_STEALTH_STREAK_MIN}天</div></div>
  <div><div class="status-col-head badge-weak volume">量能異常 Top 5</div><div>{volume_html}</div>
    <div class="status-col-note">今日量能≥{_VOL_ANOMALY_RATIO_MIN}x5日均量，但股價還沒明顯反應（±{_VOL_ANOMALY_PRICE_FLAT_MAX}%內）</div></div>
</div>"""
```

Note: `.status-col-head` already has its own color-coded `border-bottom` styling (`.status-col-head.hot{color:var(--heat-hot);border-color:var(--heat-hot)}` etc.) — adding `badge-weak` alongside it will make `badge-weak`'s `border:1px dashed` and `background:transparent` rules apply too since both are classes on the same element; the existing `.status-col-head.hot` color rule still wins for `color`/`border-color` specifically (same specificity, but `.status-col-head.hot` is a more specific 2-class combinator matching the SAME element as `.badge-weak`, so CSS cascade order in the stylesheet decides ties — since `.status-col-head.*` rules are defined AFTER `.badge-weak` in `_CSS`, they win for the properties they set, while `badge-weak`'s `border`/`background`/`padding`/`font-size` still apply since `.status-col-head.hot` doesn't set those). This is intentional — keep the existing 5 status-col-head color variants but make them all visually "quieter" via badge-weak's shared border/background/sizing rules layered underneath.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "sector_recap_html" -v`
Expected: PASS for the new tests. Some pre-existing tests (see below) will need updating.

- [ ] **Step 5: Fix pre-existing tests that assumed turning_points/rank_crossings were rendered by `_sector_recap_html()`**

Run: `python -m pytest tests/test_index_generator.py -v 2>&1 | grep FAIL`

At minimum, `test_generate_renders_rank_crossings_section_in_sector_recap` (around line 1517) will fail — it currently asserts rank-crossing content appears when `generate()` is called, checking for it near the sector-recap area. Open this test and update it: rank crossings now appear via `_today_week_movements_html()`'s output inside `generate()`'s page, not inside `_sector_recap_html()`'s section. Rename the test to `test_generate_renders_rank_crossings_section_in_today_week_movements` and update its assertions to check the crossing content appears in the page at all (via `generate()`'s full output), without asserting it's specifically inside the `族群近況` section. Example of the corrected test body:

```python
def test_generate_renders_rank_crossings_section_in_today_week_movements(tmp_path):
    """排名進出榜現在渲染在「今日/本週異動」區塊(本週層)，不在族群近況——見docs/adr/0006。"""
    meta_perf = [
        {"meta_name": "散熱", "avg_change_pct": 1.0, "up_count": 1, "down_count": 0, "flat_count": 0},
    ]
    universe_df = pd.DataFrame([{"stock_id": "1", "stock_name": "股票一", "meta_sector": "散熱"}])
    prices_df = pd.DataFrame([{"stock_id": "1", "change_pct": 1.0, "close": 100.0}])
    rank_history = {
        "散熱": {"weekly_ranks": [20, 3], "weekly_returns": [-2.0, 5.0],
                "in_top10_this_week": True, "consecutive_weeks_in_top10": 1,
                "last_top10_week_index": None, "last_top10_rank": None},
    }

    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 27), meta_perf, universe_df, {}, {}, prices_df, {},
             rank_history=rank_history, output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "排名進出榜" in html
    assert "散熱" in html
```

(Keep the original test's assertions on the exact wording/threshold logic if this codebase's existing test had more specific checks — read the actual current test before replacing it, and preserve any assertion that's still valid; only change what's about WHERE the content renders.)

- [ ] **Step 6: Run the full test file**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: all pass, no FAILs. Fix any other test broken by this restructuring the same way — update the assertion to match the new architecture (content moved, not deleted), never delete a test's coverage just to make it pass.

- [ ] **Step 7: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "refactor(index): 族群近況移除轉折點/排名進出榜(已搬進今日本週異動),剩5類套badge-weak"
```

## Context

Task 9 of 12. This removes the now-DUPLICATE rendering of `turning_points`/`rank_crossings` from `_sector_recap_html()` — Task 8 already built `_today_week_movements_html()` which renders the same data. `build_sector_recap()` (the data function) is still untouched — it still computes and returns `turning_points`/`rank_crossings` in its dict; `generate()` (Task 10) will read them from the SAME `recap` dict and pass to `_today_week_movements_html()` instead of (or in addition to, until Task 10 lands) `_sector_recap_html()`.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If `_sector_recap_html`'s current full body differs from what's shown (e.g. due to work landing between Task 6 and this task), read the actual current function before editing — don't force a mismatched find/replace.

## Your Job

1. Write the 2 new tests, confirm they fail
2. Remove the turning/rankmove local variables and their rendering from the return statement, add `badge-weak` to status-col-head elements
3. Confirm the 2 new tests pass
4. Run the full file, fix `test_generate_renders_rank_crossings_section_in_sector_recap` (rename + update, per Step 5) and any other test broken by the restructuring
5. Confirm full suite green
6. Commit
7. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`. Don't touch `build_sector_recap()`.

## When You're in Over Your Head

STOP and escalate if fixing broken tests requires understanding requirements this task doesn't cover, or if more than 2-3 pre-existing tests need updates (that would suggest the restructuring has wider-reaching effects than expected — flag it rather than pushing through).

## Before Reporting Back: Self-Review

- Does `_sector_recap_html()`'s output genuinely no longer contain `turning-wrap`/`rankmove-wrap` content?
- Do all 5 remaining `status-col-head` elements have `badge-weak` added?
- Did you UPDATE (not delete) any pre-existing test whose assumptions changed, preserving its original intent (verify the data still renders somewhere) while fixing its location assumption?
- Is `build_sector_recap()` completely untouched?

## Report Format

Same format as Task 1.

---

### Task 10: Rewire `generate()`'s HTML body — new page order, drop secondary-row

**Files:**
- Modify: `export/index_generator.py:1198-1341` (`generate()` — HTML body assembly + `_today_week_movements_html` call wiring)
- Test: `tests/test_index_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_renders_heatgrid_then_full_width_today_week_movements_then_sector_recap(tmp_path):
    """新頁面順序：①熱區格(滿版)→②今日/本週異動(滿版,新)→③族群近況(滿版,瘦身)。
    不再有secondary-row二欄並排(Wave1 Task9的產物，這次拆掉，因為②③都改滿版寬)。"""
    output_path = tmp_path / "index.html"
    generate(date(2026, 8, 27), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    heatgrid_pos = html.index('id="heatgrid"')
    movements_pos = html.index('<h2>今日/本週異動</h2>')
    recap_pos = html.index('<h2>族群近況</h2>')

    assert heatgrid_pos < movements_pos < recap_pos, "順序要是熱區格→今日本週異動→族群近況"
    assert 'class="secondary-row"' not in html, "二欄並排容器這次拆掉了，②③都改滿版"


def test_generate_passes_margin_divergence_and_limit_up_into_today_week_movements(tmp_path):
    """generate()要把margin_divergence/limit_up_results透傳給_today_week_movements_html()，
    確認資料真的接到頁面輸出裡（不只是Task2測過參數簽章本身）。"""
    output_path = tmp_path / "index.html"
    margin_divergence = {"bearish": [{"stock_id": "9999", "stock_name": "測試背離股", "meta_sector": "測試族群",
                                       "margin_pct": 5.2, "price_pct": -3.1, "days": 10, "close": 30.5}],
                          "bullish": [], "days_used": 10}
    limit_up_results = [{"stock_id": "8888", "stock_name": "測試漲停股", "meta_sector": "測試族群",
                          "close": 100.0, "change_pct": 9.9, "volume": 5000,
                          "limit_up_streak": 4, "volume_declining_streak": None,
                          "breakout_volume_confirmed": None}]

    generate(date(2026, 8, 27), _sample_meta_perf(), _sample_universe_df(), {}, {}, _sample_prices_df(), {},
             margin_divergence=margin_divergence, limit_up_results=limit_up_results,
             output_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "測試背離股" in html
    assert "測試漲停股" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_index_generator.py -k "renders_heatgrid_then_full_width or passes_margin_divergence_and_limit_up_into" -v`
Expected: FAIL — page still has `secondary-row`, still shows 異動族群/族群近況 in the old order, and `margin_divergence`/`limit_up_results` aren't rendered anywhere yet (Task 2 only accepts them, doesn't use them).

- [ ] **Step 3: Rewire the HTML body**

In `export/index_generator.py`, inside `generate()`, find the calls that build the page's data (right after `recap = build_sector_recap(...)`):

```python
    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows, cum_data)
    anomaly_cards = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows, rank_history)
```

Change to (add the new section's assembled HTML as a local variable, computed right after `recap`):

```python
    cards = build_heatgrid_cards(meta_perf, meta_signals, meta_chips, heatgrid_windows, cum_data)
    anomaly_cards = find_anomaly_cards(meta_perf, meta_signals, heatgrid_windows)
    recap = build_sector_recap(cards, heatgrid_windows, rank_history)
    today_week_movements_html = _today_week_movements_html(
        anomaly_cards, recap["today_breakout"], margin_divergence, limit_up_results,
        recap["turning_points"], recap.get("rank_crossings", {"just_in": [], "just_out": []}),
    )
```

Now find the `<main>` body (currently, after Wave 1's Task 9 reorder):

```python
<main id="main-content">
{_market_regime_html(market_regime)}
{_vol_turnover_html(vol_turnover_signals)}
<div class="section-head"><h2>族群排行</h2><span class="count">今日漲跌% ・{len(cards)} 個族群</span></div>
<div class="section-rule"></div>
<div class="section-sub">動能狀態標籤是這版的重點：不是只看今日漲跌，而是綜合「連漲天數＋本週比上週是否加速」判斷這個族群現在的動能還在不在。</div>
<div class="tier-legend">
  <span><span class="dot" style="background:var(--tier-super)"></span>超強＝多頭排列+持續加速</span>
  <span><span class="dot" style="background:var(--tier-strong)"></span>強＝多頭排列，動能穩定</span>
  <span><span class="dot" style="background:var(--tier-mid)"></span>整理＝方向不明</span>
  <span><span class="dot" style="background:var(--tier-weak)"></span>弱＝動能減弱中</span>
  <span><span class="dot" style="background:var(--tier-superweak)"></span>超弱＝轉弱+連跌</span>
</div>
<div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
<div class="legend-note">動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

<div class="secondary-row">
  <div class="secondary-col">
    <div class="section-head"><h2>異動族群</h2><span class="count">{len(anomaly_cards)} 檔符合</span></div>
    <div class="section-sub">「現在正在發生」的瞬間訊號——爆量排名跳動、或連續多週噴出。跟旁邊「族群近況」不同：這裡是單日事件，族群近況是週度趨勢。</div>
    <div class="anomaly-wrap"><div class="anomaly-strip">{_anomaly_cards_html(anomaly_cards)}</div></div>
  </div>
  <div class="secondary-col">
    {_sector_recap_html(recap)}
  </div>
</div>
</main>
```

Change to:

```python
<main id="main-content">
{_market_regime_html(market_regime)}
{_vol_turnover_html(vol_turnover_signals)}
<div class="section-head"><h2>族群排行</h2><span class="count">今日漲跌% ・{len(cards)} 個族群</span></div>
<div class="section-rule"></div>
<div class="section-sub">動能狀態標籤是這版的重點：不是只看今日漲跌，而是綜合「連漲天數＋本週比上週是否加速」判斷這個族群現在的動能還在不在。</div>
<div class="tier-legend">
  <span><span class="dot" style="background:var(--tier-super)"></span>超強＝多頭排列+持續加速</span>
  <span><span class="dot" style="background:var(--tier-strong)"></span>強＝多頭排列，動能穩定</span>
  <span><span class="dot" style="background:var(--tier-mid)"></span>整理＝方向不明</span>
  <span><span class="dot" style="background:var(--tier-weak)"></span>弱＝動能減弱中</span>
  <span><span class="dot" style="background:var(--tier-superweak)"></span>超弱＝轉弱+連跌</span>
</div>
<div class="heatgrid" id="heatgrid">{_heatgrid_html(cards)}</div>
<div class="legend-note">動能狀態標籤（超強/強/整理/弱/超弱）是族群層級獨立算的草案規則（連漲天數+本週比上週加速度），跟個股層級或觀察分頁面的五級分類不共用計算依據，門檻未經回測驗證。「近5日→前5日」是滾動5個交易日的複利累積漲跌幅，不是自然日曆週。</div>

{today_week_movements_html}

{_sector_recap_html(recap)}
</main>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_index_generator.py -k "renders_heatgrid_then_full_width or passes_margin_divergence_and_limit_up_into" -v`
Expected: PASS.

- [ ] **Step 5: Run the full test file**

Run: `python -m pytest tests/test_index_generator.py -q`
Expected: all pass. `test_generate_renders_heatgrid_before_secondary_row_with_anomaly_and_recap_side_by_side` (Wave 1 Task 9's test, asserting `.secondary-row` exists and anomaly/recap sit side-by-side) will now FAIL — this is expected, since this task deliberately removes that layout. Rename/replace it: delete this test entirely and rely on the new `test_generate_renders_heatgrid_then_full_width_today_week_movements_then_sector_recap` (written in Step 1 of this task) as its replacement — it covers the same "is the page ordered correctly" concern for the new architecture. Note in the commit message that this test was intentionally superseded, not silently dropped.

Also remove the now-dead `.secondary-row`/`.secondary-col` and their scoped override rules (`.secondary-row .section-head`, `.secondary-row .section-rule`, `.secondary-row .section-sub`, `.secondary-row .anomaly-wrap`, `.secondary-row .role-note`, `.secondary-row .status-cols`, `.secondary-row .turning-wrap`, `.secondary-row .rankmove-wrap`) from `_CSS` — find this block (added in Wave 1 Task 9, right after `.rankmove-item:last-child{border-bottom:none}`):

```css
.secondary-row{display:grid;grid-template-columns:1fr 1fr;gap:24px;padding:0 26px;align-items:start}
@media (max-width:900px){.secondary-row{grid-template-columns:1fr}}
.secondary-row .section-head{padding:20px 0 8px}
.secondary-row .section-rule{margin:0 0 4px}
.secondary-row .section-sub{padding:0 0 14px}
.secondary-row .anomaly-wrap{margin:0}
.secondary-row .role-note{margin:0 0 20px}
.secondary-row .status-cols{padding:0}
.secondary-row .turning-wrap{margin:20px 0 0}
.secondary-row .rankmove-wrap{margin:20px 0 0}
```

Delete this entire block. Since `.section-head`/`.section-rule`/`.section-sub`/`.anomaly-wrap`/`.role-note`/`.status-cols` are used directly (not nested under `.secondary-row`) by the new full-width `_today_week_movements_html()`/`_sector_recap_html()` output, their BASE (non-scoped) CSS rules already apply the original `26px`-gutter spacing correctly with no extra work — that's why Task 7 already dropped `.anomaly-wrap`'s own `margin:0 26px` (it'll pick up whatever the base rule says once `.secondary-row .anomaly-wrap{margin:0}`'s override is gone). Verify visually-relevant base rules still exist for `.anomaly-wrap` — if `.anomaly-wrap`'s base rule was `position:relative;margin:0 26px` before Task 7 removed the margin, and this task removes the `.secondary-row .anomaly-wrap{margin:0}` override, `.anomaly-wrap` will have NO horizontal margin at all now (since Task 7's edit deleted it from the base rule too, anticipating it'd sit inside a full-width parent). Confirm `_today_week_movements_html()`'s CSS containers (`.tw-today-grid`, etc.) or the outer `<main>` provide the page's `26px` gutter some other way — check the rendered HTML doesn't end up with the anomaly cards touching the page edge. If it does, add `padding:0 26px` to `.tw-today-grid` in `_CSS` to restore the gutter at the new container level instead of the old `.anomaly-wrap` level.

- [ ] **Step 6: Commit**

```bash
git add export/index_generator.py tests/test_index_generator.py
git commit -m "feat(index): 頁面改新順序(熱區格→今日本週異動→族群近況),拆掉secondary-row二欄"
```

## Context

Task 10 of 12. This is the final assembly step — wires `_today_week_movements_html()` (Task 8) into `generate()`'s page output, in place of the old side-by-side `異動族群`/`族群近況` layout from Wave 1. All three sections (熱區格/今日本週異動/族群近況) are now full-width, stacked vertically, in that order.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Before You Begin

If `generate()`'s current `<main>` body or the `.secondary-row` CSS block differ from what's shown, read the actual current content before editing.

## Your Job

1. Write both tests, confirm they fail
2. Add the `today_week_movements_html` local variable, rewire the `<main>` body
3. Remove the dead `.secondary-row`/`.secondary-col` CSS block
4. Confirm the new tests pass
5. Run the full test file; handle the now-obsolete Wave-1 secondary-row test per Step 5's instructions (delete it, note in commit message it's superseded)
6. Verify the `26px` page gutter is preserved visually in the new layout (check rendered HTML structure, not just that tests pass) — add `padding:0 26px` to `.tw-today-grid` if the gutter was lost
7. Commit
8. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` and `tests/test_index_generator.py`.

## When You're in Over Your Head

STOP and escalate if `generate()`'s current HTML body structure differs substantially, or if you're unsure whether the page gutter is actually preserved (describe what you checked and what you're unsure about rather than guessing).

## Before Reporting Back: Self-Review

- Is the page order genuinely 熱區格→今日/本週異動→族群近況 (verified by the test, not just visual inspection of the source)?
- Is `.secondary-row`/`.secondary-col` genuinely gone from both the HTML template and the CSS block?
- Did you check whether the `26px` gutter survives for the new sections (not just trust that it does)?
- Was the obsolete Wave-1 test explicitly removed with a commit message noting why (not silently deleted with no trace)?

## Report Format

Same format as Task 1.

---

### Task 11: Update `CONTEXT.md`/spec source-of-truth cross-references + docstring cleanup pass

**Files:**
- Modify: `export/index_generator.py` (docstring/comment consistency check only — no behavior change)

- [ ] **Step 1: Read through the full diff of Tasks 1-10 for internal consistency**

Run: `git log --oneline cca4965..HEAD` (or the actual SHA of the "建立CONTEXT.md" commit if it differs — find it via `git log --oneline --grep="建立CONTEXT.md"`) to list every commit in this wave so far.

Run: `git diff <first-wave2-task-commit>..HEAD -- export/index_generator.py | head -400` and read the accumulated diff.

- [ ] **Step 2: Fix any leftover stale references**

Check specifically for:
- Any remaining docstring/comment in `export/index_generator.py` that still describes 異動族群/族群近況 as being in a `secondary-row` two-column layout (should now describe the new 3-section full-width stack).
- The module-level docstring at the top of `export/index_generator.py` (lines 1-17) — if it references the old page structure or Wave 1's spec file only, add a one-line pointer to this wave's decisions too:

Find:
```python
視覺/互動設計：docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md
技術落地設計：docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md
```

Change to:
```python
視覺/互動設計：docs/superpowers/specs/2026-07-15-sector-overview-heatmap-redesign.md
技術落地設計：docs/superpowers/specs/2026-07-22-sector-overview-heatmap-implementation-design.md
第二波（信心分層+今日/本週異動合併）：CONTEXT.md、docs/adr/0005、docs/adr/0006
```

- Confirm no code comment still says "族群近況＝6大類" anywhere (should say 5大類 now — grep for "6大類" and "6 大類" across `export/index_generator.py`).

- [ ] **Step 3: Run this check**

Run: `python -c "import export.index_generator" && grep -n "6大類\|6 大類\|secondary-row\|secondary-col" export/index_generator.py`
Expected: import succeeds with no error; grep finds NOTHING (empty output) — if it finds matches, fix them (they're stale references from before this wave's restructuring).

- [ ] **Step 4: Run the full test suite once more**

Run: `python -m pytest -q`
Expected: same pass count as after Task 10, no regressions from this doc-only cleanup pass.

- [ ] **Step 5: Commit (only if Step 2 found something to fix)**

```bash
git add export/index_generator.py
git commit -m "docs(index): 清理殘留的舊版6大類/secondary-row註解引用"
```

If Step 2 found nothing to fix, skip the commit — report `DONE` with a note that no stale references were found.

## Context

Task 11 of 12. This is a lightweight consistency-check task, not a feature task — after 9 tasks of restructuring, this catches any docstring/comment that still describes the OLD architecture (pre-this-wave), which would confuse a future reader. No behavior changes, purely comment/docstring hygiene.

You are on branch `master`. **DO NOT sync any other git worktree.**

## Your Job

1. Read the accumulated diff for this wave
2. Grep for stale references (`6大類`, `secondary-row`, `secondary-col`) and fix any found
3. Update the module docstring's spec-pointer list
4. Run the import + grep check, confirm clean
5. Run full suite
6. Commit only if something was actually fixed
7. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

Only touch `export/index_generator.py` if fixes are needed. No test changes expected (this task doesn't change behavior).

## When You're in Over Your Head

STOP and escalate if the grep finds something you're not sure how to fix without changing behavior (e.g. if `secondary-row` shows up somewhere unexpected that might indicate Task 10 didn't fully remove it — re-verify Task 10's changes rather than guessing).

## Before Reporting Back: Self-Review

- Did you actually run the grep check and see empty output before declaring done?
- Did you avoid making any change beyond comments/docstrings (check `git diff` shows no logic changes)?

## Report Format

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What (if anything) you fixed
- Grep check result (paste the actual empty/non-empty output)
- Test suite result
- Commit SHA (or "no commit needed" if nothing to fix)
- Self-review findings

---

### Task 12: Full regression + debug-tasks.md handoff + debug worktree sync

**Files:** none (verification + docs only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q` from `C:\Users\Cody\Desktop\tw-sector-tracker`
Expected: all pass, 0 failures. Note the exact count for the handoff doc below.

- [ ] **Step 2: Smoke-test `generate()` end-to-end with the two new signals populated**

```bash
python -c "
from datetime import date
import pandas as pd
from export.index_generator import generate

meta_perf = [{'meta_name': 'AI晶片', 'avg_change_pct': 5.66, 'up_count': 18, 'down_count': 3, 'flat_count': 0}]
universe_df = pd.DataFrame([{'stock_id': '2330', 'stock_name': '台積電', 'meta_sector': 'AI晶片'}])
prices_df = pd.DataFrame([{'stock_id': '2330', 'close': 1080.0, 'change_pct': 3.2}])
margin_divergence = {'bearish': [{'stock_id': '1101', 'stock_name': '台泥', 'meta_sector': '水泥', 'margin_pct': 5.2, 'price_pct': -3.1, 'days': 10, 'close': 30.5}], 'bullish': [], 'days_used': 10}
limit_up_results = [{'stock_id': '2330', 'stock_name': '台積電', 'meta_sector': 'AI晶片', 'close': 1080.0, 'change_pct': 9.9, 'volume': 50000, 'limit_up_streak': 2, 'volume_declining_streak': True, 'breakout_volume_confirmed': True}]
generate(date(2026, 8, 27), meta_perf, universe_df, {}, {}, prices_df, {},
         margin_divergence=margin_divergence, limit_up_results=limit_up_results,
         output_path='wave2_smoke.html')
import os
print('OK — wrote wave2_smoke.html, size:', os.path.getsize('wave2_smoke.html'), 'bytes')
html = open('wave2_smoke.html', encoding='utf-8').read()
assert '今日/本週異動' in html
assert '台泥' in html
assert 'badge-weak' in html
assert 'secondary-row' not in html
print('OK — content checks passed')
os.remove('wave2_smoke.html')
"
```

Expected: prints both `OK` lines, no traceback, no leftover `wave2_smoke.html` file (cleaned up by the script itself).

- [ ] **Step 3: Update `debug-tasks.md`**

Append this entry to the TOP of `debug-tasks.md` (repo root), following the project's established template:

```markdown
## [2026-08-27] 首頁（index.html）第二波大改 — 12個Task全部完成

### 改了什麼
- 異動檔案：export/index_generator.py, main.py, tests/test_index_generator.py,
  CONTEXT.md（新建）, docs/adr/0005-confidence-tiering-across-index-page.md（新建）,
  docs/adr/0006-index-reuses-cross-page-signal-functions.md（新建）
- 邏輯說明：
  1. 信心分層：熱區格五級動能/溫度標籤、族群近況剩下5類的標籤，全部改用badge-weak
     樣式（虛線框+透明底+「（草案）」字樣），跟排名/%/連漲跌天數等真數字視覺區分開
  2. 新合併區塊「今日/本週異動」取代原本並排的「異動族群」+「族群近況」局部內容：
     - 今日層（4項，真數字）：異動族群、今日爆發（原本在族群近況）、融資背離警示
       （NEW，來自get_margin_divergence()）、連續漲停鎖死（NEW，來自
       scan_consecutive_limit_up()）
     - 本週層（2項並排，草案樣式）：轉折點、排名進出榜（原本在族群近況，維持獨立
       不合併，見docs/adr/0003/0006）
  3. 族群近況瘦身成5大類（升溫/退燒/外資/投信/量能），拆掉跟今日/本週異動重疊的部分
  4. 頁面改滿版三段式（熱區格→今日/本週異動→族群近況），拆掉Wave1的secondary-row
     二欄並排佈局

### 資料來源相關（如有異動）
- 上市資料（TWSE）：無異動
- 上櫃資料（TPEx）：無異動
- `get_margin_divergence()`/`scan_consecutive_limit_up()` 都是既有函式（原本只服務
  momentum.html/patterns.html），這次是第一次也接給index.html用，沒有新增資料源，
  純粹是「同一份既有資料多一個頁面引用」（見docs/adr/0006）

### 請 Debugger 驗證
- [ ] 主要功能邏輯正確（尤其：`_today_week_movements_html()` 今日層/本週層的資料
      對應是否正確、`_margin_divergence_html()`/`_limit_up_html()` 的bearish/bullish
      跟三態旗標(True/False/None)是否正確渲染不搞混）
- [ ] 上市/上櫃資料來源沒有混用
- [ ] 沒有影響其他模組（chips.html/momentum.html/patterns.html 沒被這批改動觸碰，
      `scan_consecutive_limit_up()`/`get_margin_divergence()` 是唯讀呼叫，兩邊呼叫端
      互不影響）
- [ ] **實際跑一次 `python main.py`，用瀏覽器打開重新產生的 `docs/index.html` 確認**
      （這是上一波Debugger報告點出的唯一未閉環項目，這次也要做——不能只看程式邏輯）：
  - 熱區格五級動能/溫度標籤是不是虛線草案樣式，不是實色徽章
  - 「今日/本週異動」區塊順序：今日層(異動族群卡片grid+今日爆發+融資背離+連續漲停)
    在上、本週層(轉折點+排名進出榜並排)在下，本週層是虛線草案樣式
  - 族群近況只剩5大類，不再有「今日爆發」，也沒有轉折點/排名進出榜
  - 整頁三段都滿版寬，沒有並排二欄的殘留
  - 深色/淺色主題切換，badge-weak在兩個主題下都看得清楚（不是只深色能看）

### 特別注意
- `docs/index.html` 是 generated artifact，不要手動編輯——下次 `python main.py` 跑過會被
  `export/index_generator.py` 重新產生的版本覆蓋。
- 這波刻意不動配色/字型系統本身（見docs/adr/0005背景說明：曾比較過金色+紫色、精煉
  終端機綠兩個新方向，最後決定維持現有系統）。
- 異動族群/族群近況/今日爆發的門檻數值本身（vol_ratio/排名跳動門檻等）依然沒動，
  回測驗證仍是獨立後續任務。
```

- [ ] **Step 4: Commit the debug-tasks.md update**

```bash
git add debug-tasks.md
git commit -m "docs(debug-tasks): 交接首頁第二波改版12個Task"
```

- [ ] **Step 5: Sync to debug worktree**

```bash
cd ../tw-sector-tracker-debug
git status --short
```

If clean, run `git merge master`. If not clean, STOP and report — do not overwrite uncommitted Debugger work; ask before proceeding.

## Context

Task 12 of 12, the final task of this plan. Mirrors Wave 1's final task exactly. All 11 prior tasks are done, reviewed, and committed to `master`.

You are on branch `master` in the main working tree at `C:\Users\Cody\Desktop\tw-sector-tracker`. This is the ONE task in this plan authorized to touch `../tw-sector-tracker-debug` — every prior task was explicitly told not to.

**Do NOT push to origin** — per CLAUDE.md, unvalidated code waits for the Debugger's ✅ in `bug-reports.md` before anything gets pushed.

## Before You Begin

If the test suite has unexpected failures unrelated to this wave's changes, or the debug worktree isn't clean, stop and report rather than forcing through.

## Your Job

1. Run full suite, note exact count
2. Run the smoke test, confirm both OK lines print
3. Write and commit the debug-tasks.md handoff entry
4. Sync `../tw-sector-tracker-debug` (check clean, then merge)
5. Report back

Work from: `C:\Users\Cody\Desktop\tw-sector-tracker`

## Code Organization

This task doesn't touch source code — only `debug-tasks.md` and verification commands.

## When You're in Over Your Head

STOP and escalate if: the test suite has unexpected failures, the debug worktree has uncommitted changes, or the merge produces conflicts you're unsure how to resolve (per CLAUDE.md, conflicts in append-only files like `debug-tasks.md`/`bug-reports.md` should keep BOTH sides' content).

## Before Reporting Back: Self-Review

- Did you confirm the exact final test count?
- Does the debug-tasks.md entry accurately summarize all 11 implementation tasks?
- Did the debug worktree merge complete cleanly?
- Did you avoid pushing anything to `origin`?

## Report Format

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- Test suite results (exact counts)
- Smoke-test result
- debug-tasks.md commit SHA
- Debug worktree merge result
- Self-review findings

---

## Plan Self-Review Notes

- **Spec coverage:** ADR 0005 (confidence tiering) → Tasks 3, 9. ADR 0006 (cross-page signal reuse + merged section respecting ADR 0003) → Tasks 1, 2, 4, 5, 8, 10. CONTEXT.md's "今日/本週異動" full composition (異動族群/今日爆發/融資背離/連續漲停/轉折點/排名進出榜) → Tasks 6, 7, 8, 10. Color/font unchanged → no task touches `--bg`/`--accent`/`--sans`/`--serif`/`--mono` token definitions anywhere in this plan (verified by scanning: no task's Find/Change blocks reference the `:root{...}` CSS variable definitions).
- **Discovered gap fixed before writing the plan:** `CONTEXT.md`'s first draft said 族群近況 keeps "5大類" but omitted that 今日爆發 (a 6th pre-existing category) needed explicit relocation — caught and confirmed with the user (commit `7c2179c`) before task-writing began, so Task 6 correctly extracts it rather than silently dropping it.
- **Type/name consistency check:** `margin_divergence`/`limit_up_results` spelled identically from Task 1 (main.py fetch) → Task 2 (generate() signature) → Task 8 (`_today_week_movements_html()` params) → Task 10 (wiring). `_today_breakout_html`, `_margin_divergence_html`, `_limit_up_html`, `_today_week_movements_html` function names consistent across every task that defines or calls them.
- **No placeholders:** every step has literal code, not descriptions of code.
