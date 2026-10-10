"""Config-driven source validation; uncertain market moves are warnings."""

import math
from datetime import UTC, datetime

import pandas as pd

from backend.app.core.config import load_settings
from backend.app.db.models import DataQualityIssue


def _issue(symbol, day, code, detail, severity="WARNING"):
    try:
        day = pd.Timestamp(day).date()
        if pd.isna(day):
            day = datetime.now(UTC).date()
    except (ValueError, TypeError):
        day = datetime.now(UTC).date()
    return DataQualityIssue(
        symbol=symbol,
        as_of_date=day,
        code=code,
        severity=severity,
        detail=detail,
        detected_at=datetime.now(UTC),
    )


def validate_prices(df: pd.DataFrame, symbol: str, settings=None) -> list[DataQualityIssue]:
    cfg = (settings or load_settings()).data_requirements
    issues = []
    if df.empty:
        return issues
    required = {"time", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return [
            _issue(
                symbol, None, "PRICE_SCHEMA_MISSING", "Required OHLCV columns are absent", "HIGH"
            )
        ]
    frame = df.copy()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    for name in required - {"time"}:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    for _, row in frame.iterrows():
        day = row["time"]
        if pd.isna(day):
            issues.append(
                _issue(
                    symbol,
                    None,
                    "PRICE_DATE_INVALID",
                    "Source trading date is missing or invalid",
                    "HIGH",
                )
            )
        if any(not math.isfinite(float(row[k])) for k in required - {"time"}):
            issues.append(
                _issue(
                    symbol,
                    day,
                    "PRICE_VALUE_INVALID",
                    "OHLCV contains missing or non-finite values",
                    "HIGH",
                )
            )
            continue
        if min(row[k] for k in ("open", "high", "low", "close")) <= 0 or row["volume"] < 0:
            issues.append(
                _issue(
                    symbol,
                    day,
                    "PRICE_NONPOSITIVE",
                    "OHLC must be positive and volume nonnegative",
                    "HIGH",
                )
            )
        if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(
            row["open"], row["close"]
        ):
            issues.append(
                _issue(
                    symbol,
                    day,
                    "PRICE_OHLC_INCONSISTENT",
                    "High/low contradict open or close",
                    "HIGH",
                )
            )
    for day in frame.loc[frame.time.duplicated(keep=False), "time"].drop_duplicates():
        issues.append(
            _issue(symbol, day, "PRICE_DATE_DUPLICATE", "Multiple bars share the same trading date")
        )
    ordered = frame.dropna(subset=["time"]).drop_duplicates("time", keep="last").sort_values("time")
    previous = ordered.close.shift()
    changes = (ordered.close / previous - 1).abs()
    threshold = cfg["quality"]["hose_daily_limit"] + cfg["quality"]["price_jump_tolerance"]
    for index in ordered.index[(previous > 0) & (changes > threshold)]:
        issues.append(
            _issue(
                symbol,
                ordered.loc[index, "time"],
                "PRICE_JUMP_REVIEW",
                f"Close movement exceeds configured {threshold:.2%} threshold; "
                "corporate actions or source units may explain it",
            )
        )
    zero_run = 0
    for _, row in ordered.iterrows():
        zero_run = zero_run + 1 if row.volume == 0 else 0
        if zero_run == cfg["quality"]["zero_volume_max_sessions"] + 1:
            issues.append(
                _issue(
                    symbol,
                    row.time,
                    "PRICE_ZERO_VOLUME_RUN",
                    "Consecutive zero-volume sessions exceed configured threshold",
                )
            )
    return issues


def validate_fundamentals(df: pd.DataFrame, symbol: str, settings=None) -> list[DataQualityIssue]:
    if df.empty:
        return []
    return [
        _issue(
            symbol,
            None,
            "FA_UNIT_UNVERIFIED",
            "Financial monetary/ratio units need source metadata verification "
            "before comparing periods",
        ),
        _issue(
            symbol,
            None,
            "FA_PUBLICATION_INFERRED",
            "Publication timestamp and historical revision vintage are not provided; "
            "available_at uses first fetch",
        ),
    ]


def validate_news(df: pd.DataFrame, symbol: str, settings=None) -> list[DataQualityIssue]:
    if df.empty:
        return []
    fields = (
        "published_at",
        "public_date",
        "publishDate",
        "publish_time",
        "publishTime",
        "pubDate",
    )
    issues = []
    for _, row in df.iterrows():
        value = next((row[name] for name in fields if name in row and pd.notna(row[name])), None)
        stamp = pd.to_datetime(value, errors="coerce")
        if value is None or pd.isna(stamp):
            issues.append(
                _issue(
                    symbol,
                    None,
                    "NEWS_PUBLICATION_MISSING",
                    "Source publication date missing; item excluded from scored news",
                )
            )
    return issues
