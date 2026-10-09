"""Fundamental Analysis scoring engine with sector-specific metrics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import MetricRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FAResult:
    """FA score with full breakdown for transparency."""

    score: float | None
    status: str  # COMPLETE, PARTIAL_ANALYSIS, INSUFFICIENT_DATA
    reasons: list[str]
    breakdown: dict[str, Any]


def extract_metric_from_financials(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    ratio: pd.DataFrame | None,
    metric_name: str,
    sector: str,
) -> tuple[float | None, str | None]:
    """Extract a specific FA metric value from financial statements.

    Returns:
        Tuple of (value, reason_if_missing).
    """
    try:
        if metric_name == "revenue_yoy":
            return _compute_yoy(income, "Doanh thu thuần", "revenue")
        elif metric_name == "profit_yoy":
            return _compute_yoy(income, "Lợi nhuận sau thuế", "profit")
        elif metric_name == "roe":
            return _extract_ratio(ratio, "ROE")
        elif metric_name == "roa":
            return _extract_ratio(ratio, "ROA")
        elif metric_name == "net_margin":
            return _compute_margin(income)
        elif metric_name == "gross_margin":
            return _compute_gross_margin(income)
        elif metric_name == "pe_relative_median":
            return _compute_pe_relative(ratio)
        elif metric_name == "inventory_turnover":
            return _compute_inventory_turnover(income, balance)
        elif metric_name == "cfo_profit":
            return _compute_cfo_profit(cashflow, income)
        elif metric_name == "cfo_capex":
            return _compute_cfo_capex(cashflow)
        elif metric_name == "debt_ebitda":
            return _compute_debt_ebitda(balance, income)
        # Banking specific
        elif metric_name == "nim":
            return _extract_ratio(ratio, "NIM")
        elif metric_name == "npl":
            return _extract_ratio(ratio, "NPL")
        elif metric_name == "npl_coverage":
            return _extract_ratio(ratio, "NPL Coverage")
        elif metric_name == "cir":
            return _extract_ratio(ratio, "CIR")
        elif metric_name == "casa":
            return _extract_ratio(ratio, "CASA")
        # Securities specific
        elif metric_name == "brokerage_revenue_yoy":
            return _compute_yoy(income, "Doanh thu môi giới", "brokerage_revenue")
        elif metric_name == "leverage":
            return _compute_leverage(balance)
        elif metric_name == "margin_equity":
            return _compute_margin_equity(balance)
        elif metric_name == "fvtpl_profit_yoy":
            return _compute_yoy(income, "FVTPL", "fvtpl_profit")
        else:
            return None, f"Unknown metric: {metric_name}"
    except Exception as e:
        logger.warning("Failed to extract %s for %s: %s", metric_name, sector, e)
        return None, f"Extraction error: {e}"


def _get_period_columns(df: pd.DataFrame) -> list[str]:
    """Get period columns (like 2024-Q1, 2024-Q2) from DataFrame."""
    return [
        c for c in df.columns if "-Q" in str(c) or (str(c).startswith("20") and len(str(c)) == 4)
    ]


def _find_row(df: pd.DataFrame, keyword: str) -> pd.Series | None:
    """Find a row by keyword in item or item_en columns."""
    if df is None or df.empty:
        return None
    for col_name in ["item", "item_en"]:
        if col_name in df.columns:
            mask = df[col_name].astype(str).str.contains(keyword, case=False, na=False)
            if mask.any():
                return df[mask].iloc[0]
    return None


def _compute_yoy(
    df: pd.DataFrame | None, keyword: str, label: str
) -> tuple[float | None, str | None]:
    """Compute year-over-year growth from quarterly data."""
    if df is None or df.empty:
        return None, f"No data for {label} YoY"
    row = _find_row(df, keyword)
    if row is None:
        return None, f"Row '{keyword}' not found"
    periods = _get_period_columns(df)
    if len(periods) < 5:  # Need at least current + same quarter last year
        return None, f"Need ≥5 quarters for YoY, got {len(periods)}"
    try:
        current = float(row[periods[0]])
        prev_year = float(row[periods[4]])  # Same quarter, previous year
        if prev_year == 0 or not np.isfinite(prev_year):
            return None, f"Previous year {label} is zero/invalid"
        return (current - prev_year) / abs(prev_year), None
    except (ValueError, KeyError, IndexError):
        return None, f"Could not compute {label} YoY"


def _extract_ratio(ratio: pd.DataFrame | None, keyword: str) -> tuple[float | None, str | None]:
    """Extract a ratio value from the ratio DataFrame."""
    if ratio is None or ratio.empty:
        return None, f"No ratio data for {keyword}"
    row = _find_row(ratio, keyword)
    if row is None:
        return None, f"Ratio '{keyword}' not found"
    periods = _get_period_columns(ratio)
    if not periods:
        return None, "No period columns in ratio data"
    try:
        value = float(row[periods[0]])
        if not np.isfinite(value):
            return None, f"{keyword} is not finite"
        # Convert percentage to ratio if needed
        if abs(value) > 1 and keyword in ("ROE", "ROA", "NIM", "NPL", "CIR", "CASA"):
            value = value / 100.0
        return value, None
    except (ValueError, KeyError):
        return None, f"Could not extract {keyword}"


def _compute_margin(income: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute net profit margin."""
    if income is None:
        return None, "No income statement"
    revenue_row = _find_row(income, "Doanh thu thuần")
    profit_row = _find_row(income, "Lợi nhuận sau thuế")
    if revenue_row is None or profit_row is None:
        return None, "Revenue or profit row not found"
    periods = _get_period_columns(income)
    if not periods:
        return None, "No period columns"
    try:
        revenue = float(revenue_row[periods[0]])
        profit = float(profit_row[periods[0]])
        if revenue == 0:
            return None, "Revenue is zero"
        return profit / revenue, None
    except (ValueError, KeyError):
        return None, "Could not compute net margin"


def _compute_gross_margin(income: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute gross profit margin."""
    if income is None:
        return None, "No income statement"
    revenue_row = _find_row(income, "Doanh thu thuần")
    cogs_row = _find_row(income, "Giá vốn")
    if revenue_row is None or cogs_row is None:
        return None, "Revenue or COGS row not found"
    periods = _get_period_columns(income)
    if not periods:
        return None, "No period columns"
    try:
        revenue = float(revenue_row[periods[0]])
        cogs = abs(float(cogs_row[periods[0]]))
        if revenue == 0:
            return None, "Revenue is zero"
        return (revenue - cogs) / revenue, None
    except (ValueError, KeyError):
        return None, "Could not compute gross margin"


def _compute_pe_relative(ratio: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute P/E relative to historical median."""
    if ratio is None or ratio.empty:
        return None, "No ratio data"
    row = _find_row(ratio, "P/E")
    if row is None:
        return None, "P/E row not found"
    periods = _get_period_columns(ratio)
    if len(periods) < 4:
        return None, "Need ≥4 quarters for P/E median"
    try:
        values = [
            float(row[p]) for p in periods if np.isfinite(float(row[p])) and float(row[p]) > 0
        ]
        if len(values) < 4:
            return None, "Not enough valid P/E values"
        current = values[0]
        median = np.median(values)
        if median == 0:
            return None, "Median P/E is zero"
        return current / median, None
    except (ValueError, KeyError):
        return None, "Could not compute P/E relative"


def _compute_inventory_turnover(
    income: pd.DataFrame | None, balance: pd.DataFrame | None
) -> tuple[float | None, str | None]:
    """Compute inventory turnover ratio."""
    if income is None or balance is None:
        return None, "Missing income or balance data"
    cogs_row = _find_row(income, "Giá vốn")
    inv_row = _find_row(balance, "Hàng tồn kho")
    if cogs_row is None or inv_row is None:
        return None, "COGS or inventory row not found"
    periods_inc = _get_period_columns(income)
    periods_bal = _get_period_columns(balance)
    if not periods_inc or not periods_bal:
        return None, "No period columns"
    try:
        cogs = abs(float(cogs_row[periods_inc[0]]))
        inventory = float(inv_row[periods_bal[0]])
        if inventory <= 0:
            return None, "Inventory is zero/negative"
        return (cogs * 4) / inventory, None  # Annualized from quarterly
    except (ValueError, KeyError):
        return None, "Could not compute inventory turnover"


def _compute_cfo_profit(
    cashflow: pd.DataFrame | None, income: pd.DataFrame | None
) -> tuple[float | None, str | None]:
    """Compute CFO to profit ratio."""
    if cashflow is None or income is None:
        return None, "Missing cash flow or income data"
    # Find operating cash flow (first row usually)
    cfo_keywords = ["kinh doanh", "operating", "hoạt động kinh doanh"]
    cfo_row = None
    for kw in cfo_keywords:
        cfo_row = _find_row(cashflow, kw)
        if cfo_row is not None:
            break
    profit_row = _find_row(income, "Lợi nhuận sau thuế")
    if cfo_row is None or profit_row is None:
        return None, "CFO or profit row not found"
    periods_cf = _get_period_columns(cashflow)
    periods_inc = _get_period_columns(income)
    if not periods_cf or not periods_inc:
        return None, "No period columns"
    try:
        cfo = float(cfo_row[periods_cf[0]])
        profit = float(profit_row[periods_inc[0]])
        if profit == 0:
            return None, "Profit is zero"
        return cfo / abs(profit), None
    except (ValueError, KeyError):
        return None, "Could not compute CFO/Profit"


def _compute_cfo_capex(cashflow: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute CFO to CAPEX ratio."""
    if cashflow is None:
        return None, "No cash flow data"
    cfo_row = None
    for kw in ["kinh doanh", "operating"]:
        cfo_row = _find_row(cashflow, kw)
        if cfo_row is not None:
            break
    capex_row = _find_row(cashflow, "mua sắm")
    if capex_row is None:
        capex_row = _find_row(cashflow, "TSCĐ")
    if cfo_row is None or capex_row is None:
        return None, "CFO or CAPEX row not found"
    periods = _get_period_columns(cashflow)
    if not periods:
        return None, "No period columns"
    try:
        cfo = float(cfo_row[periods[0]])
        capex = abs(float(capex_row[periods[0]]))
        if capex == 0:
            return None, "CAPEX is zero"
        return cfo / capex, None
    except (ValueError, KeyError):
        return None, "Could not compute CFO/CAPEX"


def _compute_debt_ebitda(
    balance: pd.DataFrame | None, income: pd.DataFrame | None
) -> tuple[float | None, str | None]:
    """Compute debt to EBITDA ratio."""
    if balance is None or income is None:
        return None, "Missing balance or income data"
    debt_row = _find_row(balance, "Nợ phải trả")
    if debt_row is None:
        debt_row = _find_row(balance, "NỢ PHẢI TRẢ")
    profit_row = _find_row(income, "Lợi nhuận trước thuế")
    if debt_row is None or profit_row is None:
        return None, "Debt or pre-tax profit row not found"
    periods_bal = _get_period_columns(balance)
    periods_inc = _get_period_columns(income)
    if not periods_bal or not periods_inc:
        return None, "No period columns"
    try:
        debt = float(debt_row[periods_bal[0]])
        ebit = float(profit_row[periods_inc[0]]) * 4  # Annualized
        if ebit <= 0:
            return None, "EBIT is zero/negative"
        return debt / ebit, None
    except (ValueError, KeyError):
        return None, "Could not compute Debt/EBITDA"


def _compute_leverage(balance: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute total assets / equity (leverage ratio)."""
    if balance is None:
        return None, "No balance sheet"
    assets_row = _find_row(balance, "TỔNG TÀI SẢN")
    if assets_row is None:
        assets_row = _find_row(balance, "TỔNG CỘNG TÀI SẢN")
    equity_row = _find_row(balance, "VỐN CHỦ SỞ HỮU")
    if assets_row is None or equity_row is None:
        return None, "Assets or equity row not found"
    periods = _get_period_columns(balance)
    if not periods:
        return None, "No period columns"
    try:
        assets = float(assets_row[periods[0]])
        equity = float(equity_row[periods[0]])
        if equity <= 0:
            return None, "Equity is zero/negative"
        return assets / equity, None
    except (ValueError, KeyError):
        return None, "Could not compute leverage"


def _compute_margin_equity(balance: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Compute margin lending / equity ratio for securities firms."""
    if balance is None:
        return None, "No balance sheet"
    margin_row = _find_row(balance, "cho vay")
    if margin_row is None:
        margin_row = _find_row(balance, "margin")
    equity_row = _find_row(balance, "VỐN CHỦ SỞ HỮU")
    if margin_row is None:
        return None, "Margin lending row not found"
    if equity_row is None:
        return None, "Equity row not found"
    periods = _get_period_columns(balance)
    if not periods:
        return None, "No period columns"
    try:
        margin = float(margin_row[periods[0]])
        equity = float(equity_row[periods[0]])
        if equity <= 0:
            return None, "Equity is zero/negative"
        return margin / equity, None
    except (ValueError, KeyError):
        return None, "Could not compute margin/equity"


def score_fa(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    ratio: pd.DataFrame | None,
    sector: str,
    sector_metrics_config: dict[str, Any],
) -> FAResult:
    """Compute FA score based on sector-specific metrics.

    Args:
        income: Income statement DataFrame.
        balance: Balance sheet DataFrame.
        cashflow: Cash flow statement DataFrame.
        ratio: Financial ratios DataFrame.
        sector: Sector key (e.g., 'technology', 'banking').
        sector_metrics_config: sector_metrics config dict.

    Returns:
        FAResult with score, status, reasons, and breakdown.
    """
    if sector not in sector_metrics_config.get("sectors", {}):
        return FAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=[f"No sector config for '{sector}'"],
            breakdown={},
        )

    metrics_config = sector_metrics_config["sectors"][sector]
    reasons: list[str] = []
    breakdown: dict[str, Any] = {}

    # Check minimum data availability
    has_income = income is not None and not income.empty
    has_balance = balance is not None and not balance.empty

    if not has_income and not has_balance:
        return FAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["No financial statements available"],
            breakdown={},
        )

    total_weight = 0.0
    weighted_score = 0.0
    available_metrics = 0
    missing_metrics: list[str] = []

    for metric_name, rule_dict in metrics_config.items():
        rule = MetricRule.model_validate(rule_dict)
        value, missing_reason = extract_metric_from_financials(
            income, balance, cashflow, ratio, metric_name, sector
        )

        if value is None:
            missing_metrics.append(metric_name)
            breakdown[metric_name] = {
                "raw": None,
                "score": None,
                "weight": rule.weight,
                "status": "N/A",
                "reason": missing_reason or "Data not available",
            }
            continue

        from backend.app.analysis.ta import normalize_metric

        normalized = normalize_metric(value, rule)
        if np.isnan(normalized):
            missing_metrics.append(metric_name)
            breakdown[metric_name] = {
                "raw": value,
                "score": None,
                "weight": rule.weight,
                "status": "N/A",
                "reason": "Normalization returned NaN",
            }
            continue

        weighted_score += normalized * rule.weight
        total_weight += rule.weight
        available_metrics += 1
        breakdown[metric_name] = {
            "raw": round(value, 6),
            "score": normalized,
            "weight": rule.weight,
            "weighted_contribution": round(normalized * rule.weight, 4),
            "unit": rule.unit,
        }

    if missing_metrics:
        reasons.append(f"Missing FA metrics: {', '.join(missing_metrics)}")

    if available_metrics == 0:
        return FAResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["No FA metrics could be computed"],
            breakdown=breakdown,
        )

    if total_weight < 0.99:
        score = None
        status = "PARTIAL_ANALYSIS"
        reasons.append(
            f"Total weight coverage: {total_weight:.2%} "
            f"(missing weight NOT redistributed per policy)"
        )
    else:
        score = weighted_score
        status = "COMPLETE"

    score = max(0.0, min(100.0, score)) if score is not None else None

    breakdown["_summary"] = {
        "sector": sector,
        "total_weight_covered": round(total_weight, 4),
        "available_metrics": available_metrics,
        "total_metrics": len(metrics_config),
        "final_score": round(score, 4) if score is not None else None,
    }

    return FAResult(
        score=round(score, 4) if score is not None else None,
        status=status,
        reasons=reasons,
        breakdown=breakdown,
    )
