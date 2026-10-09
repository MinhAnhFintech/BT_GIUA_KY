"""SQLite ingestion retaining source timestamps and immutable response vintages."""

from __future__ import annotations

import calendar
import hashlib
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import FundamentalValue, NewsItem, PriceBar, Stock
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


def get_latest_price_date(symbol):
    with Session(engine) as session:
        return session.scalar(
            select(func.max(PriceBar.as_of_date)).where(PriceBar.symbol == symbol)
        )


def save_prices(symbol, batch):
    with Session(engine) as session:
        _stock(session, symbol)
        for row in batch.records:
            ts = _timestamp(row.get("time", row.get("date")))
            if ts is None:
                continue
            values = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            if not all(pd.notna(v) for v in values.values()):
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
                    PriceBar.payload_sha256 == audit["payload_sha256"],
                )
            )
            if existing is None:
                session.add(
                    PriceBar(
                        symbol=symbol,
                        **values,
                        **audit,
                        price_unit="SOURCE_NATIVE_UNVERIFIED",
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
                    not in ("yearReport", "year", "lengthReport", "quarter", "symbol", "statement")
                ]
            elif row.get("item_en") or row.get("item"):
                label = (
                    row.get("item_en") or row.get("item")
                    if row.get("statement") == "ratio"
                    else row.get("item") or row.get("item_en")
                )
                for k, v in row.items():
                    try:
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
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    continue
                if not pd.notna(value):
                    continue
                metric = str(row.get("statement", "ratio")) + ":" + metric
                existing = session.scalar(
                    select(FundamentalValue).where(
                        FundamentalValue.symbol == symbol,
                        FundamentalValue.metric == metric,
                        FundamentalValue.period_end == end,
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
                            unit="SOURCE_NATIVE",
                            original_unit="SOURCE_NATIVE",
                            published_at=batch.provenance.fetched_at,
                            available_at=batch.provenance.fetched_at,
                            publication_inferred=True,
                            revision=batch.provenance.payload_sha256,
                            **_audit(batch),
                        )
                    )
        session.commit()


def save_news(batch, symbol):
    with Session(engine) as session:
        for row in batch.records:
            title = row.get("title", row.get("newsTitle", row.get("news_title")))
            url = row.get("url", row.get("newsUrl", row.get("news_url", "")))
            published = _timestamp(
                row.get(
                    "published_at",
                    row.get("publishDate", row.get("publish_time", row.get("publishTime"))),
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
                session.add(
                    NewsItem(
                        dedup_hash=digest,
                        title=str(title),
                        url=str(url),
                        published_at=published,
                        available_at=max(published, batch.provenance.fetched_at),
                        symbols=[symbol],
                        timestamp_verified=False,
                        **_audit(batch),
                    )
                )
        session.commit()


def get_prices(symbol, start, end, known_at=None):
    with Session(engine) as session:
        stmt = select(PriceBar).where(
            PriceBar.symbol == symbol, PriceBar.as_of_date >= start, PriceBar.as_of_date <= end
        )
        if known_at is not None:
            stmt = stmt.where(PriceBar.available_at <= known_at)
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
            )
            for b in bars
        ]
        return (
            pd.DataFrame(rows).drop_duplicates("time", keep="last").sort_values("time")
            if rows
            else pd.DataFrame()
        )


def get_fundamentals(symbol, known_at=None):
    with Session(engine) as session:
        stmt = select(FundamentalValue).where(FundamentalValue.symbol == symbol)
        if known_at is not None:
            stmt = stmt.where(FundamentalValue.available_at <= known_at)
        vals = session.scalars(
            stmt.order_by(FundamentalValue.period_end, FundamentalValue.fetched_at)
        ).all()
        rows = [
            dict(
                id=v.id,
                period_end=v.period_end,
                period_type=v.period_type,
                metric=v.metric,
                value=float(v.value),
                source=v.source,
                source_url=v.source_url,
                available_at=v.available_at,
                publication_inferred=v.publication_inferred,
            )
            for v in vals
        ]
        return (
            pd.DataFrame(rows).drop_duplicates(["period_end", "metric"], keep="last")
            if rows
            else pd.DataFrame()
        )


def get_news(symbols, days, known_at=None):
    cutoff = known_at or datetime.now(UTC)
    with Session(engine) as session:
        items = session.scalars(
            select(NewsItem).where(
                NewsItem.available_at <= cutoff,
                NewsItem.published_at <= cutoff,
                NewsItem.published_at >= cutoff - timedelta(days=days),
            )
        ).all()
        return pd.DataFrame(
            [
                dict(
                    id=n.id,
                    title=n.title,
                    url=n.url,
                    published_at=n.published_at,
                    source=n.source,
                    source_url=n.source_url,
                )
                for n in items
                if any(s in n.symbols for s in symbols)
            ]
        )


def record_data_quality_issue(issue):
    with Session(engine) as session:
        session.add(issue)
        session.commit()


def save_universe_snapshot(batch):
    raise ValueError("Current membership cannot be persisted as a verified historical snapshot")
