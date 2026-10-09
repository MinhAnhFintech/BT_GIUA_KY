"""Independent refresh stages preserve successful sources on partial failures."""

import logging
from datetime import UTC, datetime, timedelta

from backend.app.data.providers import (
    VnstockFundamentalsProvider,
    VnstockNewsProvider,
    VnstockPriceProvider,
)
from backend.app.data.store import get_latest_price_date, save_fundamentals, save_news, save_prices

logger = logging.getLogger(__name__)


class DataUpdater:
    def __init__(self):
        self.price_provider = VnstockPriceProvider()
        self.fundamentals_provider = VnstockFundamentalsProvider()
        self.news_provider = VnstockNewsProvider()

    def refresh_all(self, symbols, as_of_date):
        results = []
        for symbol in symbols:
            result = {"symbol": symbol, "stages": {}}
            latest = get_latest_price_date(symbol)
            start = latest + timedelta(days=1) if latest else as_of_date - timedelta(days=730)
            tasks = {
                "prices": lambda symbol=symbol, start=start: (
                    save_prices(symbol, self.price_provider.prices(symbol, start, as_of_date))
                    if start <= as_of_date
                    else None
                ),
                "fundamentals": lambda symbol=symbol, start=start: save_fundamentals(
                    symbol, self.fundamentals_provider.fundamentals(symbol, "quarter")
                ),
                "news": lambda symbol=symbol, start=start: save_news(
                    self.news_provider.news(
                        symbol,
                        datetime.combine(as_of_date - timedelta(days=90), datetime.min.time(), UTC),
                        datetime.combine(as_of_date, datetime.max.time(), UTC),
                    ),
                    symbol,
                ),
            }
            for name, task in tasks.items():
                try:
                    task()
                    result["stages"][name] = "OK"
                except Exception as exc:
                    result["stages"][name] = "FETCH_FAILED_" + type(exc).__name__
                    logger.warning("Refresh %s %s failed (%s)", symbol, name, type(exc).__name__)
            results.append(result)
        return {"symbols": results, "as_of_date": as_of_date.isoformat()}
