"""Verified Vnstock v4 KBS calls, process-only credentials and explicit provenance."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, date, datetime

import pandas as pd
from dotenv import load_dotenv

from backend.app.core.config import PROJECT_ROOT, load_settings
from backend.app.data.contracts import Provenance, ProviderBatch

logger = logging.getLogger(__name__)
VCI_BASE = "https://trading.vietcap.com.vn/api"
VCI_FINANCIAL_BASE = "https://iq.vietcap.com.vn/api/iq-insight-service"
KBS_BASE = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"


def source_url(source: str, kind: str, symbol: str | None = None) -> str:
    """Build a source-specific public endpoint URL without request secrets."""
    normalized = source.upper()
    if normalized == "VCI":
        if kind == "prices":
            return f"{VCI_BASE}/chart/OHLCChart/gap-chart"
        if kind == "fundamentals":
            return f"{VCI_FINANCIAL_BASE}/v1/company/{symbol}/financial-statement"
        if kind == "ratios":
            return f"{VCI_FINANCIAL_BASE}/v1/company/{symbol}/statistics-financial"
        if kind == "news":
            return f"{VCI_FINANCIAL_BASE}/v1/news?ticker={symbol}"
        return f"{VCI_BASE}/stock-list"
    if normalized == "KBS":
        if kind == "prices":
            return f"{KBS_BASE}/stocks/{symbol}/data_day"
        if kind == "fundamentals":
            return f"{KBS_BASE}/stock/finance-info"
        if kind == "news":
            return f"{KBS_BASE}/stockinfo/news/{symbol}"
        return f"{KBS_BASE}/market/index/stock/VN30"
    raise ValueError("UNSUPPORTED_PROVIDER_SOURCE")


def prepare_sdk() -> None:
    """Load user-owned .env into memory before importing SDK; never register/save keys."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
    os.environ["VNSTOCK_AGENT_TARGETS"] = "none"


def batch(frame: pd.DataFrame, source: str, url: str, as_of: date) -> ProviderBatch:
    """Do not infer monetary units or publication dates from provider labels."""
    if frame is None or frame.empty:
        raise ValueError("SOURCE_RETURNED_NO_DATA")
    digest = hashlib.sha256(
        frame.to_json(orient="split", date_format="iso", force_ascii=False).encode()
    ).hexdigest()
    return ProviderBatch(
        frame.to_dict("records"),
        Provenance(f"vnstock/{source.upper()}", url, datetime.now(UTC), as_of, digest),
        ("SOURCE_UNITS_NOT_VERIFIED",),
    )


class BaseProvider:
    def __init__(self, source: str | None = None):
        settings = load_settings().sources
        self.source = source or settings["provider_source"]
        self.delay = settings["request_interval_seconds"]
        self.base = settings["provider_base_url"]

    def wait(self) -> None:
        prepare_sdk()
        time.sleep(self.delay)


class VnstockPriceProvider(BaseProvider):
    def prices(self, symbol: str, start: date, end: date) -> ProviderBatch:
        """Use the method-form equity API confirmed against installed SDK."""
        self.wait()
        from vnstock import Market

        frame = (
            Market()
            .equity(symbol)
            .ohlcv(
                start=start.isoformat(),
                end=end.isoformat(),
                count=(end - start).days + 1,
                source=self.source,
            )
        )
        if frame is None or frame.empty or "time" not in frame:
            raise ValueError("SOURCE_RETURNED_NO_DATED_PRICES")
        dates = pd.to_datetime(frame["time"], errors="coerce").dt.date
        frame = frame.loc[dates.notna() & (dates >= start) & (dates <= end)].copy()
        return batch(frame, self.source, source_url(self.source, "prices", symbol), end)


def _select_vci_periods(raw, period, limit):
    """VCI quarter=5 is an annual ratio, while quarter=1..4 are quarterly vintages."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    year_name = next((n for n in ("year", "yearReport") if n in frame), None)
    quarter_name = next((n for n in ("quarter", "lengthReport") if n in frame), None)
    if year_name is None:
        raise ValueError("SOURCE_FINANCIAL_PERIOD_SCHEMA_INVALID")
    frame["_fiscal_year"] = pd.to_numeric(frame[year_name], errors="coerce")
    frame["_fiscal_quarter"] = (
        pd.to_numeric(frame[quarter_name], errors="coerce")
        if quarter_name is not None
        else (5 if period == "year" else None)
    )
    if period == "quarter":
        frame = frame.loc[frame._fiscal_quarter.between(1, 4)]
    else:
        frame = frame.loc[~frame._fiscal_quarter.between(1, 4)]
    frame = frame.dropna(subset=["_fiscal_year"])
    if frame.duplicated(["_fiscal_year", "_fiscal_quarter"]).any():
        raise ValueError("SOURCE_FINANCIAL_PERIOD_DUPLICATE")
    return (
        frame.sort_values(["_fiscal_year", "_fiscal_quarter"], ascending=False)
        .head(limit)
        .drop(columns=["_fiscal_year", "_fiscal_quarter"])
    )


class VnstockFundamentalsProvider(BaseProvider):
    def _fetch(self, symbol: str, period: str, kind: str) -> pd.DataFrame:
        self.wait()
        from vnstock import Fundamental

        settings = load_settings()
        limit = settings.sources["financial_period_limit"]
        if period == "quarter":
            limit = max(limit, settings.data_requirements["valuation_history_quarters"])
        if self.source.upper() == "VCI":
            # v4.0.9 public methods silently discard limit and ratios take oldest head(4).
            # Fetch the raw response first so selection and missing-value policy stay explicit.
            from vnstock.explorer.vci.financial import Finance

            finance = Finance(symbol=symbol, period=period, show_log=False)
            report_type = "ratio" if kind == "ratios" else kind
            raw = finance._get_report(
                report_type=report_type, period=period, mode="raw", limit=10000
            )
            selected = _select_vci_periods(raw, period, limit)
            if selected.empty:
                raise ValueError("SOURCE_RETURNED_NO_FINANCIAL_PERIODS")
            frame = finance._ratio_mapping(
                report_df=selected, lang="en", period_type=period, report_type=report_type
            )
            # Labels printed by SDK are not unit verification. Missing values remain missing.
            frame["unit"] = "SOURCE_NATIVE_UNVERIFIED"
            return frame
        domain = Fundamental().equity(symbol)
        return getattr(domain, kind)(
            period=period,
            source=self.source,
            limit=limit,
        )

    def balance_sheet(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        return self._fetch(symbol, period, "balance_sheet")

    def income_statement(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        return self._fetch(symbol, period, "income_statement")

    def cash_flow(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        return self._fetch(symbol, period, "cash_flow")

    def ratio(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        return self._fetch(symbol, period, "ratios")

    def fundamentals(self, symbol: str, period: str = "quarter") -> ProviderBatch:
        """Retain each statement's identity; errors propagate to independent refresh stages."""
        frames = []
        for kind, fetch in [
            ("income", self.income_statement),
            ("balance", self.balance_sheet),
            ("cashflow", self.cash_flow),
            ("ratio", self.ratio),
        ]:
            frame = fetch(symbol, period)
            if frame is not None and not frame.empty:
                frame = frame.copy()
                frame["statement"] = kind
                frames.append(frame)
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return batch(
            frame,
            self.source,
            source_url(self.source, "fundamentals", symbol),
            datetime.now(UTC).date(),
        )


class VnstockNewsProvider(BaseProvider):
    def news(
        self, symbol: str, start: datetime | None = None, end: datetime | None = None
    ) -> ProviderBatch:
        self.wait()
        from vnstock import Reference

        frame = Reference().company(symbol).news(source=self.source)
        if frame is not None and not frame.empty:
            # VCI names its timestamp public_date and link news_source_link.
            # Strip article bodies before passing records to the cache contract.
            frame = _news_metadata(frame)
            timestamps = pd.to_datetime(frame["published_at"], errors="coerce")
            if timestamps.dt.tz is None:
                timestamps = timestamps.dt.tz_localize("Asia/Ho_Chi_Minh")
            timestamps = timestamps.dt.tz_convert("UTC")
            valid = timestamps.notna()
            within = pd.Series(True, index=frame.index)
            if start is not None:
                within &= timestamps >= pd.Timestamp(start)
            if end is not None:
                within &= timestamps <= pd.Timestamp(end)
            frame = frame.loc[~valid | within].copy()
        return batch(
            frame,
            self.source,
            source_url(self.source, "news", symbol),
            end.date() if end else datetime.now(UTC).date(),
        )


def _news_metadata(frame):
    aliases = {
        "title": ("title", "news_title", "newsTitle"),
        "url": ("url", "news_url", "newsUrl", "news_source_link"),
        "published_at": (
            "published_at",
            "public_date",
            "publishDate",
            "publish_time",
            "publishTime",
            "pubDate",
        ),
    }
    output = pd.DataFrame(index=frame.index)
    for target, candidates in aliases.items():
        column = next((name for name in candidates if name in frame), None)
        output[target] = frame[column] if column is not None else None
    return output


class VnstockUniverseProvider(BaseProvider):
    def members(self, as_of: date | None = None) -> list[str]:
        """Reject historical lookup through a current-only endpoint."""
        from zoneinfo import ZoneInfo

        observed = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
        if as_of is not None and as_of != observed:
            raise ValueError("HISTORICAL_MEMBERSHIP_NOT_AVAILABLE")
        self.wait()
        from vnstock import Reference

        frame = Reference().equity.list_by_group("VN30", source=self.source)
        symbols = (
            frame["symbol"].astype(str).tolist()
            if isinstance(frame, pd.DataFrame)
            else frame.astype(str).tolist()
        )
        if len(set(symbols)) != 30:
            raise ValueError("INVALID_VN30_SCHEMA")
        return symbols

    def company_overview(self, symbol: str) -> pd.DataFrame:
        self.wait()
        from vnstock import Reference

        return Reference().company(symbol).info(source=self.source)
