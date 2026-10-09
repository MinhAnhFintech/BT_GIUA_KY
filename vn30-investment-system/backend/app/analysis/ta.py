"""Technical Analysis scoring engine with explicit normalization rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import MetricRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TAResult:
    """TA score with full breakdown for transparency."""

    score: float | None
    status: str  # COMPLETE, PARTIAL_ANALYSIS, INSUFFICIENT_DATA
    reasons: list[str]
    breakdown: dict[str, Any]


def compute_ma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index using exponential moving average of gains/losses."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)


def compute_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, and histogram."""
    ema_fast = series.ewm(span=fast, min_periods=fast).mean()
    ema_slow = series.ewm(span=slow, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=window, min_periods=window).mean()


def normalize_metric(value: float, rule: MetricRule) -> float:
    """Clipped linear normalization to 0-100 scale.

    Args:
        value: Raw metric value.
        rule: Normalization rule with lower/upper bounds and direction.

    Returns:
        Score between 0 and 100.
    """
    if not np.isfinite(value):
        return np.nan

    # Clip to bounds
    clipped = max(rule.lower, min(value, rule.upper))

    # Linear interpolation
    if rule.direction == "higher":
        score = (clipped - rule.lower) / (rule.upper - rule.lower)
    else:  # "lower" is better
        score = (rule.upper - clipped) / (rule.upper - rule.lower)

    return round(score * 100.0, 4)


def compute_ta_indicators(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, float]:
    """Compute all TA indicators from OHLCV DataFrame.

    Args:
        df: DataFrame with columns [time, open, high, low, close, volume].
        config: TA config section from scoring.yaml.

    Returns:
        Dict of indicator name -> raw value.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    ma_windows = config["ma_windows"]
    indicators: dict[str, float] = {}

    # Price vs MA200
    ma200 = compute_ma(close, ma_windows[2])
    if ma200.iloc[-1] and ma200.iloc[-1] > 0:
        indicators["price_ma200"] = (close.iloc[-1] / ma200.iloc[-1]) - 1.0

    # MA20 vs MA50 cross
    ma20 = compute_ma(close, ma_windows[0])
    ma50 = compute_ma(close, ma_windows[1])
    if ma50.iloc[-1] and ma50.iloc[-1] > 0:
        indicators["ma20_ma50"] = (ma20.iloc[-1] / ma50.iloc[-1]) - 1.0

    # RSI
    rsi = compute_rsi(close, config["rsi_window"])
    if not np.isnan(rsi.iloc[-1]):
        indicators["rsi14"] = rsi.iloc[-1]

    # MACD histogram as % of price
    macd_cfg = config["macd"]
    _, _, histogram = compute_macd(close, macd_cfg["fast"], macd_cfg["slow"], macd_cfg["signal"])
    if close.iloc[-1] > 0 and not np.isnan(histogram.iloc[-1]):
        indicators["macd_histogram_pct"] = histogram.iloc[-1] / close.iloc[-1]

    # Volume ratio (20-day avg vs 60-day avg)
    vol_windows = config["volume_windows"]
    vol20 = volume.rolling(vol_windows[0]).mean().iloc[-1]
    vol60 = volume.rolling(vol_windows[1]).mean().iloc[-1]
    if vol60 > 0:
        indicators["volume20_volume60"] = vol20 / vol60

    # ATR / Close (volatility)
    atr = compute_atr(high, low, close, config["atr_window"])
    if close.iloc[-1] > 0 and not np.isnan(atr.iloc[-1]):
        indicators["atr_close"] = atr.iloc[-1] / close.iloc[-1]

    return indicators


def score_ta(df: pd.DataFrame, config: dict[str, Any]) -> TAResult:
    """Compute TA score from OHLCV data.

    Args:
        df: Price history DataFrame.
        config: Full scoring config dict.

    Returns:
        TAResult with score, status, reasons, and breakdown.
    """
    ta_config = config["ta"]
    metrics_config = ta_config["metrics"]
    reasons: list[str] = []
    breakdown: dict[str, Any] = {}

    if df is None or len(df) < 200:
        return TAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=[f"Need ≥200 sessions, got {len(df) if df is not None else 0}"],
            breakdown={},
        )

    try:
        indicators = compute_ta_indicators(df, ta_config)
    except Exception as e:
        logger.error("TA indicator computation failed: %s", e)
        return TAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=[f"Indicator computation error: {e}"],
            breakdown={},
        )

    total_weight = 0.0
    weighted_score = 0.0
    available_metrics = 0
    missing_metrics: list[str] = []

    for metric_name, rule_dict in metrics_config.items():
        rule = MetricRule.model_validate(rule_dict)
        raw_value = indicators.get(metric_name)

        if raw_value is None or not np.isfinite(raw_value):
            missing_metrics.append(metric_name)
            breakdown[metric_name] = {
                "raw": None,
                "score": None,
                "weight": rule.weight,
                "status": "N/A",
                "reason": "Indicator not available",
            }
            continue

        normalized = normalize_metric(raw_value, rule)
        if np.isnan(normalized):
            missing_metrics.append(metric_name)
            breakdown[metric_name] = {
                "raw": raw_value,
                "score": None,
                "weight": rule.weight,
                "status": "N/A",
                "reason": "Normalization returned NaN",
            }
            continue

        weighted_score += normalized * rule.weight
        total_weight += rule.weight
        available_metrics += 1
        breakdown[metric_name] = {
            "raw": round(raw_value, 6),
            "score": normalized,
            "weight": rule.weight,
            "weighted_contribution": round(normalized * rule.weight, 4),
        }

    if missing_metrics:
        reasons.append(f"Missing TA metrics: {', '.join(missing_metrics)}")

    # Determine status based on available data
    if available_metrics == 0:
        return TAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["No TA metrics could be computed"],
            breakdown=breakdown,
        )

    if total_weight < 0.99:
        # Some metrics missing - PARTIAL_ANALYSIS, do NOT redistribute
        score = None
        status = "PARTIAL_ANALYSIS"
        reasons.append(
            f"Total weight coverage: {total_weight:.2%} "
            f"(missing weight NOT redistributed per policy)"
        )
    else:
        score = weighted_score
        status = "COMPLETE"

    # Clamp to 0-100
    score = max(0.0, min(100.0, score)) if score is not None else None

    breakdown["_summary"] = {
        "total_weight_covered": round(total_weight, 4),
        "available_metrics": available_metrics,
        "total_metrics": len(metrics_config),
        "final_score": round(score, 4) if score is not None else None,
    }

    return TAResult(
        score=round(score, 4) if score is not None else None,
        status=status,
        reasons=reasons,
        breakdown=breakdown,
    )
