"""Research configuration regression tests; no market data involved."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.core.config import MetricRule, Settings, UniverseConfig, load_settings


def test_standard_formula_and_independent_backtest_mode() -> None:
    """The reduced mode is explicit and cannot silently replace the standard formula."""
    settings = load_settings()
    assert settings.scoring["weights"] == {"FA": 0.45, "TA": 0.35, "NEWS": 0.20}
    assert settings.backtest["modes"]["S_ex_news"] == {"FA": 0.5625, "TA": 0.4375}
    assert settings.scoring["missing_policy"] == "exclude_without_reweighting"


def test_configuration_hash_is_stable() -> None:
    assert load_settings().config_hash == load_settings().config_hash
    assert len(load_settings().config_hash) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"weights": {"FA": 0.5, "TA": 0.3, "NEWS": 0.2}},
        {"weights": {"FA": 0.45, "TA": 0.35, "NEWS": 0.30}},
        {"missing_policy": "redistribute"},
        {"version": ""},
        {"score_range": [0, 1]},
    ],
)
def test_invalid_scoring_rejected(change: dict) -> None:
    document = deepcopy(load_settings().model_dump())
    document["scoring"].update(change)
    with pytest.raises((ValidationError, ValueError)):
        Settings.model_validate(document)


def test_duplicate_symbol_rejected() -> None:
    document = load_settings().universe.model_dump()
    document["selected"][1] = document["selected"][0]
    with pytest.raises(ValidationError, match="Duplicate"):
        UniverseConfig.model_validate(document)


def test_too_few_symbols_rejected() -> None:
    document = load_settings().universe.model_dump()
    document["selected"] = document["selected"][:4]
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(document)


@pytest.mark.parametrize("lower,upper", [(1, 1), (2, 1)])
def test_invalid_normalization_range(lower: float, upper: float) -> None:
    with pytest.raises(ValidationError):
        MetricRule(weight=0.5, lower=lower, upper=upper, direction="higher")


@pytest.mark.parametrize("field,value", [("lower", float("nan")), ("weight", float("inf"))])
def test_non_finite_thresholds_rejected(field: str, value: float) -> None:
    rule = {"weight": 0.5, "lower": 0, "upper": 1, "direction": "higher"}
    rule[field] = value
    with pytest.raises(ValidationError):
        MetricRule.model_validate(rule)


def test_unknown_sector_rejected() -> None:
    document = deepcopy(load_settings().model_dump())
    document["universe"]["selected"][0]["sector"] = "undefined_sector"
    with pytest.raises(ValidationError, match="Missing sector"):
        Settings.model_validate(document)


@pytest.mark.parametrize("field,value", [("buy_fee", -0.1), ("sell_tax", 1.5), ("top_n", 31)])
def test_invalid_backtest_parameters_rejected(field: str, value: float) -> None:
    document = deepcopy(load_settings().model_dump())
    document["backtest"][field] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(document)


@pytest.mark.parametrize(
    "change",
    [
        {"sell_fee": 0.7, "sell_tax": 0.4},
        {"annual_sessions": 0},
        {"risk_free_annual": -1},
        {"max_volume_participation": 0},
        {"initial_cash_vnd": float("inf")},
        {"rebalance": "daily"},
        {"execution": "same_day_close"},
        {"out_of_sample_fraction": 1},
    ],
)
def test_invalid_execution_assumptions_rejected(change: dict) -> None:
    document = deepcopy(load_settings().model_dump())
    document["backtest"].update(change)
    with pytest.raises(ValidationError):
        Settings.model_validate(document)
