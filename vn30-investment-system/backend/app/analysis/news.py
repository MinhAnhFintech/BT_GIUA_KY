"""News sentiment scoring engine with rule-based classification."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsResult:
    """News score with full breakdown for transparency."""

    score: float | None
    status: str  # COMPLETE, PARTIAL_ANALYSIS, INSUFFICIENT_DATA
    reasons: list[str]
    breakdown: dict[str, Any]


def dedup_hash(title: str) -> str:
    """Generate a deduplication hash from normalized title."""
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def title_similarity(title1: str, title2: str) -> float:
    """Simple Jaccard similarity between two titles."""
    words1 = set(re.sub(r"\s+", " ", title1.strip().lower()).split())
    words2 = set(re.sub(r"\s+", " ", title2.strip().lower()).split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


def classify_event(title: str, events_config: dict[str, Any]) -> tuple[str, float]:
    """Classify news event type and impact score.

    Args:
        title: News title string.
        events_config: Event classification config from scoring.yaml.

    Returns:
        Tuple of (event_type, impact_score).
    """
    title_lower = title.lower()
    best_event = "other"
    best_impact = events_config.get("other", {}).get("impact", 0.3)

    for event_type, event_cfg in events_config.items():
        terms = event_cfg.get("terms", [])
        for term in terms:
            if term.lower() in title_lower:
                impact = event_cfg.get("impact", 0.3)
                if impact > best_impact:
                    best_event = event_type
                    best_impact = impact
                break

    return best_event, best_impact


def score_sentiment(
    title: str,
    positive_terms: list[str],
    negative_terms: list[str],
    neutral_score: float = 50.0,
    sentiment_scale: float = 50.0,
) -> tuple[float, float, str]:
    """Score sentiment of a news title using keyword matching.

    Args:
        title: News title.
        positive_terms: List of positive keywords.
        negative_terms: List of negative keywords.
        neutral_score: Base score for neutral news.
        sentiment_scale: Scale factor for sentiment adjustment.

    Returns:
        Tuple of (sentiment_score [0-100], confidence [0-1], direction).
    """
    title_lower = title.lower()

    pos_count = sum(1 for term in positive_terms if term.lower() in title_lower)
    neg_count = sum(1 for term in negative_terms if term.lower() in title_lower)

    total = pos_count + neg_count
    if total == 0:
        return neutral_score, 0.3, "neutral"

    # Net sentiment direction
    net = pos_count - neg_count
    confidence = min(1.0, total * 0.25)  # More keywords = higher confidence

    if net > 0:
        adjustment = min(sentiment_scale, net * sentiment_scale * 0.5)
        return min(100.0, neutral_score + adjustment), confidence, "positive"
    elif net < 0:
        adjustment = min(sentiment_scale, abs(net) * sentiment_scale * 0.5)
        return max(0.0, neutral_score - adjustment), confidence, "negative"
    else:
        return neutral_score, confidence * 0.5, "mixed"


def compute_freshness_weight(
    published_at: datetime,
    as_of: datetime,
    half_life_days: float = 14.0,
) -> float:
    """Exponential decay weight based on news age.

    Args:
        published_at: When the news was published.
        as_of: Reference date for freshness calculation.
        half_life_days: Half-life in days for decay.

    Returns:
        Weight between 0 and 1.
    """
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    age_days = (as_of - published_at).total_seconds() / 86400.0

    if age_days < 0:
        return 0.0  # Future news rejected

    decay = math.exp(-math.log(2) * age_days / half_life_days)
    return max(0.0, min(1.0, decay))


def deduplicate_news(
    news_items: list[dict[str, Any]],
    similarity_threshold: float = 0.90,
) -> list[dict[str, Any]]:
    """Remove duplicate news items based on title similarity.

    Args:
        news_items: List of news item dicts with 'title' key.
        similarity_threshold: Minimum similarity to consider duplicate.

    Returns:
        Deduplicated list.
    """
    if not news_items:
        return []

    unique: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for item in news_items:
        title = item.get("title", "")
        h = dedup_hash(title)

        if h in seen_hashes:
            continue

        # Check similarity with existing unique items
        is_dup = False
        for existing in unique:
            if title_similarity(title, existing.get("title", "")) >= similarity_threshold:
                is_dup = True
                break

        if not is_dup:
            seen_hashes.add(h)
            unique.append(item)

    return unique


def score_news(
    news_df: pd.DataFrame | None,
    config: dict[str, Any],
    as_of: datetime | None = None,
) -> NewsResult:
    """Compute news score from news DataFrame.

    Args:
        news_df: DataFrame with news items (title, published_at/publish_time, url).
        config: News config section from scoring.yaml.
        as_of: Reference datetime for freshness calculation.

    Returns:
        NewsResult with score, status, reasons, and breakdown.
    """
    reasons: list[str] = []
    breakdown: dict[str, Any] = {}

    if news_df is None or (hasattr(news_df, "empty") and news_df.empty) or len(news_df) == 0:
        return NewsResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["No news data available"],
            breakdown={},
        )

    if as_of is None:
        as_of = datetime.now(UTC)
    elif as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    news_config = config.get("news", config)
    half_life = news_config.get("half_life_days", 14)
    sim_threshold = news_config.get("similarity_threshold", 0.90)
    neutral_score = news_config.get("neutral_score", 50)
    sentiment_scale = news_config.get("sentiment_scale", 50)
    min_confidence = news_config.get("minimum_confidence", 0.50)
    positive_terms = news_config.get("positive_terms", [])
    negative_terms = news_config.get("negative_terms", [])
    events_config = news_config.get("events", {})

    # Convert DataFrame to list of dicts
    news_items = news_df.to_dict("records")

    # Deduplicate
    original_count = len(news_items)
    news_items = deduplicate_news(news_items, sim_threshold)
    dedup_count = original_count - len(news_items)
    if dedup_count > 0:
        reasons.append(f"Removed {dedup_count} duplicate news items")

    if not news_items:
        return NewsResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["All news items were duplicates"],
            breakdown={},
        )

    # Score each news item
    item_scores: list[dict[str, Any]] = []
    total_weight = 0.0
    weighted_sum = 0.0

    for item in news_items:
        title = str(item.get("title", item.get("news_title", item.get("newsTitle", ""))))
        url = str(item.get("url", item.get("news_url", "")))

        # Parse published date
        pub_date = None
        for date_field in ["published_at", "publish_time", "publishTime", "pubDate"]:
            if date_field in item and item[date_field] is not None:
                try:
                    if isinstance(item[date_field], datetime):
                        pub_date = item[date_field]
                    elif isinstance(item[date_field], str):
                        pub_date = pd.to_datetime(item[date_field])
                    break
                except (ValueError, TypeError):
                    continue

        if pub_date is None:
            continue

        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=UTC)

        # Freshness weight
        freshness = compute_freshness_weight(pub_date, as_of, half_life)
        if freshness <= 0:
            continue

        # Sentiment
        sentiment_score, confidence, direction = score_sentiment(
            title, positive_terms, negative_terms, neutral_score, sentiment_scale
        )

        # Event classification
        event_type, impact = classify_event(title, events_config)

        # Combined item score
        item_weight = freshness * impact
        if confidence >= min_confidence:
            weighted_sum += sentiment_score * item_weight
            total_weight += item_weight

        item_detail = {
            "title": title[:200],  # Truncate for storage
            "url": url,
            "published_at": pub_date.isoformat(),
            "sentiment_score": round(sentiment_score, 2),
            "confidence": round(confidence, 2),
            "direction": direction,
            "event_type": event_type,
            "impact": impact,
            "freshness": round(freshness, 4),
            "weight": round(item_weight, 4),
        }
        item_scores.append(item_detail)

    if total_weight == 0 or not item_scores:
        return NewsResult(
            score=None,
            status="INSUFFICIENT_DATA",
            reasons=["No news items met confidence threshold"],
            breakdown={"items_analyzed": len(item_scores)},
        )

    final_score = weighted_sum / total_weight
    final_score = max(0.0, min(100.0, final_score))

    breakdown = {
        "items_total": original_count,
        "items_after_dedup": len(news_items),
        "items_scored": len(item_scores),
        "total_weight": round(total_weight, 4),
        "final_score": round(final_score, 4),
        "items": item_scores[:20],  # Limit items in breakdown
    }

    status = "COMPLETE" if len(item_scores) >= 1 else "PARTIAL_ANALYSIS"

    return NewsResult(
        score=round(final_score, 4),
        status=status,
        reasons=reasons,
        breakdown=breakdown,
    )
