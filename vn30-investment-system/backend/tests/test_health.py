"""Explicit synthetic provider fixtures; no real news or prices are fabricated for UI."""

from datetime import UTC, date, datetime
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from backend.app.core.config import load_settings
from backend.app.data.contracts import Provenance
from backend.app.data.health import inspect_frame, probe_rss

AS_OF = date(2026, 10, 9)


def synthetic_prices() -> pd.DataFrame:
    """A single deterministic OHLCV fixture used exclusively in tests."""
    return pd.DataFrame(
        {
            "time": ["2026-10-08"],
            "open": [100],
            "high": [102],
            "low": [99],
            "close": [101],
            "volume": [1000],
        }
    )


def test_real_schema_does_not_imply_backtest_ready() -> None:
    result = inspect_frame(synthetic_prices(), "prices", AS_OF)
    assert result["schema_valid"]
    assert result["freshness_days"] == 1
    assert "ADJUSTMENT_NOT_VERIFIED" in result["warnings"]
    assert "PRICE_UNIT_NOT_VERIFIED" in result["warnings"]


def test_future_price_rejected() -> None:
    frame = synthetic_prices()
    frame["time"] = ["2026-10-10"]
    with pytest.raises(ValueError, match="FUTURE_PRICE"):
        inspect_frame(frame, "prices", AS_OF)


@pytest.mark.parametrize("column,value", [("close", -1), ("volume", -10), ("high", 50)])
def test_invalid_ohlcv_rejected(column: str, value: float) -> None:
    frame = synthetic_prices()
    frame[column] = value
    with pytest.raises(ValueError):
        inspect_frame(frame, "prices", AS_OF)


def test_empty_source_rejected() -> None:
    with pytest.raises(ValueError, match="EMPTY"):
        inspect_frame(pd.DataFrame(), "prices", AS_OF)


def test_universe_without_symbol_field_rejected() -> None:
    with pytest.raises(ValueError, match="MISSING_SYMBOL"):
        inspect_frame(pd.DataFrame({"unknown": ["TEST"]}), "universe", AS_OF)


@patch("backend.app.data.health.requests.get")
def test_robots_disallow_prevents_feed_request(get: Mock) -> None:
    settings = load_settings().sources
    get.return_value = Mock(text="User-agent: *\nDisallow: /rss/", status_code=200)
    result = probe_rss(settings["rss"][0], settings, AS_OF)
    assert result.status == "BLOCKED"
    assert get.call_count == 1


@patch("backend.app.data.health.requests.get")
def test_robots_failure_does_not_fetch_feed(get: Mock) -> None:
    settings = load_settings().sources
    get.side_effect = requests.ConnectionError("SYNTHETIC_TEST_ONLY")
    result = probe_rss(settings["rss"][0], settings, AS_OF)
    assert result.status == "FAIL"
    assert get.call_count == 1


def test_provenance_rejects_naive_dates_and_invalid_hash() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Provenance("TEST_ONLY", "https://example.invalid", datetime(2026, 10, 9), AS_OF, "0" * 64)
    with pytest.raises(ValueError, match="SHA256"):
        Provenance(
            "TEST_ONLY",
            "https://example.invalid",
            datetime(2026, 10, 9, tzinfo=UTC),
            AS_OF,
            "x" * 64,
        )
