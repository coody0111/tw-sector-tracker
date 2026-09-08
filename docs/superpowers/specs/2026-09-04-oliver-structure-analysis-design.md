# Oliver Kell Structure Analysis — Watchlist Slice

## Goal

Replace the watchlist placeholders with conservative, inspectable weekly structure and daily price-cycle context derived only from OHLCV data available at the analysis date. The output is research/risk context, not an order or a claim of predictive edge.

## Public seams

1. `analyze_price_history(history, as_of=None)` accepts one stock's dated OHLCV history and returns the complete Oliver analysis record.
2. `calc_oliver_market_structure(universe_df, db_path, as_of)` loads point-in-time history once and returns `{stock_id: analysis}`.
3. `watchlist_generator.generate(..., oliver_analysis=...)` embeds and displays the analysis without changing user-owned localStorage state.

## Source-derived concepts

- Weekly chart provides the higher-timeframe trend/context and location versus the 10-week EMA.
- Daily chart provides the intermediate price cycle: Reversal Extension, Wedge Pop, EMA Crossback, Base N' Break, Exhaustion Extension, Wedge Drop, and bearish counterparts.
- A Pivotal Point must include a trigger area and invalidation; bearish deterioration is a warning, not an automatic short instruction.
- Stops move toward lower risk and never widen. This slice cannot manage a stop because it has no position state.

## Project parameters — unverified until historical testing

- Minimum history: 50 daily bars and 10 weekly bars for weekly structure; 20 daily bars for daily context.
- Daily extension watch/risk: 8% from the 10 EMA; extreme: 15%.
- Weekly extension: 15% above the 10-week EMA.
- Weekly base: latest close within 2% of the 10-week EMA and the EMA changes no more than 0.5% over the comparison interval.
- Base/tight range: at most 12% over the comparison window.
- Break confirmation volume: at least 1.5× the preceding 20-session average.
- Defined-risk pivotal point: trigger-to-invalidation distance at most 8%.
- EMA Crossback sequence lookback: 30 sessions; the latest bar must be the first retest after crossing both 10/20 EMA, with a 1% EMA-zone touch tolerance.

Every generated result must identify these as project parameters, not Oliver's quoted numeric rules.

## Classification contract

- `weekly_structure`: `bullish`, `bearish`, `correction`, `base`, `extended`, `transition`, or `unknown`.
- `daily_cycle`: an explicit cycle label or `no-clear-cycle` / `unknown`.
- `ema-crossback-bullish` requires prior downside extension, a later cross above both EMAs, and the first pullback into the EMA zone while closing above it. The bearish form mirrors this sequence after upside extension and a cross below both EMAs.
- `extension_state`: `normal`, `risk`, or `extreme`, kept separate from reversal confirmation.
- `reversal_state`: `none`, `watch`, `confirmed`, or `failed`; do not collapse clues and confirmations.
- `pivotal_point`: `defined` only when both trigger and invalidation are present and ordered coherently; otherwise `none`.
- `risk_state`: `normal`, `defined-risk`, `avoid-chasing`, `deterioration-warning`, or `unknown`.
- `action_state`: `research`, `watch`, `wait-for-confirmation`, `reduce-risk`, or `unknown`; never `buy`, `sell`, or `short`.

## Determinism and fail-soft behavior

- Sort by date, de-duplicate dates, discard invalid/non-positive closes, and filter all rows after `as_of` before computing indicators.
- Never use a future bar in a historical result.
- Missing columns, insufficient history, or database errors return explicit `unknown` output without blocking generation of the rest of the site.
- Numeric values embedded in HTML must be finite or `null`; visible text must use escaped/text rendering.

## Acceptance criteria

- Synthetic tests cover bullish weekly structure, insufficient history, downside extension plus confirmed reversal, point-in-time filtering, and a defined Pivotal Point.
- Watchlist cards show weekly structure, daily cycle, extension/reversal detail, Pivotal Point, risk state, action state, evidence, and uncertainty.
- `main.py` calculates the universe analysis once and passes it to the watchlist generator.
- Existing index and watchlist tests remain green.

## Explicitly deferred

- Index-level market structure, relative-strength ranking, Top Dogs scoring, hourly/15-minute execution, position sizing, backtest claims, and automated trade execution.
- Calibrating the project thresholds; that requires historical replay, out-of-sample evaluation, and human chart audit.
