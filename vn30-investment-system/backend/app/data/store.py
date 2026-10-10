"""SQLite ingestion retaining source timestamps and immutable response vintages."""

from __future__ import annotations

import calendar
import hashlib
import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import FundamentalValue, NewsItem, PriceBar, SourceFetch, Stock
from backend.app.db.session import initialize_database

engine = initialize_database()


def _stock(session, symbol):
    if session.get(Stock, symbol) is None:
        session.add(Stock(symbol=symbol, sector="Unknown"))
        session.flush()


def _audit(batch):
    return vars(batch.provenance)


def _timestamp(value):
    if value is None or pd.isna(value):
        return None
    try:
        ts = pd.Timestamp(value)
        return (
            ts.tz_localize("Asia/Ho_Chi_Minh").to_pydatetime().astimezone(UTC)
            if ts.tzinfo is None
            else ts.to_pydatetime().astimezone(UTC)
        )
    except (ValueError, TypeError):
        return None


def _source_name(source):
    return source if source.startswith("vnstock/") else "vnstock/" + source.upper()


def get_latest_price_date(symbol, source=None):
    with Session(engine) as session:
        stmt = select(func.max(PriceBar.as_of_date)).where(PriceBar.symbol == symbol)
        if source is not None:
            stmt = stmt.where(PriceBar.source == _source_name(source))
        return session.scalar(stmt)


def latest_financial_fetch(symbol, kind, period, source):
    """Latest successful check for one statement/period/source, including unchanged data."""
    with Session(engine) as session:
        return session.scalar(
            select(SourceFetch)
            .where(
                SourceFetch.symbol == symbol,
                SourceFetch.kind == f"fundamentals_{period}_{kind}",
                SourceFetch.source == _source_name(source),
                SourceFetch.schema_version == "financial-cache-v2",
            )
            .order_by(SourceFetch.fetched_at.desc())
            .limit(1)
        )


def save_financial_fetch(symbol, kind, period, batch, latest_period):
    with Session(engine) as session:
        session.add(
            SourceFetch(
                symbol=symbol,
                kind=f"fundamentals_{period}_{kind}",
                schema_version="financial-cache-v2",
                unit_metadata={"latest_period": latest_period, "records": len(batch.records)},
                **_audit(batch),
            )
        )
        session.commit()


def save_prices(symbol, batch):
    with Session(engine) as session:
        _stock(session, symbol)
        for row in batch.records:
            ts = _timestamp(row.get("time", row.get("date")))
            if ts is None:
                continue
            try:
                values = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in values.values()):
                continue
            if (
                min(values[k] for k in ("open", "high", "low", "close")) <= 0
                or values["volume"] < 0
            ):
                continue
            if values["high"] < max(values["open"], values["close"], values["low"]) or values[
                "low"
            ] > min(values["open"], values["close"]):
                continue
            audit = _audit(batch).copy()
            audit["as_of_date"] = ts.astimezone(
                __import__("datetime").timezone(timedelta(hours=7))
            ).date()
            existing = session.scalar(
                select(PriceBar).where(
                    PriceBar.symbol == symbol,
                    PriceBar.as_of_date == audit["as_of_date"],
                    PriceBar.source == audit["source"],
                    PriceBar.payload_sha256 == audit["payload_sha256"],
                )
            )
            if existing is None:
                session.add(
                    PriceBar(
                        symbol=symbol,
                        **values,
                        **audit,
                        price_unit=row.get("price_unit", "SOURCE_NATIVE_UNVERIFIED"),
                        available_at=batch.provenance.fetched_at,
                    )
                )
        session.commit()


def save_fundamentals(symbol, batch):
    with Session(engine) as session:
        _stock(session, symbol)
        for row in batch.records:
            year = row.get("yearReport", row.get("year"))
            quarter = row.get("lengthReport", row.get("quarter"))
            normalized = []
            if year is not None and pd.notna(year):
                y = int(year)
                q = int(quarter) if quarter is not None and pd.notna(quarter) else 0
                month = q * 3 if 1 <= q <= 4 else 12
                end = date(y, month, calendar.monthrange(y, month)[1])
                normalized = [
                    (str(k), v, end, "quarter" if 1 <= q <= 4 else "year")
                    for k, v in row.items()
                    if k
                    not in (
                        "yearReport",
                        "year",
                        "lengthReport",
                        "quarter",
                        "symbol",
                        "statement",
                        "unit",
                        "original_unit",
                    )
                ]
            elif row.get("item_en") or row.get("item"):
                label = (
                    row.get("item_en") or row.get("item")
                    if row.get("statement") == "ratio"
                    else row.get("item") or row.get("item_en")
                )
                for k, v in row.items():
                    try:
                        if len(str(k)) == 4 and str(k).isdigit():
                            normalized.append((str(label), v, date(int(k), 12, 31), "year"))
                            continue
                        y, q = str(k).split("-Q")
                        month = int(q) * 3
                        normalized.append(
                            (
                                str(label),
                                v,
                                date(int(y), month, calendar.monthrange(int(y), month)[1]),
                                "quarter",
                            )
                        )
                    except (ValueError, TypeError):
                        continue
            for metric, value, end, period in normalized:
                # Persist explicit source NULLs as a new vintage so old SDK-filled zeros
                # cannot remain current after a corrected refresh.
                if value is None or pd.isna(value):
                    value = None
                else:
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        continue
                    if not math.isfinite(value):
                        value = None
                metric = str(row.get("statement", "ratio")) + ":" + metric
                existing = session.scalar(
                    select(FundamentalValue).where(
                        FundamentalValue.symbol == symbol,
                        FundamentalValue.metric == metric,
                        FundamentalValue.period_end == end,
                        FundamentalValue.period_type == period,
                        FundamentalValue.source == batch.provenance.source,
                        FundamentalValue.revision == batch.provenance.payload_sha256,
                    )
                )
                if existing is None:
                    session.add(
                        FundamentalValue(
                            symbol=symbol,
                            metric=metric,
                            value=value,
                            period_end=end,
                            period_type=period,
                            unit=_metric_unit(row, metric),
                            original_unit=str(
                                row.get("original_unit") or _metric_unit(row, metric)
                            ),
                            published_at=batch.provenance.fetched_at,
                            available_at=batch.provenance.fetched_at,
                            publication_inferred=True,
                            revision=batch.provenance.payload_sha256,
                            missing_reason="SOURCE_VALUE_MISSING" if value is None else None,
                            **_audit(batch),
                        )
                    )
        session.commit()


def _metric_unit(row, label):
    explicit = row.get("unit")
    if explicit == "SOURCE_NATIVE_UNVERIFIED":
        return explicit
    if explicit in {"ratio", "percent", "multiple", "VND", "million_VND", "billion_VND"}:
        return explicit
    # A source's explicit printed unit is metadata; magnitude is never a unit signal.
    if "(%)" in label or label.endswith("%"):
        return "percent"
    if "Bn. VND" in label:
        return "billion_VND"
    return "SOURCE_NATIVE_UNVERIFIED"


def save_news(batch, symbol):
    with Session(engine) as session:
        for row in batch.records:
            title = row.get("title", row.get("newsTitle", row.get("news_title")))
            url = row.get("url", row.get("newsUrl", row.get("news_url", "")))
            published = _timestamp(
                row.get(
                    "published_at",
                    row.get(
                        "publishDate",
                        row.get("publish_time", row.get("publishTime", row.get("public_date"))),
                    ),
                )
            )
            if not title or published is None:
                continue
            digest = hashlib.sha256((str(title) + str(url)).encode()).hexdigest()
            existing = session.scalar(select(NewsItem).where(NewsItem.dedup_hash == digest))
            if existing:
                if symbol not in existing.symbols:
                    existing.symbols = existing.symbols + [symbol]
            else:
                existing = NewsItem(
                    dedup_hash=digest,
                    title=str(title),
                    url=str(url),
                    published_at=published,
                    available_at=max(published, batch.provenance.fetched_at),
                    symbols=[symbol],
                    timestamp_verified=False,
                    **_audit(batch),
                )
                session.add(existing)
                session.flush()
            association = session.scalar(
                select(SourceFetch).where(
                    SourceFetch.kind == "news_symbol",
                    SourceFetch.symbol == symbol,
                    SourceFetch.payload_sha256 == digest,
                    SourceFetch.source == batch.provenance.source,
                )
            )
            if association is None:
                audit = _audit(batch).copy()
                audit["payload_sha256"] = digest
                session.add(
                    SourceFetch(
                        kind="news_symbol",
                        symbol=symbol,
                        schema_version="news-association-v1",
                        unit_metadata={"news_id": existing.id},
                        **audit,
                    )
                )
        session.commit()


def get_prices(symbol, start, end, known_at=None, source=None):
    with Session(engine) as session:
        stmt = select(PriceBar).where(
            PriceBar.symbol == symbol, PriceBar.as_of_date >= start, PriceBar.as_of_date <= end
        )
        if known_at is not None:
            stmt = stmt.where(PriceBar.available_at <= known_at)
        if source is not None:
            stmt = stmt.where(PriceBar.source == _source_name(source))
        bars = session.scalars(stmt.order_by(PriceBar.as_of_date, PriceBar.fetched_at)).all()
        rows = [
            dict(
                time=b.as_of_date,
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=b.volume,
                id=b.id,
                source=b.source,
                source_url=b.source_url,
                price_unit=b.price_unit,
                adjustment_verified=b.adjustment_verified,
                fetched_at=b.fetched_at,
                available_at=b.available_at,
                as_of_date=b.as_of_date,
                payload_sha256=b.payload_sha256,
            )
            for b in bars
        ]
        return (
            pd.DataFrame(rows).drop_duplicates("time", keep="last").sort_values("time")
            if rows
            else pd.DataFrame()
        )


def get_fundamentals(symbol, known_at=None, source=None):
    with Session(engine) as session:
        stmt = select(FundamentalValue).where(FundamentalValue.symbol == symbol)
        if known_at is not None:
            stmt = stmt.where(
                FundamentalValue.available_at <= known_at,
                FundamentalValue.period_end <= known_at.date(),
            )
        if source is not None:
            stmt = stmt.where(FundamentalValue.source == _source_name(source))
        vals = session.scalars(
            stmt.order_by(FundamentalValue.period_end, FundamentalValue.fetched_at)
        ).all()
        rows = [
            dict(
                id=v.id,
                period_end=v.period_end,
                period_type=v.period_type,
                metric=v.metric,
                value=float(v.value) if v.value is not None else None,
                source=v.source,
                source_url=v.source_url,
                available_at=v.available_at,
                publication_inferred=v.publication_inferred,
                vintage_verified=v.vintage_verified,
                published_at=v.published_at,
                fetched_at=v.fetched_at,
                as_of_date=v.as_of_date,
                unit=v.unit,
                original_unit=v.original_unit,
                revision=v.revision,
                payload_sha256=v.payload_sha256,
                missing_reason=v.missing_reason,
            )
            for v in vals
        ]
        return (
            pd.DataFrame(rows).drop_duplicates(["period_end", "period_type", "metric"], keep="last")
            if rows
            else pd.DataFrame()
        )


def get_news(symbols, days, known_at=None, source=None):
    cutoff = known_at or datetime.now(UTC)
    with Session(engine) as session:
        items = session.scalars(
            select(NewsItem).where(
                NewsItem.available_at <= cutoff,
                NewsItem.published_at <= cutoff,
                NewsItem.published_at >= cutoff - timedelta(days=days),
            )
        ).all()
        associations = session.scalars(
            select(SourceFetch).where(
                SourceFetch.kind == "news_symbol",
                SourceFetch.symbol.in_(symbols),
                SourceFetch.fetched_at <= cutoff,
            )
        ).all()
        eligible = {}
        for association in sorted(associations, key=lambda a: a.fetched_at):
            if source is None or association.source == _source_name(source):
                eligible[association.unit_metadata.get("news_id")] = association
        all_associated = set(
            session.scalars(
                select(SourceFetch.payload_sha256).where(SourceFetch.kind == "news_symbol")
            ).all()
        )
        return pd.DataFrame(
            [
                dict(
                    id=n.id,
                    title=n.title,
                    url=n.url,
                    published_at=n.published_at,
                    source=eligible[n.id].source if n.id in eligible else n.source,
                    source_url=eligible[n.id].source_url if n.id in eligible else n.source_url,
                    fetched_at=eligible[n.id].fetched_at if n.id in eligible else n.fetched_at,
                    available_at=max(n.published_at, eligible[n.id].fetched_at)
                    if n.id in eligible
                    else n.available_at,
                    as_of_date=n.as_of_date,
                    payload_sha256=n.payload_sha256,
                    timestamp_verified=n.timestamp_verified,
                )
                for n in items
                if n.id in eligible
                or (
                    n.dedup_hash not in all_associated
                    and len(n.symbols) == 1
                    and n.symbols[0] in symbols
                    and (source is None or n.source == _source_name(source))
                )
            ]
        )


def record_data_quality_issue(issue):
    with Session(engine) as session:
        session.add(issue)
        session.commit()


def save_universe_snapshot(batch):
    raise ValueError("Current membership cannot be persisted as a verified historical snapshot")
