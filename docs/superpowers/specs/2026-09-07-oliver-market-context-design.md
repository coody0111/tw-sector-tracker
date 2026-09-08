# Oliver Market Context — TAIEX Weekly Gate

## Goal

Add a higher-timeframe TAIEX context before stock-level Oliver analysis. The market context explains whether the index is leading, correcting, extended, or transitioning and conservatively gates stock action states. It is research context, not an exposure command or trading order.

## Public seams

1. `fetch_taiex_history(end_date, months=4)` returns de-duplicated, ascending official FMTQIK daily closes through `end_date`.
2. `analyze_market_history(history, as_of=None)` returns a point-in-time weekly structure and one compact market action.
3. `apply_market_context(stock_analysis, market_context)` preserves the stock's raw action as `stock_action_state`, attaches market context, and returns the gated `action_state`.
4. `watchlist_generator.generate(..., market_context=...)` shows one market state and one next action above the stock cards.

These are the agreed test seams for this continuation.

## Source-derived behavior

- Start with the index and weekly chart; higher timeframes supersede lower timeframes.
- Report location versus the 10-week EMA, base/consolidation, extension, correction, transition, and uncertainty.
- During corrections reduce trading intensity, but continue watching relative-strength leaders that may move before the index completes a Wedge Pop.
- A one-day rebound does not convert a bearish weekly context into a confirmed reversal.

## Project interpretation

Map the existing weekly structure engine into an index phase:

| Weekly structure | Market phase | Market action |
|---|---|---|
| bullish | leading | normal-research |
| extended | leading-extended | avoid-chasing |
| correction | correcting | selective |
| bearish | correcting | defensive |
| base | transitioning | wait-for-confirmation |
| transition | transitioning | wait-for-confirmation |
| unknown | unknown | unknown |

Numeric EMA/base/extension thresholds remain the unverified project parameters already defined in `2026-09-04-oliver-structure-analysis-design.md`.

## Stock action gate

- `unknown` market context does not invent permission; stock `research` becomes `wait-for-confirmation`, while existing `reduce-risk` remains unchanged.
- `defensive`: existing deterioration remains `reduce-risk`; positive stock setups are capped at `wait-for-confirmation` so potential leaders remain visible.
- `selective`, `avoid-chasing`, or `wait-for-confirmation`: stock `research` is capped at `wait-for-confirmation`; `watch` remains `watch`; risk warnings remain `reduce-risk`.
- `normal-research`: preserve the stock action.
- Never emit `buy`, `sell`, or `short`.

## Data and failure behavior

- FMTQIK returns one calendar month per request; fetch four distinct months to provide at least 50 trading sessions under normal conditions.
- Parse with the existing official-response parser and preserve its WAF/error semantics.
- De-duplicate by date, sort ascending, and discard rows after `end_date`.
- Any missing/blocked/short history produces `unknown` market context and must not block index/watchlist generation.
- Do not substitute the electronic-stock universe breadth series for TAIEX and call it the index.

## Acceptance criteria

- Deterministic tests cover monthly fetch merge, point-in-time filtering, bullish/extended/bearish/base market mapping, insufficient data, and stock action gating.
- Watchlist page displays Market phase, weekly structure, close versus 10-week EMA, and one market action.
- `main.py` passes the same `trade_date` to market and stock analyses.
- Existing Oliver/watchlist/index/main/TAIEX tests remain green.

## Deferred

- TAIEX OHLC-based daily Wedge Pop/Drop (FMTQIK currently provides close, not OHLC).
- Historical persistence/cache, breadth-history confirmation, relative-strength ranking, Top Dogs, and threshold calibration.
