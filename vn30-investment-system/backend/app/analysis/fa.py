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
    requirements: dict[str, Any] | None = None,
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
            return _compute_pe_relative(
                ratio, (requirements or {}).get("valuation_history_quarters", 12)
            )
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
        logger.warning("Failed to extract %s for %s: %s", metric_name, sector, type(e).__name__)
        return None, "METRIC_EXTRACTION_FAILED"


# Explicit aliases avoid selecting subtotal and adjustment rows by substring.
LABELS = {
    "Doanh thu thuần": (
        "Doanh thu thuần về bán hàng và cung cấp dịch vụ",
        "Net Sales",
        "Net Revenue",
        "Revenue (Bn. VND)",
    ),
    "Lợi nhuận sau thuế": (
        "Lợi nhuận sau thuế thu nhập doanh nghiệp",
        "Net Profit For the Year",
        "Net Profit For the Year (Bn. VND)",
    ),
    "Giá vốn": ("Giá vốn hàng bán", "Cost of Sales", "Cost of Goods Sold"),
    "Hàng tồn kho": ("Inventories", "Inventory"),
    "CFO": (
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
        "Net cash flows from operating activities",
        "Net Cash From Operating Activities",
        "Operating Cash Flow",
    ),
    "CAPEX": (
        "Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác",
        "Purchase of Fixed Assets",
        "Capital Expenditure",
        "CAPEX",
    ),
    "Nợ vay": ("Interest-bearing Debt", "Total Borrowings", "Total Debt"),
    "Nợ vay ngắn hạn": ("Vay và nợ thuê tài chính ngắn hạn", "Short-term Borrowings"),
    "Nợ vay dài hạn": ("Vay và nợ thuê tài chính dài hạn", "Long-term Borrowings"),
    "EBITDA": ("Earnings Before Interest Taxes Depreciation and Amortization",),
    "TỔNG TÀI SẢN": ("TỔNG CỘNG TÀI SẢN", "Total Assets"),
    "VỐN CHỦ SỞ HỮU": ("Owners' Equity", "Total Equity", "Equity"),
    "cho vay margin": (
        "Cho vay giao dịch ký quỹ",
        "Cho vay hoạt động giao dịch ký quỹ",
        "Margin Lending",
        "Margin Loans",
    ),
    "Doanh thu môi giới": ("Doanh thu nghiệp vụ môi giới chứng khoán", "Brokerage Revenue"),
    "FVTPL": (
        "Lãi/lỗ thuần từ tài sản tài chính ghi nhận thông qua lãi/lỗ",
        "Net Profit From FVTPL",
        "FVTPL Profit",
    ),
    "ROE": (
        "ROE bình quân 4 quý gần nhất",
        "Tỷ suất lợi nhuận trên vốn chủ sở hữu bình quân (ROEA)",
        "ROE (%)",
        "ROEA",
    ),
    "ROA": (
        "ROA bình quân 4 quý gần nhất",
        "Tỷ suất sinh lợi trên tổng tài sản bình quân (ROAA)",
        "ROA (%)",
        "ROAA",
    ),
    "P/E": (
        "Chỉ số giá thị trường trên thu nhập (P/E)",
        "Price to Earnings",
        "P/E (x)",
    ),
    "NIM": (
        "Net Interest Margin",
        "NIM (%)",
        "Tỷ lệ thu nhập lãi thuần",
    ),
    "NPL": (
        "Non-performing Loan Ratio",
        "NPL (%)",
        "Tỷ lệ nợ xấu",
    ),
    "NPL Coverage": (
        "Loan Loss Coverage",
        "NPL Coverage (%)",
        "Tỷ lệ bao phủ nợ xấu",
        "Loan Loss Reserves/NPLs",
    ),
    "CIR": (
        "Cost to Income Ratio",
        "CIR (%)",
        "Cost/Income Ratio",
        "Tỷ lệ chi phí hoạt động trên thu nhập hoạt động",
    ),
    "CASA": (
        "CASA (%)",
        "Current Account Savings Account Ratio",
        "CASA Ratio",
        "Tỷ lệ tiền gửi không kỳ hạn",
    ),
}


def _label(value: str) -> str:
    """Strip source numbering while retaining the complete semantic name."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFC", str(value)).strip().casefold()
    text = re.sub(r"^\s*(?:[ivx]+\.|\d+[.)])\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_period_columns(df: pd.DataFrame, quarterly_only: bool = False) -> list[str]:
    """Sort dated periods; quarterly calculations never count annual columns."""
    import re

    columns = [str(c) for c in df.columns if re.fullmatch(r"\d{4}-Q[1-4]", str(c))]
    if not columns and not quarterly_only:
        columns = [str(c) for c in df.columns if re.fullmatch(r"\d{4}", str(c))]
    return sorted(columns, reverse=True)


def _find_row(df: pd.DataFrame | None, keyword: str) -> pd.Series | None:
    """Find a row by keyword/alias; when multiple rows match, pick the freshest.

    If exactly one row matches, return it.  If multiple rows match (typically
    because old and new SDK label vintages both exist), select the row whose
    max period column is most recent.  This avoids silently returning stale
    2018 data when recent 2025+ data is available under a different label.
    """
    if df is None or df.empty:
        return None
    candidates = {_label(keyword), *(_label(v) for v in LABELS.get(keyword, ()))}
    mask = pd.Series(False, index=df.index)
    for column in ("item", "item_en"):
        if column in df:
            mask |= df[column].map(_label).isin(candidates)
    matched = df.loc[mask]
    if len(matched) == 0:
        return None
    if len(matched) == 1:
        return matched.iloc[0]
    # Multiple matches — pick the one with the most recent period column.
    periods = _get_period_columns(df)
    if not periods:
        logger.warning(
            "Multiple rows match '%s' but no period columns found; returning None", keyword
        )
        return None
    best_idx = None
    best_period = ""
    tied_rows = []
    for idx in matched.index:
        row = matched.loc[idx]
        for p in periods:
            val = _value(row, p)
            if val is not None:
                if p > best_period:
                    best_period = p
                    best_idx = idx
                    tied_rows = [row]
                elif p == best_period:
                    tied_rows.append(row)
                break  # only need max period per row
    if best_idx is not None:
        if any(
            _value(row, best_period) != _value(tied_rows[0], best_period)
            or row.get("unit") != tied_rows[0].get("unit")
            for row in tied_rows[1:]
        ):
            return None
        logger.info(
            "Multiple rows match '%s'; selected row with latest period %s",
            keyword,
            best_period,
        )
        return matched.loc[best_idx]
    logger.warning("Multiple rows match '%s' but none have valid period data", keyword)
    return None


def _value(row: pd.Series, period: str) -> float | None:
    try:
        value = float(row[period])
        return value if np.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


def _latest_shared_period(*tables: pd.DataFrame) -> str | None:
    """All statement operands must describe their latest same fiscal period."""
    latest = [(_get_period_columns(df) or [None])[0] for df in tables]
    return latest[0] if latest and latest[0] is not None and len(set(latest)) == 1 else None


def _row_unit(df: pd.DataFrame, row: pd.Series) -> str | None:
    for name in ("unit", "original_unit"):
        value = row.get(name)
        if (
            value is not None
            and pd.notna(value)
            and str(value) in {"ratio", "percent", "multiple", "VND", "million_VND", "billion_VND"}
        ):
            return str(value)
    return None


def _compute_yoy(df, keyword, label):
    row = _find_row(df, keyword)
    if row is None:
        return None, f"Exact {label} metric is missing or ambiguous"
    periods = _get_period_columns(df, quarterly_only=True)
    if not periods:
        return None, "No quarterly periods"
    current_period = periods[0]
    prior_period = f"{int(current_period[:4]) - 1}{current_period[4:]}"
    current, previous = _value(row, current_period), _value(row, prior_period)
    if current is None or previous is None or previous == 0:
        return None, f"Missing/invalid same-quarter YoY inputs: {current_period}, {prior_period}"
    return (current - previous) / abs(previous), None


def _extract_ratio(ratio, keyword):
    row = _find_row(ratio, keyword)
    if row is None:
        return None, f"Exact ratio {keyword} is missing or ambiguous"
    periods = _get_period_columns(ratio)
    value = _value(row, periods[0]) if periods else None
    if value is None:
        return None, f"Latest {keyword} is unavailable"
    unit = _row_unit(ratio, row)
    labels = str(row.get("item", "")) + str(row.get("item_en", ""))
    if unit == "percent":
        return value / 100, None
    if unit in {"ratio", "multiple"}:
        return value, None
    if row.get("unit") == "SOURCE_NATIVE_UNVERIFIED":
        return None, f"{keyword} provider unit is unverified; SDK printed labels are not units"
    if "%" in labels:
        return value / 100, None
    return None, f"{keyword} ratio unit is unverified; magnitude is not used to guess percent"


def _same_table_ratio(df, numerator, denominator):
    first, second = _find_row(df, numerator), _find_row(df, denominator)
    if first is None or second is None:
        return None, f"Exact {numerator}/{denominator} inputs missing or ambiguous"
    units = (_row_unit(df, first), _row_unit(df, second))
    if units[0] is not None and units[1] is not None and units[0] != units[1]:
        return None, "Monetary units differ; operands cannot be divided without conversion"
    periods = _get_period_columns(df)
    a, b = (_value(first, periods[0]), _value(second, periods[0])) if periods else (None, None)
    if a is None or b is None or b <= 0:
        return None, "Latest same-period operands missing/invalid"
    return a / b, None


def _compute_margin(income):
    return _same_table_ratio(income, "Lợi nhuận sau thuế", "Doanh thu thuần")


def _compute_gross_margin(income):
    value, reason = _same_table_ratio(income, "Giá vốn", "Doanh thu thuần")
    return (1 - abs(value), None) if value is not None else (None, reason)


def _compute_pe_relative(ratio, min_quarters=12):
    row = _find_row(ratio, "P/E")
    periods = _get_period_columns(ratio, quarterly_only=True) if ratio is not None else []
    if row is None or not periods:
        return None, "Exact P/E history missing or ambiguous"
    current = _value(row, periods[0])
    year, quarter = int(periods[0][:4]), int(periods[0][-1])
    expected = []
    for _ in range(min_quarters):
        expected.append(f"{year}-Q{quarter}")
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    values = [_value(row, p) for p in expected]
    if (
        current is None
        or current <= 0
        or any(p not in periods for p in expected)
        or any(v is None or v <= 0 for v in values)
    ):
        return None, f"Need {min_quarters} valid quarterly P/E values including latest"
    return current / float(np.median(values)), None


def _ttm(row, period):
    if "-Q" not in period:
        return _value(row, period)
    y, q = int(period[:4]), int(period[-1])
    periods = []
    for _ in range(4):
        periods.append(f"{y}-Q{q}")
        q -= 1
        if q == 0:
            y -= 1
            q = 4
    values = [_value(row, p) for p in periods]
    return sum(values) if all(v is not None for v in values) else None


def _compute_inventory_turnover(income, balance):
    cogs, inventory = _find_row(income, "Giá vốn"), _find_row(balance, "Hàng tồn kho")
    period = (
        _latest_shared_period(income, balance)
        if income is not None and balance is not None
        else None
    )
    if cogs is None or inventory is None or period is None:
        return None, "Inventory turnover needs exact matched fiscal periods"
    prior = f"{int(period[:4]) - 1}{period[4:]}"
    latest, old = _value(inventory, period), _value(inventory, prior)
    total = _ttm(cogs, period)
    if total is None or latest is None or old is None or latest + old <= 0:
        return None, "TTM COGS and beginning/end inventory are required"
    return abs(total) / ((latest + old) / 2), None


def _cross_ratio(first_table, second_table, first_label, second_label, absolute_denominator=False):
    first, second = _find_row(first_table, first_label), _find_row(second_table, second_label)
    period = (
        _latest_shared_period(first_table, second_table)
        if first_table is not None and second_table is not None
        else None
    )
    if first is None or second is None or period is None:
        return None, "Exact inputs must match the latest fiscal period"
    a, b = _value(first, period), _value(second, period)
    first_unit, second_unit = _row_unit(first_table, first), _row_unit(second_table, second)
    if first_unit is None or first_unit != second_unit:
        return None, "Cross-statement monetary units are unverified or differ"
    if a is None or b is None or b == 0:
        return None, "Matched-period inputs missing or invalid"
    return a / (abs(b) if absolute_denominator else b), None


def _compute_cfo_profit(cashflow, income):
    value, reason = _cross_ratio(cashflow, income, "CFO", "Lợi nhuận sau thuế")
    profit = _find_row(income, "Lợi nhuận sau thuế")
    periods = _get_period_columns(income) if income is not None else []
    if profit is not None and periods and (_value(profit, periods[0]) or 0) <= 0:
        return None, "CFO/profit requires positive profit; a loss cannot produce a favorable ratio"
    return value, reason


def _compute_cfo_capex(cashflow):
    value, reason = _same_table_ratio(cashflow, "CFO", "CAPEX")
    # CAPEX may be represented as negative cash outflow.
    if value is None:
        first, second = _find_row(cashflow, "CFO"), _find_row(cashflow, "CAPEX")
        periods = _get_period_columns(cashflow) if cashflow is not None else []
        if first is not None and second is not None and periods:
            a, b = _value(first, periods[0]), _value(second, periods[0])
            if a is not None and b is not None and b != 0:
                return a / abs(b), None
    return (value, None) if value is not None else (None, reason)


def _compute_debt_ebitda(balance, income):
    debt, ebitda = _find_row(balance, "Nợ vay"), _find_row(income, "EBITDA")
    period = (
        _latest_shared_period(balance, income)
        if balance is not None and income is not None
        else None
    )
    if ebitda is None or period is None:
        return None, (
            "Verified interest-bearing debt and EBITDA with matching period are required; "
            "total liabilities/pre-tax profit are not proxies"
        )
    if debt is None:
        short = _find_row(balance, "Nợ vay ngắn hạn")
        long = _find_row(balance, "Nợ vay dài hạn")
        if short is None or long is None:
            return None, "Total interest-bearing debt or both short/long borrowings are required"
        unit = _row_unit(balance, short)
        if unit is None or unit != _row_unit(balance, long):
            return None, "Short/long borrowing units are unverified or differ"
        a, b = _value(short, period), _value(long, period)
        total = a + b if a is not None and b is not None and a >= 0 and b >= 0 else None
    else:
        unit = _row_unit(balance, debt)
        total = _value(debt, period)
    if unit is None or unit != _row_unit(income, ebitda):
        return None, "Debt/EBITDA monetary units are unverified or differ"
    denominator = _ttm(ebitda, period)
    if total is None or total < 0 or denominator is None or denominator <= 0:
        return None, "Need debt and positive annual/TTM EBITDA"
    return total / denominator, None


def _compute_leverage(balance):
    return _same_table_ratio(balance, "TỔNG TÀI SẢN", "VỐN CHỦ SỞ HỮU")


def _compute_margin_equity(balance):
    return _same_table_ratio(balance, "cho vay margin", "VỐN CHỦ SỞ HỮU")


def score_fa(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    ratio: pd.DataFrame | None,
    sector: str,
    sector_metrics_config: dict[str, Any],
    requirements: dict[str, Any] | None = None,
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
            income, balance, cashflow, ratio, metric_name, sector, requirements
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
