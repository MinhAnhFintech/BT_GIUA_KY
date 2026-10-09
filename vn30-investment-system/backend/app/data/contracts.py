"""Provider interfaces; data provenance travels with every provider response."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Provenance:
    """Recorded source and date; fetched_at must be timezone-aware."""

    source: str
    source_url: str
    fetched_at: datetime
    as_of_date: date
    payload_sha256: str

    def __post_init__(self) -> None:
        """Prevent unauditable records or ambiguous timestamps."""
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        if not self.source or not self.source_url:
            raise ValueError("source and source_url required")
        if len(self.payload_sha256) != 64:
            raise ValueError("Expected SHA256 hex digest")
        try:
            int(self.payload_sha256, 16)
        except ValueError as error:
            raise ValueError("Invalid SHA256 digest") from error


@dataclass(frozen=True)
class ProviderBatch:
    """Normalized records, provenance, and warnings about units or availability."""

    records: list[dict[str, Any]]
    provenance: Provenance
    warnings: tuple[str, ...] = ()


class PriceProvider(Protocol):
    """Fetch raw and separately verified adjusted prices, never conflate them."""

    def prices(self, symbol: str, start: date, end: date) -> ProviderBatch:
        """Fetch inclusive date range, leaving unit verification to the adapter."""
        ...


class FundamentalsProvider(Protocol):
    """Expose publication date and revision vintage when available."""

    def fundamentals(self, symbol: str, period: Literal["quarter", "year"]) -> ProviderBatch:
        """Fetch statements; missing publication timestamp must be flagged."""
        ...


class NewsProvider(Protocol):
    """Return metadata only, with trustworthy publication timestamps."""

    def news(self, symbol: str, start: datetime, end: datetime) -> ProviderBatch:
        """Return title, URL, publication time, and an independently written summary."""
        ...


class UniverseProvider(Protocol):
    """A historical query must return a dated authoritative snapshot or fail."""

    def members(self, as_of: date) -> ProviderBatch:
        """Never label a current membership response as historical membership."""
        ...
