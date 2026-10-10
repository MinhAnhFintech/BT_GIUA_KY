"""Synthetic SDK contract fixtures only; never authenticate or call live SDK in CI."""

import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.core.config import load_settings
from scripts.data_source_check import sdk_probe


def test_market_equity_is_called_before_ohlcv() -> None:
    """Regression: vnstock 4.0.9 equity is a method, not a property."""
    frame = pd.DataFrame(
        {
            "time": ["2026-10-08"],
            "open": [100],
            "high": [102],
            "low": [99],
            "close": [101],
            "volume": [1000],
        }
    )
    market = Mock()
    market.equity.return_value.ohlcv.return_value = frame
    stub = SimpleNamespace(Market=Mock(return_value=market), Fundamental=Mock(), Reference=Mock())
    with patch.dict(sys.modules, {"vnstock": stub}):
        result = sdk_probe("prices", date(2026, 10, 9), load_settings().sources)
    assert result.status == "OK"
    market.equity.assert_called_once_with("FPT")
    market.equity.return_value.ohlcv.assert_called_once_with(
        start="2026-09-25",
        end="2026-10-09",
        count=15,
        source=load_settings().sources["provider_source"],
    )
    assert "COMPLETED_SESSION_NOT_VERIFIED" in result.warnings


def test_default_financial_schema_without_unit_is_recognized_but_flagged() -> None:
    """Recognize transport schema without asserting financial monetary units."""
    frame = pd.DataFrame({"item": ["TEST_ONLY"], "item_id": ["assets"], "2026-Q2": [100]})
    frame.attrs["periods"] = ["2026-Q2"]
    financial = Mock()
    financial.equity.return_value.balance_sheet.return_value = frame
    stub = SimpleNamespace(
        Fundamental=Mock(return_value=financial), Market=Mock(), Reference=Mock()
    )
    with patch.dict(sys.modules, {"vnstock": stub}):
        result = sdk_probe("financials", date(2026, 10, 9), load_settings().sources)
    assert result.status == "OK"
    assert "FINANCIAL_MONETARY_UNITS_NOT_VERIFIED" in result.warnings
    assert "PUBLICATION_DATES_NOT_VERIFIED" in result.warnings
    assert result.latest_data_date is None


def test_sdk_exception_does_not_expose_secrets() -> None:
    market = Mock()
    market.equity.side_effect = RuntimeError("SYNTHETIC_SECRET_API_KEY_SHOULD_NOT_LEAK")
    stub = SimpleNamespace(Market=Mock(return_value=market), Fundamental=Mock(), Reference=Mock())
    with patch.dict(sys.modules, {"vnstock": stub}):
        result = sdk_probe("prices", date(2026, 10, 9), load_settings().sources)
    assert result.status == "FAIL"
    assert result.reason == "RuntimeError"
    assert "SECRET_API_KEY" not in result.model_dump_json()
