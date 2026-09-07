"""Point-in-time Oliver Kell-inspired structure analysis.

Numeric thresholds in this module are project parameters, not quoted Oliver rules.
The output is research context and never an automated trade instruction.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

import pandas as pd


PARAMETER_STATUS = "unverified-project-parameters"
MIN_WEEKLY_DAILY_BARS = 50
WEEKLY_EMA_SPAN = 10
WEEKLY_EXTENSION_PCT = 15.0
WEEKLY_BASE_EMA_DISTANCE_PCT = 2.0
WEEKLY_BASE_EMA_SLOPE_PCT = 0.5
MIN_DAILY_BARS = 20
DAILY_EXTENSION_RISK_PCT = 8.0
DAILY_EXTENSION_EXTREME_PCT = 15.0
BASE_RANGE_PCT = 12.0
BREAKOUT_VOLUME_RATIO = 1.5
DEFINED_RISK_PCT = 8.0
EMA_CROSSBACK_LOOKBACK = 30
EMA_CROSSBACK_EXTENSION_LOOKBACK = 15
EMA_ZONE_TOLERANCE = 0.01


def _unknown_result(reason: str) -> dict[str, Any]:
    return {
        "weekly_structure": {
            "state": "unknown",
            "summary": "週線資料不足",
            "close_vs_10w_ema_pct": None,
        },
        "daily_cycle": {"state": "unknown", "summary": "日線資料不足"},
        "extension_state": "normal",
        "reversal_state": "none",
        "pivotal_point": {"status": "none", "trigger": None, "invalidation": None, "risk_pct": None},
        "risk_state": "unknown",
        "action_state": "unknown",
        "evidence": [],
        "uncertainty": [reason],
        "parameter_status": PARAMETER_STATUS,
    }


def _prepare_history(history: pd.DataFrame, as_of: Optional[Any]) -> pd.DataFrame:
    required = {"date", "close"}
    if history is None or history.empty or not required.issubset(history.columns):
        return pd.DataFrame()
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame[frame["close"] > 0]
    if as_of is not None:
        frame = frame[frame["date"] <= pd.Timestamp(as_of)]
    return frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _weekly_structure(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) < MIN_WEEKLY_DAILY_BARS:
        return {"state": "unknown", "summary": "週線資料不足", "close_vs_10w_ema_pct": None}

    weekly_source = frame.assign(_week=frame["date"].dt.to_period("W-FRI"))
    weekly = weekly_source.groupby("_week", sort=True)["close"].last().dropna()
    ema10 = weekly.ewm(span=WEEKLY_EMA_SPAN, adjust=False, min_periods=WEEKLY_EMA_SPAN).mean()
    if len(weekly) < WEEKLY_EMA_SPAN or pd.isna(ema10.iloc[-1]):
        return {"state": "unknown", "summary": "不足 10 根週線", "close_vs_10w_ema_pct": None}

    close = float(weekly.iloc[-1])
    ema = float(ema10.iloc[-1])
    distance = (close / ema - 1.0) * 100.0
    slope_reference = float(ema10.dropna().iloc[-3]) if len(ema10.dropna()) >= 3 else ema
    slope = ema - slope_reference
    slope_pct = (ema / slope_reference - 1.0) * 100.0 if slope_reference > 0 else 0.0

    if abs(distance) <= WEEKLY_BASE_EMA_DISTANCE_PCT and abs(slope_pct) <= WEEKLY_BASE_EMA_SLOPE_PCT:
        state, summary = "base", "週線貼近走平的 10-week EMA，處於整理區"
    elif distance >= WEEKLY_EXTENSION_PCT and slope > 0:
        state, summary = "extended", "週線位於上升 10-week EMA 上方且延伸"
    elif close > ema and slope > 0:
        state, summary = "bullish", "週線位於上升 10-week EMA 上方"
    elif close < ema and slope < 0:
        state, summary = "bearish", "週線位於下降 10-week EMA 下方"
    elif close < ema and slope >= 0:
        state, summary = "correction", "跌回仍上升的 10-week EMA 下方"
    else:
        state, summary = "transition", "週線與 10-week EMA 尚未形成同向趨勢"
    return {
        "state": state,
        "summary": summary,
        "close_vs_10w_ema_pct": round(distance, 2),
    }


def _is_first_ema_crossback(work: pd.DataFrame, direction: str) -> bool:
    """Detect extension -> 10/20 EMA cross -> first retest on the latest bar."""
    if len(work) < MIN_DAILY_BARS + 2:
        return False
    latest = work.iloc[-1]
    latest_ema_high = max(float(latest["ema10"]), float(latest["ema20"]))
    latest_ema_low = min(float(latest["ema10"]), float(latest["ema20"]))
    start = max(1, len(work) - EMA_CROSSBACK_LOOKBACK - 1)

    for position in range(len(work) - 2, start - 1, -1):
        bar = work.iloc[position]
        prior = work.iloc[position - 1]
        prior_extension = work["extension_pct"].iloc[
            max(0, position - EMA_CROSSBACK_EXTENSION_LOOKBACK):position
        ].dropna()
        between = work.iloc[position + 1:-1]

        if direction == "bullish":
            crossed = (
                not (
                    float(prior["close"]) > float(prior["ema10"])
                    and float(prior["close"]) > float(prior["ema20"])
                )
                and float(bar["close"]) > float(bar["ema10"])
                and float(bar["close"]) > float(bar["ema20"])
            )
            had_extension = not prior_extension.empty and prior_extension.min() <= -DAILY_EXTENSION_RISK_PCT
            latest_retest = (
                float(latest["close"]) > latest_ema_high
                and float(latest["low"]) <= latest_ema_high * (1.0 + EMA_ZONE_TOLERANCE)
                and float(latest["low"]) >= latest_ema_low * (1.0 - EMA_ZONE_TOLERANCE * 3)
            )
            no_earlier_retest = all(
                float(row["close"]) > max(float(row["ema10"]), float(row["ema20"]))
                and float(row["low"]) > max(float(row["ema10"]), float(row["ema20"])) * (1.0 + EMA_ZONE_TOLERANCE)
                for _, row in between.iterrows()
            )
        else:
            crossed = (
                not (
                    float(prior["close"]) < float(prior["ema10"])
                    and float(prior["close"]) < float(prior["ema20"])
                )
                and float(bar["close"]) < float(bar["ema10"])
                and float(bar["close"]) < float(bar["ema20"])
            )
            had_extension = not prior_extension.empty and prior_extension.max() >= DAILY_EXTENSION_RISK_PCT
            latest_retest = (
                float(latest["close"]) < latest_ema_low
                and float(latest["high"]) >= latest_ema_low * (1.0 - EMA_ZONE_TOLERANCE)
                and float(latest["high"]) <= latest_ema_high * (1.0 + EMA_ZONE_TOLERANCE * 3)
            )
            no_earlier_retest = all(
                float(row["close"]) < min(float(row["ema10"]), float(row["ema20"]))
                and float(row["high"]) < min(float(row["ema10"]), float(row["ema20"])) * (1.0 - EMA_ZONE_TOLERANCE)
                for _, row in between.iterrows()
            )

        if crossed and had_extension and latest_retest and no_earlier_retest:
            return True
    return False


def _daily_cycle(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"open", "high", "low", "close"}
    if len(frame) < MIN_DAILY_BARS or not required.issubset(frame.columns):
        return {
            "daily_cycle": {"state": "unknown", "summary": "日線 OHLC 資料不足"},
            "extension_state": "normal",
            "reversal_state": "none",
            "pivotal_point": {"status": "none", "trigger": None, "invalidation": None, "risk_pct": None},
            "evidence": [],
        }

    work = frame.dropna(subset=["open", "high", "low", "close"]).copy()
    if len(work) < MIN_DAILY_BARS:
        return {
            "daily_cycle": {"state": "unknown", "summary": "有效日線 OHLC 少於 20 根"},
            "extension_state": "normal",
            "reversal_state": "none",
            "pivotal_point": {"status": "none", "trigger": None, "invalidation": None, "risk_pct": None},
            "evidence": [],
        }

    work["ema10"] = work["close"].ewm(span=10, adjust=False, min_periods=10).mean()
    work["ema20"] = work["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    work["extension_pct"] = (work["close"] / work["ema10"] - 1.0) * 100.0
    latest = work.iloc[-1]
    previous = work.iloc[-2]
    current_extension = float(latest["extension_pct"])
    recent_extension = work["extension_pct"].iloc[-6:-1].dropna()
    recent_downside = bool(not recent_extension.empty and recent_extension.min() <= -DAILY_EXTENSION_RISK_PCT)
    recent_upside = bool(not recent_extension.empty and recent_extension.max() >= DAILY_EXTENSION_RISK_PCT)

    if abs(current_extension) >= DAILY_EXTENSION_EXTREME_PCT:
        extension_state = "extreme"
    elif abs(current_extension) >= DAILY_EXTENSION_RISK_PCT or recent_downside or recent_upside:
        extension_state = "risk"
    else:
        extension_state = "normal"

    bar_range = float(latest["high"] - latest["low"])
    bullish_reversal_bar = (
        bar_range > 0
        and float(latest["close"]) > float(latest["open"])
        and float(latest["close"]) >= float(latest["low"]) + bar_range * 0.70
        and float(latest["close"]) > float(previous["high"])
    )
    bearish_reversal_bar = (
        bar_range > 0
        and float(latest["close"]) < float(latest["open"])
        and float(latest["close"]) <= float(latest["high"]) - bar_range * 0.70
        and float(latest["close"]) < float(previous["low"])
    )
    prior_reversal_bar = work.iloc[-2]
    before_prior_reversal = work.iloc[-3]
    prior_bar_range = float(prior_reversal_bar["high"] - prior_reversal_bar["low"])
    prior_extension_window = work["extension_pct"].iloc[-7:-2].dropna()
    failed_bullish_reversal = (
        not prior_extension_window.empty
        and prior_extension_window.min() <= -DAILY_EXTENSION_RISK_PCT
        and prior_bar_range > 0
        and float(prior_reversal_bar["close"]) > float(prior_reversal_bar["open"])
        and float(prior_reversal_bar["close"]) >= float(prior_reversal_bar["low"]) + prior_bar_range * 0.70
        and float(prior_reversal_bar["close"]) > float(before_prior_reversal["high"])
        and float(latest["close"]) < float(prior_reversal_bar["low"])
    )

    prior20 = work.iloc[-21:-1]
    prior_high = float(prior20["high"].max()) if not prior20.empty else None
    prior_low = float(prior20["low"].min()) if not prior20.empty else None
    average_volume = None
    volume_ratio = None
    if "volume" in work.columns:
        valid_volume = pd.to_numeric(prior20["volume"], errors="coerce").dropna()
        valid_volume = valid_volume[valid_volume > 0]
        average_volume = float(valid_volume.mean()) if not valid_volume.empty else None
        if average_volume and pd.notna(latest.get("volume")):
            volume_ratio = float(latest["volume"]) / average_volume

    close = float(latest["close"])
    above_emas = close > float(latest["ema10"]) and close > float(latest["ema20"])
    below_emas = close < float(latest["ema10"]) and close < float(latest["ema20"])
    prior_above = float(previous["close"]) > float(previous["ema10"]) and float(previous["close"]) > float(previous["ema20"])
    prior_below = float(previous["close"]) < float(previous["ema10"]) and float(previous["close"]) < float(previous["ema20"])
    bullish_crossback = _is_first_ema_crossback(work, "bullish")
    bearish_crossback = _is_first_ema_crossback(work, "bearish")

    state = "no-clear-cycle"
    summary = "日線尚無清楚的 Oliver price-cycle 事件"
    reversal_state = "none"
    pivotal = {"status": "none", "trigger": None, "invalidation": None, "risk_pct": None}

    if failed_bullish_reversal:
        state = "reversal-extension-failed"
        summary = "下行延伸反轉低點失守，原反轉線索失效"
        reversal_state = "failed"
    elif recent_downside and bullish_reversal_bar:
        state = "reversal-extension-confirmed"
        summary = "下行延伸後出現明確反轉棒，等待後續確認"
        reversal_state = "confirmed"
        trigger = float(latest["high"])
        invalidation = float(latest["low"])
        pivotal = {
            "status": "defined",
            "trigger": round(trigger, 2),
            "invalidation": round(invalidation, 2),
            "risk_pct": round((trigger - invalidation) / trigger * 100.0, 2),
        }
    elif current_extension <= -DAILY_EXTENSION_RISK_PCT:
        state = "reversal-extension-watch"
        summary = "價格向下遠離 10 EMA，只有反轉觀察條件，尚未確認"
        reversal_state = "watch"
    elif current_extension >= DAILY_EXTENSION_RISK_PCT:
        state = "exhaustion-extension"
        summary = "價格向上遠離 10 EMA，進入延伸風險區"
    elif recent_downside and above_emas and not prior_above:
        state = "wedge-pop"
        summary = "下行延伸後首次站回 10/20 EMA"
    elif recent_upside and below_emas and not prior_below:
        state = "wedge-drop"
        summary = "上行延伸後首次跌破 10/20 EMA，屬風險警訊"
    elif bullish_crossback:
        state = "ema-crossback-bullish"
        summary = "Wedge Pop 後第一次回測 10/20 EMA 區並守住"
        trigger = float(latest["high"])
        invalidation = float(latest["low"])
        pivotal = {
            "status": "defined",
            "trigger": round(trigger, 2),
            "invalidation": round(invalidation, 2),
            "risk_pct": round((trigger - invalidation) / trigger * 100.0, 2),
        }
    elif bearish_crossback:
        state = "ema-crossback-bearish"
        summary = "Wedge Drop 後第一次反彈回測 10/20 EMA 區，屬惡化警訊"
    elif prior_high is not None and close > prior_high and volume_ratio is not None and volume_ratio >= BREAKOUT_VOLUME_RATIO:
        state = "base-n-break-bullish"
        summary = "突破近 20 日高點且成交量確認"
        trigger = prior_high
        invalidation = float(work["low"].iloc[-10:].min())
        pivotal = {
            "status": "defined",
            "trigger": round(trigger, 2),
            "invalidation": round(invalidation, 2),
            "risk_pct": round((trigger - invalidation) / trigger * 100.0, 2),
        }
    elif prior_low is not None and close < prior_low and volume_ratio is not None and volume_ratio >= BREAKOUT_VOLUME_RATIO:
        state = "base-n-break-bearish"
        summary = "跌破近 20 日低點且成交量確認，屬惡化警訊"
    elif recent_upside and bearish_reversal_bar:
        state = "exhaustion-reversal-warning"
        summary = "上行延伸後出現反轉棒，避免追價"
        reversal_state = "confirmed"
    else:
        range_low = float(prior20["low"].min()) if not prior20.empty else close
        range_high = float(prior20["high"].max()) if not prior20.empty else close
        range_pct = (range_high / range_low - 1.0) * 100.0 if range_low > 0 else float("inf")
        if range_pct <= BASE_RANGE_PCT:
            state = "base"
            summary = "近 20 日價格區間收斂，仍等待方向確認"

    evidence = [
        f"收盤距 10 EMA {current_extension:+.2f}%",
        summary,
    ]
    if volume_ratio is not None:
        evidence.append(f"成交量為前 20 日均量 {volume_ratio:.2f} 倍")
    return {
        "daily_cycle": {"state": state, "summary": summary},
        "extension_state": extension_state,
        "reversal_state": reversal_state,
        "pivotal_point": pivotal,
        "evidence": evidence,
    }


def analyze_price_history(history: pd.DataFrame, as_of: Optional[Any] = None) -> dict[str, Any]:
    """Analyze one stock using only rows visible at ``as_of``."""
    frame = _prepare_history(history, as_of)
    if frame.empty:
        return _unknown_result("缺少有效 date/close 資料")

    weekly = _weekly_structure(frame)
    daily = _daily_cycle(frame)
    result = _unknown_result("資料門檻為待回測的專案參數")
    result["weekly_structure"] = weekly
    result.update(daily)
    result["evidence"] = ([weekly["summary"]] if weekly["state"] != "unknown" else []) + daily["evidence"]

    daily_state = daily["daily_cycle"]["state"]
    pivotal = daily["pivotal_point"]
    pivotal_risk = pivotal.get("risk_pct")
    if weekly["state"] == "unknown" or daily_state == "unknown":
        result["risk_state"] = "unknown"
        result["action_state"] = "unknown"
    elif weekly["state"] == "extended" or daily_state in {"exhaustion-extension", "exhaustion-reversal-warning"}:
        result["risk_state"] = "avoid-chasing"
        result["action_state"] = "reduce-risk"
    elif weekly["state"] == "bearish" or daily_state in {"wedge-drop", "ema-crossback-bearish", "base-n-break-bearish", "reversal-extension-failed"}:
        result["risk_state"] = "deterioration-warning"
        result["action_state"] = "reduce-risk"
    elif pivotal["status"] == "defined" and pivotal_risk is not None and pivotal_risk <= DEFINED_RISK_PCT:
        result["risk_state"] = "defined-risk"
        result["action_state"] = "research"
    elif daily_state in {"reversal-extension-confirmed", "wedge-pop"}:
        result["risk_state"] = "normal"
        result["action_state"] = "wait-for-confirmation"
    else:
        result["risk_state"] = "normal"
        result["action_state"] = "watch"
    result["uncertainty"] = ["數值門檻是待歷史回放驗證的專案參數，不是 Oliver 原文規則"]
    return result


_MARKET_PHASES = {
    "bullish": ("leading", "normal-research"),
    "extended": ("leading-extended", "avoid-chasing"),
    "correction": ("correcting", "selective"),
    "bearish": ("correcting", "defensive"),
    "base": ("transitioning", "wait-for-confirmation"),
    "transition": ("transitioning", "wait-for-confirmation"),
    "unknown": ("unknown", "unknown"),
}


def analyze_market_history(history: pd.DataFrame, as_of: Optional[Any] = None) -> dict[str, Any]:
    """Classify point-in-time TAIEX weekly context before stock analysis."""
    frame = _prepare_history(history, as_of)
    weekly = _weekly_structure(frame) if not frame.empty else _unknown_result("缺少 TAIEX 歷史")["weekly_structure"]
    phase, action = _MARKET_PHASES[weekly["state"]]
    return {
        "weekly_structure": weekly,
        "market_phase": phase,
        "market_action": action,
        "as_of": frame["date"].iloc[-1].date().isoformat() if not frame.empty else None,
        "evidence": [weekly["summary"]] if weekly["state"] != "unknown" else [],
        "uncertainty": ["大盤數值門檻是待回測的專案參數，不是 Oliver 原文規則"],
        "parameter_status": PARAMETER_STATUS,
    }


def apply_market_context(stock_analysis: dict[str, Any], market_context: dict[str, Any]) -> dict[str, Any]:
    """Attach index context and conservatively gate a stock research action."""
    result = deepcopy(stock_analysis)
    market = deepcopy(market_context)
    stock_action = result.get("action_state", "unknown")
    market_action = market.get("market_action", "unknown")
    result["stock_action_state"] = stock_action
    result["market_context"] = market

    if stock_action == "research" and market_action != "normal-research":
        result["action_state"] = "wait-for-confirmation"
        evidence = list(result.get("evidence") or [])
        evidence.append(f"大盤週線 {market_action}：個股 research 降為等待確認")
        result["evidence"] = evidence
    return result


def calc_oliver_market_structure(
    universe_df: pd.DataFrame,
    db_path: str = "data/screener.db",
    as_of: Optional[Any] = None,
    lookback: int = 90,
    market_context: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    """Load one point-in-time OHLCV window and analyze every universe stock."""
    if universe_df is None or universe_df.empty or "stock_id" not in universe_df.columns:
        return {}
    stock_ids = list(dict.fromkeys(universe_df["stock_id"].astype(str).tolist()))

    def with_market(analysis: dict[str, Any]) -> dict[str, Any]:
        return apply_market_context(analysis, market_context) if market_context is not None else analysis

    try:
        import duckdb

        con = duckdb.connect(db_path, read_only=True)
        try:
            if as_of is None:
                dates = con.execute(
                    "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT ?",
                    [lookback],
                ).fetchall()
            else:
                dates = con.execute(
                    "SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
                    [pd.Timestamp(as_of).date(), lookback],
                ).fetchall()
            if not dates:
                return {stock_id: with_market(_unknown_result("資料庫沒有可用行情")) for stock_id in stock_ids}
            oldest = min(row[0] for row in dates)
            if as_of is None:
                history = con.execute(
                    "SELECT stock_id, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? ORDER BY stock_id, date",
                    [oldest],
                ).fetchdf()
            else:
                history = con.execute(
                    "SELECT stock_id, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? AND date <= ? ORDER BY stock_id, date",
                    [oldest, pd.Timestamp(as_of).date()],
                ).fetchdf()
        finally:
            con.close()
    except Exception as exc:
        reason = f"Oliver 行情載入失敗：{type(exc).__name__}"
        return {stock_id: with_market(_unknown_result(reason)) for stock_id in stock_ids}

    if history.empty:
        return {stock_id: with_market(_unknown_result("所選期間沒有個股行情")) for stock_id in stock_ids}
    history["stock_id"] = history["stock_id"].astype(str)
    grouped = {stock_id: frame for stock_id, frame in history.groupby("stock_id", sort=False)}
    return {
        stock_id: with_market(analyze_price_history(grouped.get(stock_id, pd.DataFrame()), as_of=as_of))
        for stock_id in stock_ids
    }
