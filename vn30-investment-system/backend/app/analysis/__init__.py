"""Analysis engine __init__ - public API for the analysis package."""

from backend.app.analysis.fa import FAResult, score_fa
from backend.app.analysis.news import NewsResult, score_news
from backend.app.analysis.scoring import (
    CompositeScore,
    RankingEntry,
    compute_composite_score,
    rank_stocks,
)
from backend.app.analysis.ta import TAResult, score_ta

__all__ = [
    "FAResult",
    "NewsResult",
    "TAResult",
    "CompositeScore",
    "RankingEntry",
    "score_fa",
    "score_ta",
    "score_news",
    "compute_composite_score",
    "rank_stocks",
]
