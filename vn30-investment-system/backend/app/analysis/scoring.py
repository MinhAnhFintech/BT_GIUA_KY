"""Composite scoring and ranking engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.app.analysis.fa import FAResult
from backend.app.analysis.news import NewsResult
from backend.app.analysis.ta import TAResult

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư. "
    "Điểm không đại diện cho xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến."
)


@dataclass(frozen=True)
class CompositeScore:
    """Full composite score with component breakdown."""

    symbol: str
    sector: str
    fa_result: FAResult
    ta_result: TAResult
    news_result: NewsResult
    total_score: float | None
    status: str
    reasons: list[str]
    breakdown: dict[str, Any]


def compute_composite_score(
    symbol: str,
    sector: str,
    fa_result: FAResult,
    ta_result: TAResult,
    news_result: NewsResult,
    weights: dict[str, float],
) -> CompositeScore:
    """Compute composite score S = w_FA * FA + w_TA * TA + w_NEWS * NEWS.

    Missing components result in PARTIAL_ANALYSIS or INSUFFICIENT_DATA.
    Weights are NOT redistributed when a component is missing.

    Args:
        symbol: Stock symbol.
        sector: Stock sector.
        fa_result: FA analysis result.
        ta_result: TA analysis result.
        news_result: News analysis result.
        weights: Dict with keys FA, TA, NEWS and float weights summing to 1.

    Returns:
        CompositeScore with total_score (None if incomplete) and full breakdown.
    """
    reasons: list[str] = []
    breakdown: dict[str, Any] = {
        "weights": weights,
        "disclaimer": DISCLAIMER,
    }

    # Collect component statuses
    components = {
        "FA": fa_result,
        "TA": ta_result,
        "NEWS": news_result,
    }

    component_scores: dict[str, float | None] = {}
    all_complete = True
    any_available = False

    for name, result in components.items():
        score = result.score
        status = result.status
        component_scores[name] = score

        breakdown[name] = {
            "score": score,
            "status": status,
            "weight": weights.get(name, 0),
            "reasons": result.reasons,
            "detail": result.breakdown,
        }

        if status != "COMPLETE":
            all_complete = False
            reasons.extend(f"[{name}] {r}" for r in result.reasons)

        if score is not None:
            any_available = True

    if all_complete:
        # All components available - compute full score
        total = sum(
            component_scores[name] * weights[name]  # type: ignore[operator]
            for name in ("FA", "TA", "NEWS")
        )
        total = max(0.0, min(100.0, total))
        status = "COMPLETE"
    elif not any_available:
        total = None
        status = "INSUFFICIENT_DATA"
        reasons.append("No analysis components available")
    else:
        # Some components missing - PARTIAL_ANALYSIS
        # Do NOT redistribute weights (per policy)
        total = None
        status = "PARTIAL_ANALYSIS"
        missing = [name for name, score in component_scores.items() if score is None]
        reasons.append(
            f"Missing components: {', '.join(missing)}. Weights NOT redistributed per policy."
        )

    breakdown["total_score"] = round(total, 4) if total is not None else None
    breakdown["status"] = status

    return CompositeScore(
        symbol=symbol,
        sector=sector,
        fa_result=fa_result,
        ta_result=ta_result,
        news_result=news_result,
        total_score=round(total, 4) if total is not None else None,
        status=status,
        reasons=reasons,
        breakdown=breakdown,
    )


@dataclass(frozen=True)
class RankingEntry:
    """One entry in the ranking table."""

    rank: int
    symbol: str
    sector: str
    fa_score: float | None
    ta_score: float | None
    news_score: float | None
    total_score: float | None
    status: str
    reasons: list[str]


def rank_stocks(
    scores: list[CompositeScore],
) -> tuple[list[RankingEntry], list[RankingEntry]]:
    """Rank stocks into main and secondary tables.

    Main table: only COMPLETE stocks with total_score.
    Secondary table: PARTIAL_ANALYSIS and INSUFFICIENT_DATA stocks.

    Args:
        scores: List of CompositeScore results.

    Returns:
        Tuple of (main_ranking, secondary_ranking).
    """
    complete: list[CompositeScore] = []
    incomplete: list[CompositeScore] = []

    for score in scores:
        if score.status == "COMPLETE" and score.total_score is not None:
            complete.append(score)
        else:
            incomplete.append(score)

    # Sort complete by total_score descending
    complete.sort(key=lambda s: s.total_score or 0, reverse=True)

    main_ranking = [
        RankingEntry(
            rank=i + 1,
            symbol=s.symbol,
            sector=s.sector,
            fa_score=s.fa_result.score,
            ta_score=s.ta_result.score,
            news_score=s.news_result.score,
            total_score=s.total_score,
            status=s.status,
            reasons=s.reasons,
        )
        for i, s in enumerate(complete)
    ]

    secondary_ranking = [
        RankingEntry(
            rank=0,
            symbol=s.symbol,
            sector=s.sector,
            fa_score=s.fa_result.score,
            ta_score=s.ta_result.score,
            news_score=s.news_result.score,
            total_score=s.total_score,
            status=s.status,
            reasons=s.reasons,
        )
        for s in incomplete
    ]

    return main_ranking, secondary_ranking
