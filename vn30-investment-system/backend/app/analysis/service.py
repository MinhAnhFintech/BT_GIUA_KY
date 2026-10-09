"""Point-in-time cached analysis. No network or fabricated fallback values."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd

from backend.app.analysis.fa import FAResult, score_fa
from backend.app.analysis.news import NewsResult, score_news
from backend.app.analysis.scoring import DISCLAIMER, compute_composite_score, rank_stocks
from backend.app.analysis.ta import TAResult, compute_ma, compute_macd, compute_rsi, score_ta
from backend.app.data.store import get_fundamentals, get_news, get_prices

ALIASES = {
    "Net Sales": "Doanh thu thuần",
    "Revenue (Bn. VND)": "Doanh thu thuần",
    "Net Profit For the Year": "Lợi nhuận sau thuế",
    "Net Profit For the Year (Bn. VND)": "Lợi nhuận sau thuế",
    "Cost of Sales": "Giá vốn",
    "Inventories": "Hàng tồn kho",
    "Owners' Equity": "equity",
    "Total Equity": "equity",
}


def _statements(frame):
    output = {}
    for kind in ("income", "balance", "cashflow", "ratio"):
        rows = []
        if not frame.empty:
            subset = frame[frame.metric.str.startswith(kind + ":")].copy()
            for metric, group in subset.groupby("metric"):
                name = metric.split(":", 1)[1]
                name = ALIASES.get(name, name)
                row = {"item_en": name, "item": name}
                for _, v in group.sort_values("period_end", ascending=False).iterrows():
                    end = v.period_end
                    period = (
                        f"{end.year}-Q{(end.month - 1) // 3 + 1}"
                        if v.period_type == "quarter"
                        else str(end.year)
                    )
                    row[period] = float(v.value)
                rows.append(row)
        output[kind] = pd.DataFrame(rows)
    return output


def _clean(records):
    import json

    return (
        json.loads(pd.DataFrame(records).to_json(orient="records", date_format="iso"))
        if records
        else []
    )


def analyze_cached(symbols: list[dict], as_of: date, settings) -> dict:
    cutoff = datetime.combine(as_of, datetime.max.time(), timezone(timedelta(hours=7))).astimezone(
        UTC
    )
    scores = []
    stocks = []
    for item in symbols:
        symbol = item["symbol"]
        sector = item["sector"]
        prices = get_prices(symbol, as_of - timedelta(days=1100), as_of, known_at=cutoff)
        fundamentals = get_fundamentals(symbol, known_at=cutoff)
        news = get_news([symbol], settings.data_requirements["news_window_days"], known_at=cutoff)
        statements = _statements(fundamentals)
        fa = score_fa(
            statements["income"],
            statements["balance"],
            statements["cashflow"],
            statements["ratio"],
            sector,
            settings.sector_metrics,
        )
        if (
            not fundamentals.empty
            and fundamentals.period_end.nunique() < settings.data_requirements["min_quarters"]
        ):
            fa = FAResult(
                None,
                "INSUFFICIENT_DATA",
                ["Insufficient historical financial periods"],
                fa.breakdown,
            )
        ta = score_ta(prices, settings.scoring)
        if len(prices) < settings.data_requirements["min_price_sessions"]:
            ta = TAResult(None, "INSUFFICIENT_DATA", ["Insufficient price sessions"], ta.breakdown)
        elif (as_of - prices.time.max()).days > settings.data_requirements.get(
            "price_stale_calendar_days", 7
        ):
            ta = TAResult(None, "INSUFFICIENT_DATA", ["Price series is stale"], ta.breakdown)
        ns = score_news(news, settings.scoring, cutoff)
        if len(news) < settings.data_requirements["min_news"]:
            ns = NewsResult(
                None, "INSUFFICIENT_DATA", ["Insufficient dated news items"], ns.breakdown
            )
        composite = compute_composite_score(symbol, sector, fa, ta, ns, settings.scoring["weights"])
        scores.append(composite)
        chart = prices.copy()
        if not chart.empty:
            for window in settings.scoring["ta"]["ma_windows"]:
                chart[f"ma{window}"] = compute_ma(chart.close, window)
            chart["rsi14"] = compute_rsi(chart.close, settings.scoring["ta"]["rsi_window"])
            chart["macd"], chart["macd_signal"], chart["macd_histogram"] = compute_macd(chart.close)
        stocks.append(
            {
                "symbol": symbol,
                "sector": sector,
                "status": composite.status,
                "total_score": composite.total_score,
                "fa_score": fa.score,
                "ta_score": ta.score,
                "news_score": ns.score,
                "reasons": composite.reasons,
                "breakdown": composite.breakdown,
                "prices": _clean(chart.to_dict("records")),
                "fundamentals": _clean(fundamentals.to_dict("records")),
                "news": _clean(news.to_dict("records")),
                "provenance": {
                    "price_ids": prices.id.tolist() if not prices.empty else [],
                    "fundamental_ids": fundamentals.id.tolist() if not fundamentals.empty else [],
                    "news_ids": news.id.tolist() if not news.empty else [],
                    "known_at": cutoff.isoformat(),
                    "adjustments_verified": False,
                    "financial_publications_inferred": True,
                },
            }
        )
    main, secondary = rank_stocks(scores)
    return {
        "as_of_date": as_of.isoformat(),
        "config_hash": settings.config_hash,
        "main_ranking": [asdict(r) for r in main],
        "secondary_ranking": [asdict(r) for r in secondary],
        "stocks": stocks,
        "disclaimer": DISCLAIMER,
    }
