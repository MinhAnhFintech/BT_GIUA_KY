"""Source diagnostics distinguish network availability from research suitability."""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Literal
from urllib.robotparser import RobotFileParser

import requests
from pydantic import BaseModel, Field


class SourceHealth(BaseModel):
    """Only verified facts may be labelled OK; untested properties remain None."""

    name: str
    kind: str
    status: Literal["OK", "FAIL", "BLOCKED", "NOT_VERIFIED"]
    required: bool = False
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested_as_of: date
    latest_data_date: date | None = None
    freshness_days: int | None = None
    schema_valid: bool | None = None
    row_count: int | None = None
    payload_sha256: str | None = None
    duration_seconds: float = 0
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


def inspect_frame(frame: Any, kind: str, as_of: date) -> dict[str, Any]:
    """Inspect actual SDK output without assuming units, vintages or publication dates."""
    import pandas as pd

    if isinstance(frame, pd.Series):
        frame = frame.to_frame(name="symbol")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("EMPTY_OR_UNEXPECTED_SCHEMA")
    columns = [str(column) for column in frame.columns]
    details: dict[str, Any] = {"columns": columns}
    warnings: list[str] = []
    latest = None
    if kind == "universe":
        if "symbol" not in columns:
            raise ValueError("MISSING_SYMBOL_COLUMN")
        symbols = frame["symbol"].astype(str).tolist()
        if len(set(symbols)) != 30 or any(
            not re.fullmatch(r"[A-Z][A-Z0-9]{2,4}", s) for s in symbols
        ):
            raise ValueError("INVALID_VN30_MEMBERSHIP_SCHEMA")
        details["symbols"] = sorted(symbols)
        details["observed_on"] = datetime.now(timezone(timedelta(hours=7))).date().isoformat()
        warnings.append("CURRENT_SNAPSHOT_ONLY: chưa xác minh ngày hiệu lực hoặc lịch sử VN30")
    elif kind == "prices":
        if not {"time", "open", "high", "low", "close", "volume"}.issubset(columns):
            raise ValueError("MISSING_OHLCV_COLUMNS")
        times = pd.to_datetime(frame["time"], errors="coerce")
        if times.isna().any() or times.duplicated().any():
            raise ValueError("INVALID_OR_DUPLICATE_PRICE_DATE")
        latest = times.max().date()
        if latest > as_of:
            raise ValueError("FUTURE_PRICE_RETURNED")
        ohlc = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        if ohlc.isna().any().any() or (ohlc <= 0).any().any():
            raise ValueError("INVALID_PRICE_VALUES")
        if volume.isna().any() or (volume < 0).any():
            raise ValueError("INVALID_VOLUME_VALUES")
        if (ohlc.high < ohlc[["open", "close", "low"]].max(axis=1)).any() or (
            ohlc.low > ohlc[["open", "close", "high"]].min(axis=1)
        ).any():
            raise ValueError("INVALID_OHLC_RANGE")
        warnings.extend(
            [
                "PRICE_UNIT_NOT_VERIFIED",
                "ADJUSTMENT_NOT_VERIFIED",
                "EXCHANGE_CALENDAR_NOT_VERIFIED",
                "COMPLETED_SESSION_NOT_VERIFIED",
            ]
        )
    elif kind == "financials":
        if not {"item_id", "item"}.issubset(columns):
            raise ValueError("MISSING_FINANCIAL_METADATA_COLUMNS")
        periods = list(frame.attrs.get("periods", []))
        if not periods:
            periods = [column for column in columns if re.search(r"20\d{2}", column)]
        if not periods:
            raise ValueError("MISSING_REPORT_PERIODS")
        details["report_periods"] = [str(p) for p in periods]
        details["units"] = (
            sorted(set(frame["unit"].dropna().astype(str))) if "unit" in columns else []
        )
        warnings.append("FINANCIAL_MONETARY_UNITS_NOT_VERIFIED")
        warnings.extend(
            [
                "PUBLICATION_DATES_NOT_VERIFIED",
                "VINTAGES_NOT_VERIFIED",
                "SECTOR_METRIC_COVERAGE_NOT_VERIFIED",
            ]
        )
    elif kind == "news":
        title_fields = {"title", "news_title", "newsTitle", "Title"}
        if not title_fields.intersection(columns):
            raise ValueError("MISSING_NEWS_TITLE_COLUMN")
        warnings.extend(
            [
                "HISTORICAL_NEWS_NOT_VERIFIED",
                "PUBLICATION_TIMESTAMPS_NOT_VERIFIED",
                "ARTICLE_LINKS_AND_SYMBOL_MATCH_NOT_VERIFIED",
            ]
        )
    elif kind == "company":
        if not {"symbol", "as_of_date"}.issubset(columns):
            raise ValueError("MISSING_COMPANY_METADATA_COLUMNS")
        warnings.append("COMPANY_SCHEMA_REQUIRES_FIELD_MAPPING")
    else:
        raise ValueError("UNKNOWN_PROBE_KIND")
    payload = frame.to_json(orient="split", date_format="iso", force_ascii=False)
    return {
        "schema_valid": True,
        "row_count": len(frame),
        "latest_data_date": latest,
        "freshness_days": (as_of - latest).days if latest else None,
        "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "warnings": warnings,
        "details": details,
    }


def probe_rss(spec: dict[str, Any], settings: dict[str, Any], as_of: date) -> SourceHealth:
    """Check robots first; if policy cannot be read, fail closed without fetching RSS."""
    health = SourceHealth(
        name=spec["name"],
        kind="rss",
        status="NOT_VERIFIED",
        source=spec["name"],
        source_url=spec["url"],
        requested_as_of=as_of,
        required=spec["required"],
    )
    headers = {"User-Agent": settings["user_agent"]}
    try:
        robots = requests.get(
            spec["robots_url"], headers=headers, timeout=settings["timeout_seconds"]
        )
        robots.raise_for_status()
        if "<html" in robots.text.lower():
            raise ValueError("ROBOTS_RESPONSE_IS_HTML")
        policy = RobotFileParser()
        policy.parse(robots.text.splitlines())
        if not policy.can_fetch(settings["user_agent"], spec["url"]):
            return health.model_copy(update={"status": "BLOCKED", "reason": "ROBOTS_DISALLOW"})
        delay = policy.crawl_delay(settings["user_agent"]) or 0
        if delay > settings["request_interval_seconds"]:
            return health.model_copy(
                update={"status": "BLOCKED", "reason": "CRAWL_DELAY_REQUIRES_WAIT"}
            )
        time.sleep(settings["request_interval_seconds"])
        response = requests.get(spec["url"], headers=headers, timeout=settings["timeout_seconds"])
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        if not items or any(
            item.find("title") is None or item.find("link") is None or item.find("pubDate") is None
            for item in items
        ):
            raise ValueError("INVALID_RSS_SCHEMA")
        health.status = "OK"
        health.schema_valid = True
        health.row_count = len(items)
        health.payload_sha256 = hashlib.sha256(response.content).hexdigest()
        health.warnings = ["RSS_NOT_A_HISTORICAL_ARCHIVE", "SYMBOL_FILTER_NOT_VERIFIED"]
    except (requests.RequestException, ValueError, ET.ParseError) as error:
        health.status = "FAIL"
        # Exception type only: URLs/headers from errors could contain credentials.
        health.reason = type(error).__name__
    return health
