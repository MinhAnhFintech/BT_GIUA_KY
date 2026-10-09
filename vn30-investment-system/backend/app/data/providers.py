"""Data providers using vnstock new API (v4.0.9+)."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd

from backend.app.core.config import PROJECT_ROOT
from backend.app.data.contracts import Provenance, ProviderBatch

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
REQUEST_DELAY = 2.0  # seconds between API calls (community tier: 60 req/min)


def prepare_sdk() -> None:
    """Read a user-owned dotenv only into this process before importing the SDK."""
    from dotenv import dotenv_values

    if not os.environ.get("VNSTOCK_API_KEY"):
        key = dotenv_values(PROJECT_ROOT / ".env").get("VNSTOCK_API_KEY")
        if key:
            os.environ["VNSTOCK_API_KEY"] = key


def _batch(df: pd.DataFrame, source: str, end: date) -> ProviderBatch:
    return ProviderBatch(
        df.to_dict("records"),
        Provenance(
            source=f"vnstock_{source}",
            source_url="https://vnstocks.com/",
            fetched_at=_now_utc(),
            as_of_date=end,
            payload_sha256=_hash_df(df),
        ),
    )


def _hash_df(df: pd.DataFrame) -> str:
    """SHA256 hash of DataFrame content for provenance tracking."""
    payload = df.to_json(orient="split", date_format="iso", force_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(UTC)


class VnstockPriceProvider:
    """Fetch OHLCV data via vnstock.api.quote.Quote."""

    def __init__(self, source: str = "VCI"):
        self.source = source

    def prices(self, symbol: str, start: date, end: date) -> ProviderBatch:
        """Fetch price history for a symbol."""
        prepare_sdk()
        from vnstock.api.quote import Quote

        logger.info("Fetching prices for %s from %s to %s", symbol, start, end)
        time.sleep(REQUEST_DELAY)

        q = Quote(symbol=symbol, source=self.source)
        df = q.history(start=start.isoformat(), end=end.isoformat())

        if df is None or df.empty:
            raise ValueError(f"No price data for {symbol}")

        records = df.to_dict("records")
        payload_hash = _hash_df(df)

        provenance = Provenance(
            source=f"vnstock_{self.source}",
            source_url=f"https://vnstock.vn/quote/{symbol}",
            fetched_at=_now_utc(),
            as_of_date=end,
            payload_sha256=payload_hash,
        )

        return ProviderBatch(
            records=records,
            provenance=provenance,
            warnings=("PRICE_UNIT_NOT_VERIFIED", "ADJUSTMENT_NOT_VERIFIED"),
        )


class VnstockFundamentalsProvider:
    """Fetch financial statements via vnstock.api.financial.Finance."""

    def __init__(self, source: str = "VCI"):
        self.source = source

    def fundamentals(self, symbol: str, period: str = "quarter") -> ProviderBatch:
        prepare_sdk()
        records = []
        for kind, fetch in (
            ("balance", self.balance_sheet),
            ("income", self.income_statement),
            ("cashflow", self.cash_flow),
            ("ratio", self.ratio),
        ):
            df = fetch(symbol, period)
            if df is None or df.empty:
                continue
            df = df.copy()
            df.columns = [str(c[-1] if isinstance(c, tuple) else c) for c in df.columns]
            for row in df.to_dict("records"):
                row["statement"] = kind
                records.append(row)
        return _batch(pd.DataFrame(records), self.source, date.today())

    def balance_sheet(self, symbol: str, period: str = "quarter") -> pd.DataFrame | None:
        """Fetch balance sheet."""
        from vnstock.api.financial import Finance

        logger.info("Fetching balance sheet for %s (%s)", symbol, period)
        time.sleep(REQUEST_DELAY)
        try:
            f = Finance(symbol=symbol, source=self.source)
            return f.balance_sheet(period=period, lang="en")
        except Exception as e:
            logger.warning("Balance sheet fetch failed for %s: %s", symbol, type(e).__name__)
            return None

    def income_statement(self, symbol: str, period: str = "quarter") -> pd.DataFrame | None:
        """Fetch income statement."""
        from vnstock.api.financial import Finance

        logger.info("Fetching income statement for %s (%s)", symbol, period)
        time.sleep(REQUEST_DELAY)
        try:
            f = Finance(symbol=symbol, source=self.source)
            return f.income_statement(period=period, lang="en")
        except Exception as e:
            logger.warning("Income statement fetch failed for %s: %s", symbol, type(e).__name__)
            return None

    def cash_flow(self, symbol: str, period: str = "quarter") -> pd.DataFrame | None:
        """Fetch cash flow statement."""
        from vnstock.api.financial import Finance

        logger.info("Fetching cash flow for %s (%s)", symbol, period)
        time.sleep(REQUEST_DELAY)
        try:
            f = Finance(symbol=symbol, source=self.source)
            return f.cash_flow(period=period, lang="en")
        except Exception as e:
            logger.warning("Cash flow fetch failed for %s: %s", symbol, type(e).__name__)
            return None

    def ratio(self, symbol: str, period: str = "quarter") -> pd.DataFrame | None:
        """Fetch financial ratios."""
        from vnstock.api.financial import Finance

        logger.info("Fetching ratios for %s (%s)", symbol, period)
        time.sleep(REQUEST_DELAY)
        try:
            f = Finance(symbol=symbol, source=self.source)
            return f.ratio(period=period, lang="en")
        except Exception as e:
            logger.warning("Ratio fetch failed for %s: %s", symbol, type(e).__name__)
            return None


class VnstockNewsProvider:
    """Fetch news via vnstock.api.company.Company."""

    def __init__(self, source: str = "VCI"):
        self.source = source

    def news(
        self, symbol: str, start: datetime | None = None, end: datetime | None = None
    ) -> ProviderBatch:
        """Fetch news for a symbol."""
        prepare_sdk()
        from vnstock.api.company import Company

        logger.info("Fetching news for %s", symbol)
        time.sleep(REQUEST_DELAY)
        try:
            c = Company(symbol=symbol, source=self.source)
            df = c.news()
            return _batch(
                df if df is not None else pd.DataFrame(),
                self.source,
                end.date() if end else date.today(),
            )
        except Exception as e:
            logger.warning("News fetch failed for %s: %s", symbol, type(e).__name__)
            return _batch(pd.DataFrame(), self.source, end.date() if end else date.today())


class VnstockUniverseProvider:
    """Fetch VN30 membership via vnstock.api.listing.Listing."""

    def members(self, as_of: date | None = None) -> list[str]:
        """Get current VN30 members."""
        from vnstock.api.listing import Listing

        logger.info("Fetching VN30 members")
        time.sleep(REQUEST_DELAY)
        listing = Listing()
        vn30 = listing.symbols_by_group("VN30")
        return vn30.tolist()

    def company_overview(self, symbol: str) -> pd.DataFrame | None:
        """Get company overview."""
        from vnstock.api.company import Company

        time.sleep(REQUEST_DELAY)
        try:
            c = Company(symbol=symbol, source="VCI")
            return c.overview()
        except Exception as e:
            logger.warning("Company overview failed for %s: %s", symbol, type(e).__name__)
            return None
