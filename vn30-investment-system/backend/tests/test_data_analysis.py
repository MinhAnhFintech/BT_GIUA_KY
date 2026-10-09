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
