"""Point-in-time cached analysis. No network or fabricated fallback values."""

from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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

# VCI SDK changed metric labels between versions. Map old (English short) names
# to their modern (Vietnamese long) equivalents so _statements() can merge them
# into a single row with the most-recent periods kept.  Keys are casefold()ed.
_RATIO_EQUIVALENCES: dict[str, str] = {
    "roe (%)": "Tỷ suất lợi nhuận trên vốn chủ sở hữu bình quân (ROEA)",
    "roa (%)": "Tỷ suất sinh lợi trên tổng tài sản bình quân (ROAA)",
    "p/e": "Chỉ số giá thị trường trên thu nhập (P/E)",
    "p/b": "Chỉ số giá thị trường trên giá trị sổ sách (P/B)",
    "p/s": "Chỉ số giá thị trường trên doanh thu thuần (P/S)",
    "price to earnings": "Chỉ số giá thị trường trên thu nhập (P/E)",
    "p/e (x)": "Chỉ số giá thị trường trên thu nhập (P/E)",
    "gross margin (%)": "Tỷ suất lợi nhuận gộp biên",
    "after-tax profit margin (%)": "Tỷ suất sinh lợi trên doanh thu thuần",
    "ebit margin (%)": "Tỷ lệ lãi EBIT",
    "net interest margin": "Net Interest Margin",  # kept as-is when VN name unavailable
    "npl (%)": "NPL (%)",
    "cir": "CIR",
    "casa ratio": "CASA (%)",
    "loan loss reserves/npls": "Tỷ lệ bao phủ nợ xấu",
    "cost/income ratio": "CIR",
    "dividend yield (%)": "Tỷ suất cổ tức",
    "debt to equity": "Tỷ số Nợ trên Vốn chủ sở hữu",
    "debt/equity": "Tỷ số Nợ vay trên Vốn chủ sở hữu",
    "current ratio": "Tỷ số thanh toán hiện hành (ngắn hạn)",
    "quick ratio": "Tỷ số thanh toán nhanh",
    "cash ratio": "Tỷ số thanh toán bằng tiền mặt",
    "asset turnover": "Vòng quay tổng tài sản (Hiệu suất sử dụng toàn bộ tài sản)",
    "fixed asset turnover": "Vòng quay tài sản cố định (Hiệu suất sử dụng tài sản cố định)",
    "roic": "ROIC",
}


def _canonical_name(raw_name: str) -> str:
    """Return the canonical (newest SDK) label for a ratio metric name.

    If the raw name (case-insensitively) matches a known old→new mapping,
    return the new name.  Otherwise return the original name unchanged.
    """
    folded = raw_name.strip().casefold()
    return _RATIO_EQUIVALENCES.get(folded, raw_name)


def _statements(frame):
    """Merge equivalent labels without mixing units or reviving withdrawn values."""
    if not frame.empty and "source" in frame and frame.source.dropna().nunique() > 1:
        raise ValueError("Financial statements must use one selected source")
    output = {}
    for kind in ("income", "balance", "cashflow", "ratio"):
        rows = []
        if frame.empty:
            output[kind] = pd.DataFrame()
            continue
        subset = frame[frame.metric.str.startswith(kind + ":")].copy()
        subset["canonical"] = subset.metric.map(
            lambda metric: ALIASES.get(metric.split(":", 1)[1], metric.split(":", 1)[1])
        )
        if kind == "ratio":
            subset["canonical"] = subset.canonical.map(_canonical_name)
        for name, group in subset.groupby("canonical"):
            if "unit" not in group:
                group = group.assign(unit="SOURCE_NATIVE_UNVERIFIED")
            period_values = {}
            for (end, period_type), values in group.groupby(["period_end", "period_type"]):
                # Newer knowledge supersedes old aliases, including explicit NULL revisions.
                for timestamp in ("available_at", "fetched_at"):
                    if timestamp in values and values[timestamp].notna().any():
                        values = values.loc[values[timestamp] == values[timestamp].max()]
                units = set(values.unit.fillna("SOURCE_NATIVE_UNVERIFIED"))
                numbers = [float(v) if pd.notna(v) else None for v in values.value]
                unit = next(iter(units)) if len(units) == 1 else "SOURCE_NATIVE_UNVERIFIED"
                value = (
                    numbers[0]
                    if len(units) == 1 and all(v == numbers[0] for v in numbers)
                    else None
                )
                label = (
                    f"{end.year}-Q{(end.month - 1) // 3 + 1}"
                    if period_type == "quarter"
                    else str(end.year)
                )
                period_values[label] = (end, value, unit)
            latest = max(period_values.values(), key=lambda entry: entry[0])
            row = {"item": name, "item_en": name, "unit": latest[2]}
            for label, (_, value, unit) in period_values.items():
                # A historical alias with another unit cannot inherit the newest unit.
                row[label] = value if unit == latest[2] and value is not None else float("nan")
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
    vietnam = ZoneInfo("Asia/Ho_Chi_Minh")
    cutoff = datetime.combine(as_of, time.max, vietnam).astimezone(UTC)
    price_as_of = as_of
    now_local = datetime.now(vietnam)
    if as_of == now_local.date():
        cutoff = min(cutoff, datetime.now(UTC))
        close_time = time.fromisoformat(settings.sources["price_complete_after_local"])
        if now_local.time() < close_time:
            price_as_of -= timedelta(days=1)
    scores = []
    stocks = []
    for item in symbols:
        symbol = item["symbol"]
        sector = item["sector"]
        source = settings.sources["provider_source"]
        prices = get_prices(
            symbol, as_of - timedelta(days=1100), price_as_of, known_at=cutoff, source=source
        )
        fundamentals = get_fundamentals(symbol, known_at=cutoff, source=source)
        news = get_news(
            [symbol], settings.data_requirements["news_window_days"], known_at=cutoff, source=source
        )
        statements = _statements(fundamentals)
        fa = score_fa(
            statements["income"],
            statements["balance"],
            statements["cashflow"],
            statements["ratio"],
            sector,
            settings.sector_metrics,
            settings.data_requirements,
        )
        quarter_count = (
            fundamentals.loc[fundamentals.period_type.eq("quarter"), "period_end"].nunique()
            if not fundamentals.empty
            else 0
        )
        latest_quarter = (
            fundamentals.loc[fundamentals.period_type.eq("quarter"), "period_end"].max()
            if not fundamentals.empty
            else None
        )
        stale_fundamentals = (
            latest_quarter is not None
            and pd.notna(latest_quarter)
            and (as_of - latest_quarter).days > settings.data_requirements["fundamental_stale_days"]
        )
        if quarter_count < settings.data_requirements["min_quarters"] or stale_fundamentals:
            fa = FAResult(
                None,
                "INSUFFICIENT_DATA",
                [
                    "Financial statements are stale"
                    if stale_fundamentals
                    else "Insufficient historical financial periods"
                ],
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
        if ns.breakdown.get("items_eligible", 0) < settings.data_requirements["min_news"]:
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
                    "source": "vnstock/" + source.upper(),
                    "adjustments_verified": bool(
                        not prices.empty and prices.adjustment_verified.all()
                    ),
                    "financial_publications_inferred": bool(
                        fundamentals.empty or fundamentals.publication_inferred.any()
                    ),
                    "financial_vintages_verified": bool(
                        not fundamentals.empty and fundamentals.vintage_verified.all()
                    ),
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
