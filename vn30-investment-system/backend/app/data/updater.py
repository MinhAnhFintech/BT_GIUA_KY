"""Refresh stages, independent source failures, SQLite quality audit and timings."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

import pandas as pd

from backend.app.core.config import load_settings
from backend.app.data.contracts import Provenance, ProviderBatch
from backend.app.data.providers import (
    VnstockFundamentalsProvider,
    VnstockNewsProvider,
    VnstockPriceProvider,
    source_url,
)
from backend.app.data.store import (
    get_latest_price_date,
    latest_financial_fetch,
    record_data_quality_issue,
    save_financial_fetch,
    save_fundamentals,
    save_news,
    save_prices,
)
from backend.app.data.validator import validate_fundamentals, validate_news, validate_prices

logger = logging.getLogger(__name__)


class DataUpdater:
    def __init__(self, settings=None):
        self.settings = settings or load_settings()
        source = self.settings.sources["provider_source"]
        self.price_provider = VnstockPriceProvider(source)
        self.fundamentals_provider = VnstockFundamentalsProvider(source)
        self.news_provider = VnstockNewsProvider(source)

    def _audit(self, issues):
        for issue in issues:
            record_data_quality_issue(issue)
        return len(issues)

    def _financial_statement(self, symbol, kind, fetch, period, as_of):
        checked = latest_financial_fetch(symbol, kind, period, self.fundamentals_provider.source)
        cache_hours = self.settings.sources.get("financial_cache_hours", 24)
        if checked is not None and (
            checked.as_of_date == as_of
            and 0 <= (datetime.now(UTC) - checked.fetched_at).total_seconds() < cache_hours * 3600
        ):
            return {
                "records": checked.unit_metadata.get("records", 0),
                "latest_period": checked.unit_metadata.get("latest_period"),
                "quality_issues": 0,
                "cached": True,
            }
        frame = fetch(symbol, period)
        if frame is None or frame.empty:
            raise ValueError("SOURCE_RETURNED_NO_DATA")
        frame = frame.copy()
        frame.columns = [str(col[-1] if isinstance(col, tuple) else col) for col in frame.columns]
        if frame.columns.duplicated().any():
            raise ValueError("SOURCE_FINANCIAL_COLUMNS_DUPLICATE")
        frame["statement"] = kind
        digest = hashlib.sha256(
            frame.to_json(orient="split", date_format="iso", force_ascii=False).encode()
        ).hexdigest()
        provenance = Provenance(
            "vnstock/" + self.fundamentals_provider.source.upper(),
            source_url(
                self.fundamentals_provider.source,
                "ratios" if kind == "ratio" else "fundamentals",
                symbol,
            ),
            datetime.now(UTC),
            as_of,
            digest,
        )
        batch = ProviderBatch(
            frame.to_dict("records"),
            provenance,
            ("SOURCE_ENDPOINT_GROUP", "SOURCE_UNITS_NOT_VERIFIED", "PUBLICATION_NOT_VERIFIED"),
        )
        count = self._audit(validate_fundamentals(frame, symbol, self.settings))
        save_fundamentals(symbol, batch)
        latest_period = _latest_period(frame, period)
        save_financial_fetch(symbol, kind, period, batch, latest_period)
        return {
            "records": len(frame),
            "quality_issues": count,
            "latest_period": latest_period,
            "cached": False,
        }

    def refresh_all(self, symbols, as_of_date):
        results = []
        total_started = perf_counter()
        for symbol in symbols:
            result = {"symbol": symbol, "stages": {}, "timing": {}, "details": {}}
            source = getattr(
                self.price_provider, "source", self.settings.sources["provider_source"]
            )
            latest = get_latest_price_date(symbol, source=source)
            # Re-fetch the last session: an intraday bar may later receive its closing price.
            start = latest if latest else as_of_date - timedelta(days=730)

            def prices(symbol=symbol, start=start):
                if start > as_of_date:
                    return {"records": 0, "quality_issues": 0, "cached": True}
                batch = self.price_provider.prices(symbol, start, as_of_date)
                count = self._audit(
                    validate_prices(pd.DataFrame(batch.records), symbol, self.settings)
                )
                save_prices(symbol, batch)
                return {"records": len(batch.records), "quality_issues": count}

            def news(symbol=symbol):
                window = self.settings.data_requirements["news_window_days"]
                batch = self.news_provider.news(
                    symbol,
                    datetime.combine(as_of_date - timedelta(days=window), datetime.min.time(), UTC),
                    datetime.combine(as_of_date, datetime.max.time(), UTC),
                )
                count = self._audit(
                    validate_news(pd.DataFrame(batch.records), symbol, self.settings)
                )
                save_news(batch, symbol)
                return {"records": len(batch.records), "quality_issues": count}

            tasks = {"prices": prices, "news": news}
            for period in ("quarter", "year"):
                for kind, fetch in (
                    ("income", self.fundamentals_provider.income_statement),
                    ("balance", self.fundamentals_provider.balance_sheet),
                    ("cashflow", self.fundamentals_provider.cash_flow),
                    ("ratio", self.fundamentals_provider.ratio),
                ):
                    tasks[f"fundamentals_{period}_{kind}"] = (
                        lambda symbol=symbol, kind=kind, fetch=fetch, period=period: (
                            self._financial_statement(symbol, kind, fetch, period, as_of_date)
                        )
                    )
            for name, task in tasks.items():
                started = perf_counter()
                try:
                    result["details"][name] = task()
                    result["stages"][name] = "OK"
                except Exception as exc:
                    result["stages"][name] = "FETCH_FAILED_" + type(exc).__name__
                    logger.warning("Refresh %s %s failed (%s)", symbol, name, type(exc).__name__)
                finally:
                    result["timing"][name] = round(perf_counter() - started, 4)
            financial_states = [
                status
                for name, status in result["stages"].items()
                if name.startswith("fundamentals_")
            ]
            result["stages"]["fundamentals"] = (
                "OK"
                if all(status == "OK" for status in financial_states)
                else "PARTIAL_SOURCE_FAILURE"
                if any(status == "OK" for status in financial_states)
                else "FETCH_FAILED"
            )
            results.append(result)
        return {
            "symbols": results,
            "as_of_date": as_of_date.isoformat(),
            "duration_seconds": round(perf_counter() - total_started, 4),
        }


def _latest_period(frame, period):
    """Period metadata is derived from explicit fiscal labels, never from fetch date."""
    import re

    pattern = r"\d{4}-Q[1-4]" if period == "quarter" else r"\d{4}"
    columns = [str(c) for c in frame.columns if re.fullmatch(pattern, str(c))]
    if columns:
        return max(columns)
    year_name = next((name for name in ("yearReport", "year") if name in frame), None)
    if year_name is None:
        return None
    years = pd.to_numeric(frame[year_name], errors="coerce")
    if period == "year":
        return str(int(years.max())) if years.notna().any() else None
    quarter_name = next((name for name in ("lengthReport", "quarter") if name in frame), None)
    if quarter_name is None:
        return None
    quarters = pd.to_numeric(frame[quarter_name], errors="coerce")
    rows = [
        (int(y), int(q))
        for y, q in zip(years, quarters, strict=True)
        if pd.notna(y) and pd.notna(q) and 1 <= q <= 4
    ]
    return f"{max(rows)[0]}-Q{max(rows)[1]}" if rows else None
