"""Synthetic execution/PIT fixtures are isolated from the real market-data database."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.app.backtest.engine import run_backtest, simulate
from backend.app.core.config import load_settings
from backend.app.db import session as database
from backend.app.db.models import (
    BacktestRun,
    FundamentalValue,
    PriceBar,
    Stock,
    TradingSession,
    UniverseMember,
    UniverseSnapshot,
)


def market(prices, start=date(2026, 1, 5)):
    return [
        dict(
            date=str(start + timedelta(days=i)),
            symbol=symbol,
            open=price,
            close=price,
            volume=1_000_000,
        )
        for i, values in enumerate(prices)
        for symbol, price in values.items()
    ]


def frictionless(**extra):
    return dict(
        buy_fee=0,
        sell_fee=0,
        sell_tax=0,
        slippage=0,
        settlement_sessions=0,
        initial_cash=10_000_000,
        **extra,
    )


def test_retained_symbols_are_rebalanced_only_on_new_signal():
    rows = market(
        [
            {"FPT": 10_000, "MWG": 10_000},
            {"FPT": 10_000, "MWG": 10_000},
            {"FPT": 20_000, "MWG": 10_000},
            {"FPT": 20_000, "MWG": 10_000},
        ]
    )
    result = simulate(
        rows, {"2026-01-05": ["FPT", "MWG"], "2026-01-07": ["FPT", "MWG"]}, **frictionless()
    )
    assert not [t for t in result["trades"] if t["date"] == "2026-01-07"]
    retained_sales = [
        t
        for t in result["trades"]
        if t["date"] == "2026-01-08" and t["symbol"] == "FPT" and t["side"] == "SELL"
    ]
    assert retained_sales[0]["quantity"] == 200
    assert any(
        t["date"] == "2026-01-08" and t["symbol"] == "MWG" and t["side"] == "BUY"
        for t in result["trades"]
    )


def test_open_participation_never_reads_same_day_volume():
    rows = market([{"FPT": 10_000}] * 3)
    rows[0]["volume"] = 10_000
    rows[1]["volume"] = 1_000_000
    result = simulate(rows, {"2026-01-05": ["FPT"]}, **frictionless())
    assert result["trades"][0]["quantity"] == 100
    assert result["trades"][1]["date"] == "2026-01-07"
    assert result["trades"][1]["quantity"] == 900


def test_unknown_simulator_option_is_not_silently_ignored():
    with pytest.raises(TypeError, match="unexpected keyword"):
        simulate([], {}, top_n=3)


@pytest.mark.parametrize(
    "params",
    [
        {"sell_fee": 0.8, "sell_tax": 0.3},
        {"annual_sessions": 0},
        {"risk_free_annual": -1},
        {"execution": "same_close"},
        {"slippage": float("nan")},
    ],
)
def test_effective_simulator_parameters_are_validated(params):
    with pytest.raises(ValueError):
        simulate([], {}, **params)


def test_annual_sessions_and_risk_free_affect_metrics():
    rows = market([{"FPT": 10_000}, {"FPT": 10_000}, {"FPT": 11_000}])
    result = simulate(
        rows, {"2026-01-05": ["FPT"]}, **frictionless(annual_sessions=12, risk_free_annual=0.05)
    )
    assert result["metrics"]["cagr"] == pytest.approx(1.1**4 - 1)
    assert result["metrics"]["annual_sessions"] == 12
    assert result["metrics"]["risk_free_annual"] == 0.05
    baseline = simulate(rows, {"2026-01-05": ["FPT"]}, **frictionless(annual_sessions=12))
    assert result["metrics"]["sharpe"] < baseline["metrics"]["sharpe"]


def test_missing_previous_session_volume_defers_sale_without_assuming_liquidity():
    rows = market([{"FPT": 10_000}] * 5)
    del rows[2]
    result = simulate(
        rows,
        {"2026-01-05": ["FPT"], "2026-01-06": []},
        calendar=[str(date(2026, 1, 5) + timedelta(days=i)) for i in range(5)],
        initial_cash=10_000_000,
    )
    assert result["trades"][1]["date"] == "2026-01-09"


def test_split_preserves_nav_and_dividend_is_receivable_before_payment():
    rows = market(
        [{"FPT": 10_000}, {"FPT": 10_000}, {"FPT": 5_000}, {"FPT": 4_500}, {"FPT": 4_500}]
    )
    actions = [
        dict(symbol="FPT", ex_date="2026-01-07", action_type="split", factor=2),
        dict(
            symbol="FPT",
            ex_date="2026-01-08",
            action_type="cash_dividend",
            cash_per_share_vnd=500,
            payable_date="2026-01-09",
        ),
    ]
    result = simulate(
        rows, {"2026-01-05": ["FPT"]}, corporate_actions=actions, price_limit=0.07, **frictionless()
    )
    assert all(row["equity"] == 10_000_000 for row in result["equity_curve"])
    assert result["equity_curve"][3]["available_cash"] == 0
    assert result["equity_curve"][4]["available_cash"] == 1_000_000


def test_buy_is_deferred_at_verified_upper_limit():
    rows = market([{"FPT": 10_000}, {"FPT": 10_700}, {"FPT": 10_700}])
    result = simulate(
        rows, {"2026-01-05": ["FPT"]}, price_limit=0.07, limit_tolerance=0.00001, **frictionless()
    )
    assert result["trades"][0]["date"] == "2026-01-07"


def _isolated_engine(tmp_path, monkeypatch):
    engine = database.initialize_database(tmp_path / "backtest.sqlite")
    monkeypatch.setattr(database, "initialize_database", lambda: engine)
    return engine


def test_unavailable_audit_is_persisted_reproducibly(tmp_path, monkeypatch):
    engine = _isolated_engine(tmp_path, monkeypatch)
    settings = load_settings()
    request = dict(start_date="2026-01-01", end_date="2026-02-01")
    first, second = run_backtest(request, settings), run_backtest(request, settings)
    assert first["status"] == "UNAVAILABLE"
    assert first["metrics"] is None and first["equity_curve"] == []
    assert first["config_hash"] == second["config_hash"]
    assert first["data_hash"] == second["data_hash"]
    assert first["backtest_run_id"] != second["backtest_run_id"]
    with Session(engine) as session:
        saved = session.get(BacktestRun, first["backtest_run_id"])
        assert saved.results["reasons"] == first["reasons"]
        assert saved.seed == settings.backtest["seed"]
        assert saved.config_snapshot["effective_backtest"]["annual_sessions"] == 252


def audit(day, tag):
    stamp = datetime.combine(day, datetime.min.time(), UTC)
    return dict(
        source="vnstock/VCI",
        source_url="https://example.invalid/synthetic-test",
        fetched_at=stamp,
        as_of_date=day,
        payload_sha256=tag.ljust(64, "0")[:64],
    )


def _verified_fixture(engine):
    """Only temporary test DB: verified flags here are test inputs, not real data claims."""
    with Session(engine) as session:
        session.add_all(
            [Stock(symbol="FPT", sector="technology"), Stock(symbol="MWG", sector="retail")]
        )
        session.flush()
        snapshot = UniverseSnapshot(
            index_name="VN30",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            announced_at=datetime(2024, 12, 20, tzinfo=UTC),
            coverage="full",
            verified=True,
            **audit(date(2025, 1, 1), "uni"),
        )
        session.add(snapshot)
        session.flush()
        session.add_all(
            [
                UniverseMember(snapshot_id=snapshot.id, symbol=s, sector=sector)
                for s, sector in [("FPT", "technology"), ("MWG", "retail")]
            ]
        )
        day = date(2025, 1, 1)
        while day <= date(2026, 6, 5):
            if day.weekday() < 5:
                session.add(
                    TradingSession(
                        exchange="HOSE",
                        session_date=day,
                        is_open=True,
                        **audit(day, f"calendar-{day}"),
                    )
                )
                for symbol in ("FPT", "MWG"):
                    session.add(
                        PriceBar(
                            symbol=symbol,
                            open=10_000,
                            high=10_100,
                            low=9_900,
                            close=10_000,
                            volume=1_000_000,
                            adjusted_close=10_000,
                            adjustment_verified=True,
                            price_unit="VND",
                            available_at=datetime.combine(day, datetime.min.time(), UTC),
                            suspended=False,
                            **audit(day, f"{symbol}-{day}"),
                        )
                    )
            day += timedelta(days=1)
        for symbol, roe in (("FPT", 0.3), ("MWG", 0.1)):
            for period_end in (
                date(2025, 6, 30),
                date(2025, 9, 30),
                date(2025, 12, 31),
                date(2026, 3, 31),
            ):
                published = datetime.combine(
                    period_end + timedelta(days=15), datetime.min.time(), UTC
                )
                session.add(
                    FundamentalValue(
                        symbol=symbol,
                        period_end=period_end,
                        period_type="quarter",
                        metric="ratio:ROE",
                        value=roe,
                        unit="ratio",
                        original_unit="ratio",
                        published_at=published,
                        available_at=published,
                        publication_inferred=False,
                        vintage_verified=True,
                        revision="original",
                        missing_reason=None,
                        **audit(period_end, f"fa-{symbol}-{period_end}"),
                    )
                )
                session.add(
                    FundamentalValue(
                        symbol=symbol,
                        period_end=period_end,
                        period_type="quarter",
                        metric="balance:Total Assets",
                        value=100_000_000,
                        unit="VND",
                        original_unit="VND",
                        published_at=published,
                        available_at=published,
                        publication_inferred=False,
                        vintage_verified=True,
                        revision="original",
                        missing_reason=None,
                        **audit(period_end, f"balance-{symbol}-{period_end}"),
                    )
                )
        revised = FundamentalValue(
            symbol="FPT",
            period_end=date(2026, 3, 31),
            period_type="quarter",
            metric="ratio:ROE",
            value=0,
            unit="ratio",
            original_unit="ratio",
            published_at=datetime(2026, 5, 5, tzinfo=UTC),
            available_at=datetime(2026, 5, 5, tzinfo=UTC),
            publication_inferred=False,
            vintage_verified=True,
            revision="later_revision",
            missing_reason=None,
            **audit(date(2026, 3, 31), "revised-after-initial-signal"),
        )
        session.add(revised)
        session.commit()
        return revised.id


def test_verified_replay_executes_and_future_revision_cannot_change_initial_signal(
    tmp_path, monkeypatch
):
    engine = _isolated_engine(tmp_path, monkeypatch)
    revision_id = _verified_fixture(engine)
    settings = load_settings().model_copy(deep=True)
    for sector in ("technology", "retail"):
        settings.sector_metrics["sectors"][sector] = {
            "roe": dict(weight=1, lower=0, upper=0.4, direction="higher", unit="ratio")
        }
    settings.backtest.update(
        top_n=1, annual_sessions=240, risk_free_annual=0.03, random_baseline_runs=3
    )
    request = dict(start_date="2026-05-04", end_date="2026-06-05", symbols=["FPT", "MWG"])
    result = run_backtest(request, settings)
    assert result["status"] == "COMPLETE", result["reasons"]
    first = result["signal_replay"][0]
    assert first["ranking"][0]["symbol"] == "FPT"
    assert revision_id not in first["ranking"][0]["fundamental_ids"]
    later = result["signal_replay"][1]
    assert later["ranking"][0]["symbol"] == "MWG"
    assert result["trades"][0]["date"] == "2026-05-05"
    assert result["metrics"]["annual_sessions"] == 240
    assert math.isfinite(result["metrics"]["total_return"])
    repeat = run_backtest(request, settings)
    assert result["data_hash"] == repeat["data_hash"]
    assert result["benchmarks"]["random_top_n"] == repeat["benchmarks"]["random_top_n"]
    with Session(engine) as session:
        assert session.get(BacktestRun, result["backtest_run_id"]).results["status"] == "COMPLETE"


def test_unknown_backtest_parameter_is_rejected_before_persistence():
    with pytest.raises(ValueError, match="Unsupported"):
        run_backtest(
            dict(start_date="2026-01-01", end_date="2026-02-01", typo_fee=0), load_settings()
        )


def test_null_revision_cannot_resurrect_an_older_financial_value(tmp_path, monkeypatch):
    from sqlalchemy import select

    from backend.app.backtest.engine import _point_in_time_score

    engine = _isolated_engine(tmp_path, monkeypatch)
    revision_id = _verified_fixture(engine)
    settings = load_settings().model_copy(deep=True)
    settings.sector_metrics["sectors"]["technology"] = {
        "roe": dict(weight=1, lower=0, upper=0.4, direction="higher", unit="ratio")
    }
    with Session(engine) as session:
        revised = session.get(FundamentalValue, revision_id)
        revised.value = None
        revised.missing_reason = "SOURCE_VALUE_MISSING"
        session.commit()
        bars = session.scalars(select(PriceBar)).all()
        values = session.scalars(select(FundamentalValue)).all()
        initial, reason = _point_in_time_score(
            "FPT",
            "technology",
            date(2026, 5, 4),
            bars,
            values,
            [],
            settings,
            settings.backtest["modes"]["S_ex_news"],
        )
        assert initial is not None and reason is None
        after_revision, reason = _point_in_time_score(
            "FPT",
            "technology",
            date(2026, 5, 29),
            bars,
            values,
            [],
            settings,
            settings.backtest["modes"]["S_ex_news"],
        )
        assert after_revision is None
        assert "FA" in reason
