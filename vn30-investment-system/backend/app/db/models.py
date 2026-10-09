"""Initial SQLAlchemy schema, including vintages and traceable analysis inputs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite stores UTC-naive timestamps and restores explicit UTC on reading."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        """Reject ambiguous datetimes before persistence."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        """Restore the UTC timezone discarded by SQLite."""
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Base for all persistent entities."""


class AuditFields:
    """Every source record identifies its source and its retrieval timestamp."""

    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))


class SourceFetch(AuditFields, Base):
    """Immutable source response metadata; no secrets in source URLs."""

    __tablename__ = "source_fetches"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    symbol: Mapped[str | None] = mapped_column(String(10))
    schema_version: Mapped[str] = mapped_column(String(40))
    unit_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Stock(Base):
    """Security reference information is independent of VN30 membership."""

    __tablename__ = "stocks"
    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str] = mapped_column(String(40))


class UniverseSnapshot(AuditFields, Base):
    """Effective date range and knowledge date are separate from fetch date."""

    __tablename__ = "universe_snapshots"
    __table_args__ = (CheckConstraint("effective_to IS NULL OR effective_to >= effective_from"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    index_name: Mapped[str] = mapped_column(String(20))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    announced_at: Mapped[datetime] = mapped_column(UTCDateTime())
    coverage: Mapped[str] = mapped_column(String(40))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class UniverseMember(Base):
    """Full membership set; candidate sector metadata is not a membership claim."""

    __tablename__ = "universe_members"
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("universe_snapshots.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(40))


class PriceBar(AuditFields, Base):
    """Raw execution prices and analytical adjusted prices remain distinct."""

    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", "source", "payload_sha256"),
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0"),
        CheckConstraint("high >= low AND high >= open AND high >= close"),
        CheckConstraint("low <= open AND low <= close AND volume >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), index=True)
    open: Mapped[float] = mapped_column(Numeric(20, 6))
    high: Mapped[float] = mapped_column(Numeric(20, 6))
    low: Mapped[float] = mapped_column(Numeric(20, 6))
    close: Mapped[float] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(Integer)
    adjusted_close: Mapped[float | None] = mapped_column(Numeric(20, 6))
    adjustment_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    price_unit: Mapped[str] = mapped_column(String(20))
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class FundamentalValue(AuditFields, Base):
    """Long-format metric; revisions cannot overwrite original known values."""

    __tablename__ = "fundamental_values"
    __table_args__ = (
        UniqueConstraint("symbol", "period_end", "period_type", "metric", "source", "revision"),
        CheckConstraint("available_at >= published_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(10))
    metric: Mapped[str] = mapped_column(String(80))
    value: Mapped[float | None] = mapped_column(Numeric(28, 8))
    unit: Mapped[str] = mapped_column(String(20))
    original_unit: Mapped[str] = mapped_column(String(30))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    publication_inferred: Mapped[bool] = mapped_column(Boolean)
    vintage_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[str] = mapped_column(String(80))
    missing_reason: Mapped[str | None] = mapped_column(Text)


class NewsItem(AuditFields, Base):
    """Metadata and self-written summary only; never store full article text."""

    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    timestamp_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    symbols: Mapped[list[str]] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    classifier_version: Mapped[str | None] = mapped_column(String(40))


class CorporateAction(AuditFields, Base):
    """Verified event inputs needed for split and cash dividend accounting."""

    __tablename__ = "corporate_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"))
    ex_date: Mapped[date] = mapped_column(Date)
    payable_date: Mapped[date | None] = mapped_column(Date)
    action_type: Mapped[str] = mapped_column(String(30))
    factor: Mapped[float | None] = mapped_column(Numeric(20, 8))
    cash_per_share_vnd: Mapped[float | None] = mapped_column(Numeric(20, 6))
    announced_at: Mapped[datetime] = mapped_column(UTCDateTime())
    verified: Mapped[bool] = mapped_column(Boolean)


class TradingSession(AuditFields, Base):
    """Official sessions support missing-session checks, holidays and T+2."""

    __tablename__ = "trading_sessions"
    exchange: Mapped[str] = mapped_column(String(10), primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean)


class DataQualityIssue(Base):
    """Rejected records still leave an actionable audit trail."""

    __tablename__ = "data_quality_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    fetch_id: Mapped[int | None] = mapped_column(ForeignKey("source_fetches.id"))
    symbol: Mapped[str | None] = mapped_column(String(10))
    as_of_date: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Job(Base):
    """Persisted job state enables restart recovery; workers arrive at stage 4."""

    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    timing: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))


class AnalysisRun(Base):
    """One immutable configuration/data combination per analysis run."""

    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    scoring_version: Mapped[str] = mapped_column(String(40))
    config_hash: Mapped[str] = mapped_column(String(64))
    data_hash: Mapped[str] = mapped_column(String(64))
    input_record_ids: Mapped[dict[str, Any]] = mapped_column(JSON)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class AnalysisResult(Base):
    """Unavailable component scores remain NULL; all breakdowns retain input IDs."""

    __tablename__ = "analysis_results"
    __table_args__ = (
        CheckConstraint("status IN ('COMPLETE','PARTIAL_ANALYSIS','INSUFFICIENT_DATA')"),
        CheckConstraint("status = 'COMPLETE' OR total_score IS NULL"),
        CheckConstraint(
            "status != 'COMPLETE' OR (fa IS NOT NULL AND ta IS NOT NULL "
            "AND news IS NOT NULL AND total_score IS NOT NULL)"
        ),
        *(
            CheckConstraint(f"{field} IS NULL OR ({field} >= 0 AND {field} <= 100)")
            for field in ("fa", "ta", "news", "total_score")
        ),
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    fa: Mapped[float | None] = mapped_column(Numeric(12, 8))
    ta: Mapped[float | None] = mapped_column(Numeric(12, 8))
    news: Mapped[float | None] = mapped_column(Numeric(12, 8))
    total_score: Mapped[float | None] = mapped_column(Numeric(12, 8))
    status: Mapped[str] = mapped_column(String(30))
    reasons: Mapped[list[str]] = mapped_column(JSON)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON)


class BacktestRun(Base):
    """Reproducible run artifact, including limitations and all requested parameters."""

    __tablename__ = "backtest_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    mode: Mapped[str] = mapped_column(String(20))
    seed: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    data_hash: Mapped[str] = mapped_column(String(64))
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_record_ids: Mapped[dict[str, Any]] = mapped_column(JSON)
    results: Mapped[dict[str, Any]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)


class ReportArtifact(Base):
    """PDF identifies immutable analysis and optional backtest, not current live data."""

    __tablename__ = "report_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"))
    backtest_run_id: Mapped[str | None] = mapped_column(ForeignKey("backtest_runs.id"))
    kind: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    relative_path: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
