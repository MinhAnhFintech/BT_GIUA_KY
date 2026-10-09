"""Synthetic unit-test fixtures only: these values are never production market data."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from backend.app.db.models import AnalysisResult, AnalysisRun, FundamentalValue, PriceBar, Stock
from backend.app.db.session import initialize_database

NOW = datetime(2026, 10, 9, 8, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path):
    """Isolated, temporary fixture DB; never uses data/vn30.sqlite3."""
    result = initialize_database(tmp_path / "fixture.sqlite3")
    yield result
    result.dispose()


def test_schema_is_idempotent_and_foreign_keys_enabled(engine) -> None:
    tables = inspect(engine).get_table_names()
    assert {
        "price_bars",
        "fundamental_values",
        "universe_snapshots",
        "universe_members",
        "news_items",
        "corporate_actions",
        "trading_sessions",
        "analysis_runs",
        "analysis_results",
        "data_quality_issues",
        "backtest_runs",
    }.issubset(tables)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    from backend.app.db.models import Base

    Base.metadata.create_all(engine)
    assert inspect(engine).get_table_names() == tables


def test_missing_component_stays_null(engine) -> None:
    with Session(engine) as session:
        session.add(
            AnalysisRun(
                id="TEST_RUN",
                as_of_date=date(2026, 10, 9),
                created_at=NOW,
                scoring_version="TEST",
                config_hash="0" * 64,
                data_hash="0" * 64,
                input_record_ids={},
                config_snapshot={},
            )
        )
        session.commit()
        session.add(
            AnalysisResult(
                run_id="TEST_RUN",
                symbol="TEST",
                fa=None,
                ta=70,
                news=None,
                total_score=None,
                status="PARTIAL_ANALYSIS",
                reasons=["SYNTHETIC_MISSING_FA_NEWS"],
                breakdown={},
            )
        )
        session.commit()
        row = session.get(AnalysisResult, ("TEST_RUN", "TEST"))
        assert row.fa is None and row.news is None and row.total_score is None


def test_partial_analysis_cannot_have_total_score(engine) -> None:
    with Session(engine) as session:
        session.add(
            AnalysisRun(
                id="TEST_RUN",
                as_of_date=date(2026, 10, 9),
                created_at=NOW,
                scoring_version="TEST",
                config_hash="0" * 64,
                data_hash="0" * 64,
                input_record_ids={},
                config_snapshot={},
            )
        )
        session.commit()
        session.add(
            AnalysisResult(
                run_id="TEST_RUN",
                symbol="TEST",
                fa=None,
                ta=70,
                news=None,
                total_score=24.5,
                status="PARTIAL_ANALYSIS",
                reasons=[],
                breakdown={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_financial_revisions_preserved_and_filtered_by_availability(engine) -> None:
    """Schema can retain future revisions separately; backtest engine tests arrive at stage 7."""
    with Session(engine) as session:
        session.add(Stock(symbol="TEST", sector="technology"))
        session.commit()
        for revision, value, available in [
            ("initial", 100, datetime(2026, 8, 14, tzinfo=UTC)),
            ("restated", 999, datetime(2026, 11, 1, tzinfo=UTC)),
        ]:
            session.add(
                FundamentalValue(
                    symbol="TEST",
                    source="SYNTHETIC_TEST_ONLY",
                    source_url="https://example.invalid",
                    fetched_at=NOW,
                    as_of_date=date(2026, 6, 30),
                    payload_sha256="0" * 64,
                    period_end=date(2026, 6, 30),
                    period_type="quarter",
                    metric="revenue",
                    value=value,
                    unit="VND",
                    original_unit="VND",
                    published_at=available,
                    available_at=available,
                    publication_inferred=False,
                    vintage_verified=True,
                    revision=revision,
                )
            )
        session.commit()
        rows = session.scalars(
            select(FundamentalValue).where(FundamentalValue.available_at <= NOW)
        ).all()
        assert len(rows) == 1
        assert float(rows[0].value) == 100
        assert rows[0].available_at.tzinfo == UTC
        assert len(session.scalars(select(FundamentalValue)).all()) == 2


def test_negative_prices_are_rejected(engine) -> None:
    with Session(engine) as session:
        session.add(Stock(symbol="TEST", sector="technology"))
        session.commit()
        session.add(
            PriceBar(
                symbol="TEST",
                source="SYNTHETIC_TEST_ONLY",
                source_url="https://example.invalid",
                fetched_at=NOW,
                as_of_date=date(2026, 10, 9),
                payload_sha256="0" * 64,
                open=100,
                high=101,
                low=-1,
                close=100,
                volume=100,
                available_at=NOW,
                price_unit="VND",
                adjustment_verified=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_naive_timestamp_rejected(engine) -> None:
    with Session(engine) as session:
        session.add(
            AnalysisRun(
                id="TEST",
                as_of_date=date(2026, 10, 9),
                created_at=NOW.replace(tzinfo=None),
                scoring_version="TEST",
                config_hash="0" * 64,
                data_hash="0" * 64,
                input_record_ids={},
                config_snapshot={},
            )
        )
        with pytest.raises(StatementError):
            session.commit()
        session.rollback()
