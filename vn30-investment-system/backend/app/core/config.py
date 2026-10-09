"""Load versioned YAML and reject inconsistent research assumptions."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_NAMES = ("universe", "scoring", "sector_metrics", "data_requirements", "sources", "backtest")


class MetricRule(BaseModel):
    """An explicit linear normalization rule; missing inputs remain unavailable."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    weight: float = Field(gt=0, le=1)
    lower: float
    upper: float
    direction: Literal["higher", "lower"]
    unit: str | None = None

    @model_validator(mode="after")
    def ordered_bounds(self) -> MetricRule:
        """Reject inverted or constant normalization ranges."""
        if self.lower >= self.upper:
            raise ValueError("Metric lower must be smaller than upper")
        return self


class SelectedStock(BaseModel):
    """Candidate symbol, not evidence of VN30 membership."""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9]{2,4}$")
    sector: str


class UniverseConfig(BaseModel):
    """Universe constraints validated before any network request."""

    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1)
    index: Literal["VN30"]
    timezone: str
    min_symbols: int = Field(ge=5, le=10)
    max_symbols: int = Field(ge=5, le=10)
    historical_membership_policy: Literal["require_dated_snapshot"]
    selected: list[SelectedStock]

    @model_validator(mode="after")
    def valid_selection(self) -> UniverseConfig:
        """Selection size and uniqueness do not imply membership validation."""
        if not self.min_symbols <= len(self.selected) <= self.max_symbols:
            raise ValueError("Selection must satisfy configured min/max_symbols")
        if len({stock.symbol for stock in self.selected}) != len(self.selected):
            raise ValueError("Duplicate selected symbol")
        return self


def validate_weights(weights: dict[str, float], label: str) -> None:
    """Require finite positive weights adding to one, without renormalizing."""
    if not weights or any(not math.isfinite(w) or w <= 0 or w > 1 for w in weights.values()):
        raise ValueError(f"{label}: weights must be finite and in (0, 1]")
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"{label}: weights must sum to 1")


class Settings(BaseModel):
    """Validated bundle; hash identifies all six configuration files at load time."""

    universe: UniverseConfig
    scoring: dict[str, Any]
    sector_metrics: dict[str, Any]
    data_requirements: dict[str, Any]
    sources: dict[str, Any]
    backtest: dict[str, Any]
    config_hash: str

    @model_validator(mode="after")
    def validate_consistency(self) -> Settings:
        """Protect the original scoring formula and strict missing-data policy."""
        for name in CONFIG_NAMES:
            section = getattr(self, name)
            version = section.version if name == "universe" else section.get("version")
            if not isinstance(version, str) or not version.strip():
                raise ValueError(f"{name}: version required")
        weights = self.scoring["weights"]
        validate_weights(weights, "scoring")
        if weights != {"FA": 0.45, "TA": 0.35, "NEWS": 0.20}:
            raise ValueError("Standard scoring formula must remain 45/35/20")
        if self.scoring["score_range"] != [0, 100]:
            raise ValueError("Score range must be 0–100")
        if self.scoring["missing_policy"] != "exclude_without_reweighting":
            raise ValueError("Missing data must not become zero or redistribute weights")
        for label, metrics in {
            "TA": self.scoring["ta"]["metrics"],
            **self.sector_metrics["sectors"],
        }.items():
            rules = {name: MetricRule.model_validate(rule) for name, rule in metrics.items()}
            validate_weights({name: rule.weight for name, rule in rules.items()}, label)
        for stock in self.universe.selected:
            if stock.sector not in self.sector_metrics["sectors"]:
                raise ValueError(f"Missing sector rules: {stock.sector}")
        requirements = self.data_requirements
        for key in (
            "min_price_sessions",
            "min_quarters",
            "min_news",
            "news_window_days",
            "quarter_publication_lag_days",
            "annual_publication_lag_days",
        ):
            if not isinstance(requirements[key], int) or requirements[key] <= 0:
                raise ValueError(f"{key}: positive integer required")
        for label, mode_weights in self.backtest["modes"].items():
            validate_weights(mode_weights, label)
        if self.backtest["modes"]["S_full"] != weights:
            raise ValueError("S_full must match the original formula")
        if set(self.backtest["modes"]["S_ex_news"]) != {"FA", "TA"}:
            raise ValueError("S_ex_news must contain FA and TA only")
        if self.backtest["default_mode"] not in self.backtest["modes"]:
            raise ValueError("Unknown default backtest mode")
        if not 1 <= self.backtest["top_n"] <= len(self.universe.selected):
            raise ValueError("Invalid top_n")
        for key in ("buy_fee", "sell_fee", "sell_tax", "slippage"):
            value = self.backtest[key]
            if not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{key}: finite fraction in [0, 1) required")
        if self.backtest["lot_size"] <= 0 or self.backtest["settlement_sessions"] < 0:
            raise ValueError("Invalid lot size or settlement period")
        return self


def load_settings(config_dir: Path | None = None) -> Settings:
    """Read YAML safely; stable hash changes whenever an effective parameter changes."""
    folder = config_dir or PROJECT_ROOT / "config"
    documents: dict[str, Any] = {}
    for name in CONFIG_NAMES:
        path = folder / f"{name}.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError(f"{path.name}: expected a YAML mapping")
        documents[name] = document
    canonical = json.dumps(documents, ensure_ascii=False, sort_keys=True, allow_nan=False)
    config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Settings(**documents, config_hash=config_hash)
