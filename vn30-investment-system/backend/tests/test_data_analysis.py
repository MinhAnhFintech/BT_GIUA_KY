from datetime import date

import pandas as pd

from backend.app.analysis.service import analyze_cached
from backend.app.analysis.ta import compute_rsi, score_ta
from backend.app.core.config import load_settings


def test_monotonic_rsi_is_100_and_flat_is_50():
    assert compute_rsi(pd.Series(range(40))).iloc[-1] == 100
    assert compute_rsi(pd.Series([10] * 40)).iloc[-1] == 50


def test_missing_ta_metric_never_becomes_zero():
    frame = pd.DataFrame(
        {
            "close": [100 + i * 0.1 for i in range(210)],
            "high": [101 + i * 0.1 for i in range(210)],
            "low": [99 + i * 0.1 for i in range(210)],
            "volume": [0] * 210,
        }
    )
    result = score_ta(frame, load_settings().scoring)
    assert result.score is None
    assert result.status == "PARTIAL_ANALYSIS"


def test_empty_cache_is_explicit(monkeypatch):
    import backend.app.analysis.service as service

    monkeypatch.setattr(service, "get_prices", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(service, "get_fundamentals", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(service, "get_news", lambda *a, **k: pd.DataFrame())
    result = analyze_cached(
        [{"symbol": "FPT", "sector": "technology"}], date(2026, 10, 9), load_settings()
    )
    assert result["main_ranking"] == []
    assert result["stocks"][0]["total_score"] is None
    assert result["stocks"][0]["prices"] == []


def test_cached_vintages_do_not_leak_into_past(tmp_path, monkeypatch):
    from datetime import UTC, date, datetime

    from backend.app.data import store
    from backend.app.data.contracts import Provenance, ProviderBatch
    from backend.app.db.session import initialize_database

    monkeypatch.setattr(store, "engine", initialize_database(tmp_path / "cache.sqlite3"))
    fetched = datetime(2026, 10, 9, 3, tzinfo=UTC)
    provenance = Provenance(
        "test", "https://example.com/data", fetched, date(2026, 10, 9), "a" * 64
    )
    batch = ProviderBatch(
        [{"time": "2026-10-08", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}],
        provenance,
    )
    store.save_prices("FPT", batch)
    assert store.get_prices(
        "FPT", date(2026, 10, 1), date(2026, 10, 9), known_at=datetime(2026, 10, 8, 23, tzinfo=UTC)
    ).empty
    assert len(store.get_prices("FPT", date(2026, 10, 1), date(2026, 10, 9), known_at=fetched)) == 1
    store.save_prices("FPT", batch)
    assert len(store.get_prices("FPT", date(2026, 10, 1), date(2026, 10, 9), known_at=fetched)) == 1


def test_price_validation_threshold_is_configured():
    from backend.app.data.validator import validate_prices

    frame = pd.DataFrame(
        [
            {"time": "2026-10-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-10-02", "open": 110, "high": 111, "low": 109, "close": 110, "volume": 1},
        ]
    )
    settings = load_settings()
    assert any(i.code == "PRICE_JUMP_REVIEW" for i in validate_prices(frame, "FPT", settings))
    settings.data_requirements["quality"]["hose_daily_limit"] = 0.15
    assert not any(i.code == "PRICE_JUMP_REVIEW" for i in validate_prices(frame, "FPT", settings))


def test_refresh_persists_quality_and_continues_statement_failures(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.app.data import store
    from backend.app.data.contracts import Provenance, ProviderBatch
    from backend.app.data.updater import DataUpdater
    from backend.app.db.models import DataQualityIssue, FundamentalValue
    from backend.app.db.session import initialize_database

    monkeypatch.setattr(store, "engine", initialize_database(tmp_path / "refresh.sqlite3"))
    now = datetime(2026, 10, 9, 3, tzinfo=UTC)
    provenance = Provenance("test", "https://example.com/data", now, now.date(), "a" * 64)
    prices = ProviderBatch(
        [{"time": "2026-10-08", "open": 0, "high": 1, "low": 0, "close": 1, "volume": 1}],
        provenance,
    )

    def fail(*args):
        raise ValueError("SECRET_MUST_NOT_LEAK")

    def financial(symbol, period):
        return pd.DataFrame(
            [
                {
                    "item": "Doanh thu thuần",
                    "item_en": "Revenue",
                    ("2026-Q2" if period == "quarter" else "2025"): 100,
                }
            ]
        )

    updater = DataUpdater()
    updater.price_provider = SimpleNamespace(prices=lambda *a: prices)
    updater.news_provider = SimpleNamespace(news=fail)
    updater.fundamentals_provider = SimpleNamespace(
        source="VCI",
        income_statement=financial,
        balance_sheet=financial,
        cash_flow=financial,
        ratio=fail,
    )
    result = updater.refresh_all(["FPT"], date(2026, 10, 9))
    assert "SECRET_MUST_NOT_LEAK" not in str(result)
    assert result["symbols"][0]["stages"]["fundamentals"] == "PARTIAL_SOURCE_FAILURE"
    assert result["symbols"][0]["timing"]["prices"] >= 0
    with Session(store.engine) as session:
        assert (
            session.scalar(
                select(DataQualityIssue).where(DataQualityIssue.code == "PRICE_NONPOSITIVE")
            )
            is not None
        )
        assert (
            session.scalar(select(FundamentalValue).where(FundamentalValue.period_type == "year"))
            is not None
        )


def test_yoy_requires_matching_quarter_and_ignores_annual_columns():
    from backend.app.analysis.fa import extract_metric_from_financials

    frame = pd.DataFrame(
        [
            {
                "item": "Doanh thu thuần",
                "2026-Q2": 120,
                "2025-Q4": 80,
                "2025-Q3": 90,
                "2025": 1000,
                "2025-Q2": 100,
                "2025-Q1": 10,
            }
        ]
    )
    args = (frame, None, None, None, "revenue_yoy", "technology")
    assert extract_metric_from_financials(*args)[0] == 0.2
    frame.drop(columns="2025-Q2", inplace=True)
    assert extract_metric_from_financials(*args)[0] is None


def test_cfo_uses_exact_cash_flow_line_and_matched_period():
    from backend.app.analysis.fa import extract_metric_from_financials

    income = pd.DataFrame([{"item": "Lợi nhuận sau thuế", "unit": "VND", "2026-Q2": 100}])
    cashflow = pd.DataFrame(
        [
            {
                "item": "Lợi nhuận kinh doanh trước thay đổi vốn lưu động",
                "unit": "VND",
                "2026-Q2": 900,
            },
            {"item": "Lưu chuyển tiền thuần từ hoạt động kinh doanh", "unit": "VND", "2026-Q2": 80},
        ]
    )
    args = (income, None, cashflow, None, "cfo_profit", "technology")
    assert extract_metric_from_financials(*args)[0] == 0.8
    cashflow.rename(columns={"2026-Q2": "2026-Q1"}, inplace=True)
    assert extract_metric_from_financials(*args)[0] is None
    cashflow.rename(columns={"2026-Q1": "2026-Q2"}, inplace=True)
    income.loc[0, "2026-Q2"] = -100
    assert extract_metric_from_financials(*args)[0] is None


def test_debt_ebitda_rejects_liability_profit_proxy_and_uses_ttm():
    from backend.app.analysis.fa import extract_metric_from_financials

    income = pd.DataFrame([{"item": "Lợi nhuận trước thuế", "unit": "VND", "2026-Q2": 100}])
    balance = pd.DataFrame([{"item": "Tổng nợ phải trả", "unit": "VND", "2026-Q2": 400}])
    assert (
        extract_metric_from_financials(income, balance, None, None, "debt_ebitda", "steel")[0]
        is None
    )
    income = pd.DataFrame(
        [
            {
                "item": "EBITDA",
                "unit": "VND",
                "2026-Q2": 10,
                "2026-Q1": 20,
                "2025-Q4": 30,
                "2025-Q3": 40,
            }
        ]
    )
    balance = pd.DataFrame(
        [
            {"item": "Short-term Borrowings", "unit": "VND", "2026-Q2": 120},
            {"item": "Long-term Borrowings", "unit": "VND", "2026-Q2": 80},
        ]
    )
    assert (
        extract_metric_from_financials(income, balance, None, None, "debt_ebitda", "steel")[0] == 2
    )


def test_ratio_units_are_explicit_and_never_guessed_from_magnitude():
    from backend.app.analysis.fa import extract_metric_from_financials

    frame = pd.DataFrame([{"item": "ROE", "unit": "ratio", "2026-Q2": 1.2}])
    args = (None, None, None, frame, "roe", "technology")
    assert extract_metric_from_financials(*args)[0] == 1.2
    frame.loc[0, "unit"] = "percent"
    assert extract_metric_from_financials(*args)[0] == 0.012
    frame.loc[0, "unit"] = "SOURCE_NATIVE_UNVERIFIED"
    assert extract_metric_from_financials(*args)[0] is None
    frame.loc[0, "item"] = "ROE (%)"
    frame.loc[0, "unit"] = "ratio"
    assert extract_metric_from_financials(*args)[0] == 1.2


def test_price_source_filter_and_news_association_are_point_in_time(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from backend.app.data import store
    from backend.app.data.contracts import Provenance, ProviderBatch
    from backend.app.db.session import initialize_database

    monkeypatch.setattr(store, "engine", initialize_database(tmp_path / "sources.sqlite3"))
    first = datetime(2026, 10, 8, 9, tzinfo=UTC)
    later = first + timedelta(days=1)

    def batch(source, when, close):
        return ProviderBatch(
            [
                {
                    "time": "2026-10-08",
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000,
                }
            ],
            Provenance(
                "vnstock/" + source,
                "https://example.com/" + source,
                when,
                when.date(),
                ("a" if source == "VCI" else "b") * 64,
            ),
        )

    store.save_prices("FPT", batch("VCI", first, 100))
    store.save_prices("FPT", batch("KBS", later, 200))
    prices = store.get_prices("FPT", first.date(), later.date(), source="VCI")
    assert prices.close.tolist() == [100]
    assert prices.price_unit.tolist() == ["SOURCE_NATIVE_UNVERIFIED"]
    item = {
        "title": "FPT và SSI tăng trưởng vượt kế hoạch",
        "url": "https://example.com/news",
        "published_at": first.isoformat(),
    }
    first_batch = ProviderBatch([item], batch("VCI", first, 100).provenance)
    later_batch = ProviderBatch([item], batch("VCI", later, 100).provenance)
    store.save_news(first_batch, "FPT")
    store.save_news(later_batch, "SSI")
    assert not store.get_news(["FPT"], 30, known_at=first, source="VCI").empty
    assert store.get_news(["SSI"], 30, known_at=first, source="VCI").empty
    assert len(store.get_news(["SSI"], 30, known_at=later, source="VCI")) == 1


def test_valid_news_count_excludes_low_confidence_and_duplicates():
    from datetime import UTC, datetime

    from backend.app.analysis.news import score_news

    stamp = datetime(2026, 10, 9, 3, tzinfo=UTC)
    title = "FPT tăng trưởng vượt kế hoạch"
    rows = pd.DataFrame(
        [
            {"title": title, "published_at": stamp},
            {"title": title, "published_at": stamp},
            {"title": "Lịch nghỉ của thị trường", "published_at": stamp},
        ]
    )
    result = score_news(rows, load_settings().scoring, stamp)
    assert result.breakdown["items_after_dedup"] == 2
    assert result.breakdown["items_eligible"] == 1
    assert result.breakdown["items_scored"] == 1


def test_refresh_rechecks_last_session_and_caches_financials(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from backend.app.data import store
    from backend.app.data.contracts import Provenance, ProviderBatch
    from backend.app.data.updater import DataUpdater
    from backend.app.db.session import initialize_database

    monkeypatch.setattr(store, "engine", initialize_database(tmp_path / "lastday.sqlite3"))
    now = datetime.now(UTC)
    as_of = now.date()
    prices = ProviderBatch(
        [
            {
                "time": as_of.isoformat(),
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 100,
                "volume": 1000,
            }
        ],
        Provenance("vnstock/VCI", "https://example.com/data", now, as_of, "a" * 64),
    )
    store.save_prices("FPT", prices)
    calls = []

    def price_fetch(symbol, start, end):
        calls.append(start)
        return prices

    def financial(symbol, period):
        calls.append(period)
        return pd.DataFrame(
            [{"item": "Doanh thu thuần", ("2026-Q2" if period == "quarter" else "2025"): 100}]
        )

    updater = DataUpdater()
    updater.price_provider = SimpleNamespace(source="VCI", prices=price_fetch)
    updater.news_provider = SimpleNamespace(news=lambda *a: ProviderBatch([], prices.provenance))
    updater.fundamentals_provider = SimpleNamespace(
        source="VCI",
        income_statement=financial,
        balance_sheet=financial,
        cash_flow=financial,
        ratio=financial,
    )
    updater.refresh_all(["FPT"], as_of)
    assert calls[0] == as_of
    assert calls.count("quarter") == 4
    second = updater.refresh_all(["FPT"], as_of)
    assert calls.count("quarter") == 4
    assert second["symbols"][0]["details"]["fundamentals_quarter_income"]["cached"] is True


def test_vci_selects_latest_correct_periods_without_filling_nulls():
    from backend.app.data.providers import _select_vci_periods

    raw = pd.DataFrame(
        [
            {"year": 2018, "quarter": 1, "roe": 0.1},
            {"year": 2025, "quarter": 5, "roe": 0.2},
            {"year": 2026, "quarter": 1, "roe": 0.3},
            {"year": 2026, "quarter": 2, "roe": None},
            {"year": 2024, "quarter": 5, "roe": 0.4},
        ]
    )
    quarterly = _select_vci_periods(raw, "quarter", 2)
    assert quarterly.quarter.tolist() == [2, 1]
    assert pd.isna(quarterly.roe.iloc[0])
    annual = _select_vci_periods(raw, "year", 2)
    assert annual.year.tolist() == [2025, 2024]
    assert annual.quarter.tolist() == [5, 5]


def test_provider_filters_sdk_prices_outside_requested_range(monkeypatch):
    import sys
    from types import SimpleNamespace

    from backend.app.data.providers import VnstockPriceProvider

    frame = pd.DataFrame(
        [
            {"time": "2026-10-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"time": "2026-10-08", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"time": "2026-10-09", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "vnstock",
        SimpleNamespace(
            Market=lambda: SimpleNamespace(
                equity=lambda *a: SimpleNamespace(ohlcv=lambda **k: frame)
            )
        ),
    )
    provider = VnstockPriceProvider("VCI")
    monkeypatch.setattr(provider, "wait", lambda: None)
    result = provider.prices("FPT", date(2026, 10, 8), date(2026, 10, 8))
    assert len(result.records) == 1
    assert result.records[0]["time"] == "2026-10-08"


def test_analysis_forwards_configured_source_to_every_cached_input(monkeypatch):
    import backend.app.analysis.service as service

    sources = []

    def empty(*args, **kwargs):
        sources.append(kwargs["source"])
        return pd.DataFrame()

    for method in ("get_prices", "get_fundamentals", "get_news"):
        monkeypatch.setattr(service, method, empty)
    settings = load_settings()
    result = service.analyze_cached(
        [{"symbol": "FPT", "sector": "technology"}], date(2026, 10, 8), settings
    )
    assert sources == [settings.sources["provider_source"]] * 3
    assert result["stocks"][0]["provenance"]["source"] == "vnstock/VCI"
