from datetime import UTC, datetime

import pandas as pd

from backend.app.db.models import DataQualityIssue


def validate_prices(df: pd.DataFrame, symbol: str) -> list[DataQualityIssue]:
    issues = []
    if df.empty:
        return issues

    for _idx, row in df.iterrows():
        if row["close"] <= 0:
            issues.append(
                DataQualityIssue(
                    symbol=symbol,
                    as_of_date=row["time"],
                    code="PRICE_ZERO",
                    severity="HIGH",
                    detail=f"Close price is zero or negative: {row['close']}",
                    detected_at=datetime.now(UTC),
                )
            )
        if row["high"] < row["low"] or row["high"] < row["open"] or row["high"] < row["close"]:
            issues.append(
                DataQualityIssue(
                    symbol=symbol,
                    as_of_date=row["time"],
                    code="PRICE_OHLC_INCONSISTENT",
                    severity="HIGH",
                    detail="High is less than Low/Open/Close",
                    detected_at=datetime.now(UTC),
                )
            )

    if len(df) > 1:
        df_sorted = df.sort_values(by="time").copy()
        df_sorted["prev_close"] = df_sorted["close"].shift(1)
        for _idx, row in df_sorted.dropna().iterrows():
            jump = abs((row["close"] - row["prev_close"]) / row["prev_close"])
            if jump > 0.08:
                issues.append(
                    DataQualityIssue(
                        symbol=symbol,
                        as_of_date=row["time"],
                        code="PRICE_JUMP_LIMIT",
                        severity="MEDIUM",
                        detail=f"Price jumped by {jump * 100:.2f}%",
                        detected_at=datetime.now(UTC),
                    )
                )
    return issues


def validate_fundamentals(df: pd.DataFrame, symbol: str) -> list[DataQualityIssue]:
    issues = []
    return issues


def validate_news(df: pd.DataFrame, symbol: str) -> list[DataQualityIssue]:
    issues = []
    return issues
