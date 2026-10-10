"""Explicit public API contracts for the local research dashboard."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobAccepted(BaseModel):
    job_id: str
    status: Literal["accepted"]
    message: str


class JobResult(BaseModel):
    job_id: str
    kind: str
    status: Literal["pending", "running", "completed", "failed"]
    timing: dict[str, Any]
    error: str | None = None
    created_at: datetime
    result: dict[str, Any] | None = None


class HealthJob(BaseModel):
    job_id: str
    kind: str
    status: str
    timing: dict[str, Any]
    error: str | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    scoring_version: str
    config_hash: str
    timestamp: datetime
    api_key_present: bool
    data_sources: dict[str, Any]
    jobs: list[HealthJob]


class UniverseResponse(BaseModel):
    date: date
    vn30_members: list[str]
    selected: list[dict[str, str]]
    warnings: list[str]
    min_symbols: int = 5
    max_symbols: int = 30
    source: str | None = None
    fetched_at: str | None = None


class ScoreRow(BaseModel):
    rank: int = 0
    symbol: str
    sector: str
    fa_score: float | None = None
    ta_score: float | None = None
    news_score: float | None = None
    total_score: float | None = None
    status: Literal["COMPLETE", "PARTIAL_ANALYSIS", "INSUFFICIENT_DATA"]
    reasons: list[str] = Field(default_factory=list)


class RankingResponse(BaseModel):
    as_of_date: date
    scoring_version: str
    config_hash: str | None = None
    data_hash: str | None = None
    run_id: str | None = None
    main_ranking: list[ScoreRow]
    secondary_ranking: list[ScoreRow]
    disclaimer: str


class StockResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    sector: str
    status: str
    total_score: float | None = None
    fa_score: float | None = None
    ta_score: float | None = None
    news_score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    prices: list[dict[str, Any]]
    fundamentals: list[dict[str, Any]]
    news: list[dict[str, Any]]
    breakdown: dict[str, Any]
    provenance: dict[str, Any]


class ReportResponse(BaseModel):
    report_id: str
    kind: str
    status: Literal["completed"]
    download_url: str


class ReportEntry(ReportResponse):
    symbol: str | None = None
    created_at: datetime


class ReportsResponse(BaseModel):
    reports: list[ReportEntry]


class QualityIssue(BaseModel):
    symbol: str | None = None
    code: str
    detail: str
    severity: str
    as_of_date: date


class QualityResponse(BaseModel):
    issues: list[QualityIssue]
    checks: list[dict[str, Any]]
