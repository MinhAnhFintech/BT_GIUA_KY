"""Measure stages without logging API keys, URLs or raw provider exceptions."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger(__name__)


@contextmanager
def timed(operation: str) -> Iterator[dict[str, float]]:
    """Return elapsed seconds even when an operation raises an exception."""
    measurement: dict[str, float] = {}
    start = perf_counter()
    try:
        yield measurement
    finally:
        measurement["duration_seconds"] = perf_counter() - start
        logger.info(
            "operation=%s duration_seconds=%.4f", operation, measurement["duration_seconds"]
        )
