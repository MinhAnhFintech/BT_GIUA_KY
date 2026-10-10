"""Audited point-in-time replay and next-session execution; no fabricated history."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo


def _metrics(equity, trades, initial_cash, annual_sessions, risk_free_annual):
    values = [float(initial_cash)] + [row["equity"] for row in equity]
    returns = [b / a - 1 for a, b in zip(values, values[1:], strict=False)]
    daily_rf = (1 + risk_free_annual) ** (1 / annual_sessions) - 1
    excess = [value - daily_rf for value in returns]
    mean = sum(excess) / len(excess) if excess else 0
    variance = sum((r - mean) ** 2 for r in excess) / max(len(excess) - 1, 1)
    downside = sum(min(r, 0) ** 2 for r in excess) / max(len(excess), 1)
    peak, max_drawdown = initial_cash, 0.0
    for row in equity:
        peak = max(peak, row["equity"])
        row["drawdown"] = row["equity"] / peak - 1
        max_drawdown = min(max_drawdown, row["drawdown"])
    cagr = (values[-1] / initial_cash) ** (annual_sessions / len(returns)) - 1 if returns else None
    sells = [trade for trade in trades if trade["side"] == "SELL"]
    average_nav = sum(values) / len(values)
    return {
        "total_return": values[-1] / initial_cash - 1,
        "max_drawdown": max_drawdown,
        "cagr": cagr,
        "sharpe": mean / math.sqrt(variance) * math.sqrt(annual_sessions) if variance else None,
        "sortino": mean / math.sqrt(downside) * math.sqrt(annual_sessions) if downside else None,
        "calmar": cagr / -max_drawdown if cagr is not None and max_drawdown < 0 else None,
        "hit_rate": sum(t["realized_pnl"] > 0 for t in sells) / len(sells) if sells else None,
        "turnover": sum(t["quantity"] * t["price"] for t in trades) / average_nav,
        "trade_count": len(trades),
        "annual_sessions": annual_sessions,
        "risk_free_annual": risk_free_annual,
    }


def simulate(
    prices: list[dict],
    signals: dict,
    initial_cash: float = 1_000_000_000,
    lot_size: int = 100,
    settlement_sessions: int = 2,
    buy_fee: float = 0.0015,
    sell_fee: float = 0.0015,
    sell_tax: float = 0.001,
    slippage: float = 0.001,
    max_volume_participation: float = 0.01,
    annual_sessions: int = 252,
    risk_free_annual: float = 0.0,
    execution: str = "next_session_open",
    calendar: list[str] | None = None,
    corporate_actions: list[dict] | None = None,
    price_limit: float | None = None,
    limit_tolerance: float = 0.0,
) -> dict:
    """Freeze equal-weight target quantities at each signal's following open.

    Rebalance retained stocks too. Unsettled shares/proceeds delay orders, which
    retry toward the same target until the next signal. Participation uses the
    previous official session's volume, never the current session's future volume.
    Prices are raw VND; analytical adjusted closes are not execution prices.
    """
    if (
        not math.isfinite(initial_cash)
        or initial_cash <= 0
        or not isinstance(lot_size, int)
        or lot_size <= 0
        or not isinstance(settlement_sessions, int)
        or settlement_sessions < 0
    ):
        raise ValueError("Invalid cash, lot size or settlement period")
    rates = (buy_fee, sell_fee, sell_tax, slippage)
    if any(not math.isfinite(rate) or not 0 <= rate < 1 for rate in rates):
        raise ValueError("Fees, taxes and slippage must be finite fractions in [0,1)")
    if sell_fee + sell_tax >= 1:
        raise ValueError("Combined sale fee and tax must be less than 1")
    if not math.isfinite(max_volume_participation) or not 0 < max_volume_participation <= 1:
        raise ValueError("Volume participation must be in (0,1]")
    if not isinstance(annual_sessions, int) or annual_sessions <= 0:
        raise ValueError("Annual sessions must be a positive integer")
    if not math.isfinite(risk_free_annual) or risk_free_annual <= -1:
        raise ValueError("Risk-free rate must be finite and greater than -1")
    if execution != "next_session_open":
        raise ValueError("Only next_session_open execution is supported")
    if price_limit is not None and (not math.isfinite(price_limit) or not 0 < price_limit < 1):
        raise ValueError("Invalid daily price limit")
    if not math.isfinite(limit_tolerance) or not 0 <= limit_tolerance < 1:
        raise ValueError("Invalid price limit tolerance")
    bars = defaultdict(dict)
    for row in prices:
        day = str(row.get("date", row.get("time")))[:10]
        date.fromisoformat(day)
        if any(
            not math.isfinite(float(row[key])) or float(row[key]) <= 0 for key in ("open", "close")
        ):
            raise ValueError("Prices must be positive raw VND")
        volume = float(row.get("volume", 0))
        if not math.isfinite(volume) or volume < 0:
            raise ValueError("Volume must be finite and nonnegative")
        if row["symbol"] in bars[day]:
            raise ValueError("Duplicate symbol/session bar; select an audited source vintage")
        bars[day][row["symbol"]] = row
    sessions = (
        sorted(set(str(day)[:10] for day in calendar)) if calendar is not None else sorted(bars)
    )
    if any(day not in sessions for day in bars):
        raise ValueError("Price bar outside official trading calendar")
    signals = {str(day)[:10]: list(dict.fromkeys(symbols)) for day, symbols in signals.items()}
    if any(day not in sessions for day in signals):
        raise ValueError("Signal must be produced after an official trading session")
    actions = defaultdict(list)
    for action in corporate_actions or []:
        kind = action["action_type"]
        if kind not in {"split", "stock_dividend", "cash_dividend"}:
            raise ValueError(f"Unsupported corporate action: {kind}")
        if kind in {"split", "stock_dividend"} and (
            action.get("factor") is None
            or not math.isfinite(float(action["factor"]))
            or float(action["factor"]) <= 0
        ):
            raise ValueError("Corporate action factor must be finite and positive")
        if kind == "cash_dividend" and (
            not action.get("payable_date")
            or action.get("cash_per_share_vnd") is None
            or not math.isfinite(float(action["cash_per_share_vnd"]))
            or float(action["cash_per_share_vnd"]) < 0
            or str(action["payable_date"])[:10] < str(action["ex_date"])[:10]
        ):
            raise ValueError("Cash dividend requires nonnegative VND and a verified payment date")
        actions[str(action["ex_date"])[:10]].append(action)
    cash = float(initial_cash)
    holdings = defaultdict(list)  # lots: quantity, settlement index, unit cost including buy fee
    pending_cash, trades, equity = [], [], []
    marks, target_quantities = {}, None
    for i, day in enumerate(sessions):
        cash += sum(amount for at, amount in pending_cash if at <= i)
        pending_cash = [(at, amount) for at, amount in pending_cash if at > i]
        references = dict(marks)
        for action in actions[day]:
            symbol = action["symbol"]
            if action["action_type"] in {"split", "stock_dividend"}:
                factor = float(action["factor"])
                if any(
                    not math.isclose(q * factor, round(q * factor)) for q, _, _ in holdings[symbol]
                ):
                    raise ValueError("Fractional split entitlement requires a cash-in-lieu record")
                holdings[symbol] = [
                    (round(q * factor), at, cost / factor) for q, at, cost in holdings[symbol]
                ]
                if symbol in marks:
                    marks[symbol] /= factor
                    references[symbol] /= factor
                if target_quantities is not None and symbol in target_quantities:
                    target_quantities[symbol] = round(target_quantities[symbol] * factor)
            else:
                dividend = float(action["cash_per_share_vnd"])
                amount = sum(q for q, _, _ in holdings[symbol]) * dividend
                payment = str(action["payable_date"])[:10]
                due = next(
                    (j for j, session in enumerate(sessions) if session >= payment),
                    len(sessions) + 1,
                )
                if due <= i:
                    cash += amount
                elif amount:
                    pending_cash.append((due, amount))
                if symbol in marks:
                    marks[symbol] -= dividend
                    references[symbol] -= dividend
        if i and sessions[i - 1] in signals:
            target = signals[sessions[i - 1]]
            opening_nav = cash + sum(amount for _, amount in pending_cash)
            opening_nav += sum(
                sum(q for q, _, _ in lots)
                * float(bars[day].get(s, {}).get("open", marks.get(s, 0)))
                for s, lots in holdings.items()
            )
            allocation = opening_nav / max(len(target), 1)
            target_quantities = {}
            for symbol in target:
                price = float(bars[day].get(symbol, {}).get("open", marks.get(symbol, 0)))
                if price > 0:
                    target_quantities[symbol] = (
                        int(allocation / (price * (1 + slippage) * (1 + buy_fee)) / lot_size)
                        * lot_size
                    )
        if target_quantities is not None:
            participation_used = defaultdict(int)

            def capacity(
                symbol,
                side,
                current_day=day,
                index=i,
                prior_marks=references,
                used=participation_used,
            ):
                row = bars[current_day].get(symbol)
                if not row or row.get("suspended") or index == 0:
                    return 0
                if (
                    row.get("limit_up")
                    and side == "BUY"
                    or row.get("limit_down")
                    and side == "SELL"
                ):
                    return 0
                reference = prior_marks.get(symbol)
                if price_limit is not None and reference and reference > 0:
                    change = float(row["open"]) / reference - 1
                    if abs(change) > price_limit + limit_tolerance:
                        raise ValueError(
                            "Open breaches verified daily limit/corporate-action reference"
                        )
                    if side == "BUY" and change >= price_limit - limit_tolerance:
                        return 0
                    if side == "SELL" and change <= -price_limit + limit_tolerance:
                        return 0
                previous_volume = float(bars[sessions[index - 1]].get(symbol, {}).get("volume", 0))
                return max(
                    0,
                    int(previous_volume * max_volume_participation / lot_size) * lot_size
                    - used[symbol],
                )

            for symbol in list(holdings):
                lots = holdings[symbol]
                count = sum(q for q, _, _ in lots)
                excess = count - target_quantities.get(symbol, 0)
                settled = sum(q for q, at, _ in lots if at <= i)
                qty = int(min(excess, settled, capacity(symbol, "SELL")) / lot_size) * lot_size
                if qty <= 0:
                    continue
                price = float(bars[day][symbol]["open"]) * (1 - slippage)
                proceeds = qty * price * (1 - sell_fee - sell_tax)
                if settlement_sessions == 0:
                    cash += proceeds
                else:
                    pending_cash.append((i + settlement_sessions, proceeds))
                remaining, basis, new_lots = qty, 0.0, []
                for count, at, cost in lots:
                    sold = min(count, remaining) if at <= i else 0
                    remaining -= sold
                    basis += sold * cost
                    if count > sold:
                        new_lots.append((count - sold, at, cost))
                holdings[symbol] = new_lots
                participation_used[symbol] += qty
                trades.append(
                    dict(
                        date=day,
                        symbol=symbol,
                        side="SELL",
                        quantity=qty,
                        price=price,
                        fees=qty * price * (sell_fee + sell_tax),
                        realized_pnl=proceeds - basis,
                    )
                )
            desired = []
            for symbol, target_qty in target_quantities.items():
                held = sum(q for q, _, _ in holdings[symbol])
                qty = int(min(target_qty - held, capacity(symbol, "BUY")) / lot_size) * lot_size
                if qty > 0:
                    price = float(bars[day][symbol]["open"]) * (1 + slippage)
                    desired.append((symbol, qty, price))
            cost = sum(qty * price * (1 + buy_fee) for _, qty, price in desired)
            allocation_scale = min(1.0, cash / cost) if cost else 0
            for symbol, qty, price in desired:
                qty = int(qty * allocation_scale / lot_size) * lot_size
                qty = min(qty, int(max(cash, 0) / (price * (1 + buy_fee)) / lot_size) * lot_size)
                if qty <= 0:
                    continue
                cash -= qty * price * (1 + buy_fee)
                holdings[symbol].append((qty, i + settlement_sessions, price * (1 + buy_fee)))
                trades.append(
                    dict(
                        date=day,
                        symbol=symbol,
                        side="BUY",
                        quantity=qty,
                        price=price,
                        fees=qty * price * buy_fee,
                    )
                )
        marks.update({s: float(row["close"]) for s, row in bars[day].items()})
        nav = cash + sum(amount for _, amount in pending_cash)
        nav += sum(sum(q for q, _, _ in lots) * marks[s] for s, lots in holdings.items() if lots)
        equity.append(dict(date=day, equity=round(nav, 2), available_cash=round(cash, 2)))
    return dict(
        status="COMPLETE",
        equity_curve=equity,
        trades=trades,
        metrics=_metrics(equity, trades, initial_cash, annual_sessions, risk_free_annual),
        limitations=[
            "T+2 được tính theo phiên chính thức; mô phỏng quyền bán từ mở cửa phiên T+2, "
            "chưa mô phỏng giờ thanh toán nội phiên.",
            "Thanh khoản mở cửa dùng khối lượng phiên trước làm trần tham gia; "
            "không có dữ liệu sổ lệnh hoặc khối lượng đấu giá mở cửa.",
        ],
    )


def _close_at(day):
    return datetime.combine(day, time(16), ZoneInfo("Asia/Ho_Chi_Minh")).astimezone(UTC)


def _bar_dict(bar):
    return dict(
        id=bar.id,
        date=bar.as_of_date.isoformat(),
        time=bar.as_of_date,
        symbol=bar.symbol,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=bar.volume,
        suspended=bar.suspended,
    )


def _latest(records, key):
    result = {}
    for row in sorted(records, key=lambda r: (r.available_at, r.id)):
        result[key(row)] = row
    return list(result.values())


def _point_in_time_score(
    symbol, sector, day, bars, fundamentals, news, settings, weights, news_associations=None
):
    """Replay verified records known at this close, without current analysis results."""
    import pandas as pd

    from backend.app.analysis.fa import score_fa
    from backend.app.analysis.news import score_news
    from backend.app.analysis.service import _statements
    from backend.app.analysis.ta import score_ta

    cutoff = _close_at(day)
    px = _latest(
        [
            b
            for b in bars
            if b.symbol == symbol
            and b.as_of_date <= day
            and b.available_at <= cutoff
            and b.adjustment_verified
            and b.price_unit == "VND"
        ],
        lambda b: b.as_of_date,
    )
    px.sort(key=lambda b: b.as_of_date)
    minimum = settings.data_requirements["min_price_sessions"]
    if len(px) < minimum:
        return None, f"{symbol}: chỉ có {len(px)}/{minimum} phiên giá vintage đã xác minh"
    frame = pd.DataFrame([_bar_dict(b) for b in px])
    ratios = pd.Series([float(b.adjusted_close or b.close) / float(b.close) for b in px])
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column] * ratios
    ta = score_ta(frame, settings.scoring)
    fs = _latest(
        [
            f
            for f in fundamentals
            if f.symbol == symbol
            and f.period_end <= day
            and f.available_at <= cutoff
            and f.published_at <= cutoff
            and f.vintage_verified
            and not f.publication_inferred
        ],
        lambda f: (f.period_end, f.period_type, f.metric),
    )
    quarter_count = len({f.period_end for f in fs if f.period_type == "quarter"})
    if quarter_count < settings.data_requirements["min_quarters"]:
        return None, f"{symbol}: thiếu số quý BCTC point-in-time tại {day}"
    if not fs or (day - max(f.period_end for f in fs)).days > settings.data_requirements.get(
        "fundamental_stale_days", 180
    ):
        return None, f"{symbol}: BCTC point-in-time quá cũ tại {day}"
    fframe = pd.DataFrame(
        [
            dict(
                id=f.id,
                metric=f.metric,
                period_end=f.period_end,
                period_type=f.period_type,
                value=float(f.value) if f.value is not None else None,
                unit=f.unit,
            )
            for f in fs
        ]
    )
    statements = _statements(fframe)
    fa = score_fa(
        statements["income"],
        statements["balance"],
        statements["cashflow"],
        statements["ratio"],
        sector,
        settings.sector_metrics,
        settings.data_requirements,
    )
    components = {"FA": fa.score, "TA": ta.score}
    relevant = []
    if "NEWS" in weights:
        earliest = cutoff - timedelta(days=settings.data_requirements["news_window_days"])
        associations = news_associations or []
        associated_ids = {a.unit_metadata.get("news_id") for a in associations}
        eligible_ids = {
            a.unit_metadata.get("news_id")
            for a in associations
            if a.symbol == symbol and a.fetched_at <= cutoff
        }
        relevant = [
            n
            for n in news
            if symbol in n.symbols
            and n.timestamp_verified
            and earliest <= n.published_at <= cutoff
            and n.available_at <= cutoff
            and (n.id in eligible_ids or (n.id not in associated_ids and len(n.symbols) == 1))
        ]
        if len(relevant) < settings.data_requirements["min_news"]:
            return None, f"{symbol}: thiếu tin timestamp đã xác minh tại {day}"
        ns = score_news(
            pd.DataFrame(
                [dict(title=n.title, url=n.url, published_at=n.published_at) for n in relevant]
            ),
            settings.scoring,
            cutoff,
        )
        if ns.breakdown.get("items_eligible", 0) < settings.data_requirements["min_news"]:
            return None, f"{symbol}: thiếu tin hợp lệ sau phân loại/dedup tại {day}"
        components["NEWS"] = ns.score
    if any(components.get(component) is None for component in weights):
        missing = [name for name in weights if components.get(name) is None]
        return None, f"{symbol}: không đủ metric {', '.join(missing)} tại {day}"
    score = sum(components[component] * weight for component, weight in weights.items())
    return dict(
        symbol=symbol,
        score=score,
        components=components,
        price_ids=[b.id for b in px],
        fundamental_ids=[f.id for f in fs],
        news_ids=[n.id for n in relevant],
        known_at=cutoff.isoformat(),
    ), None


def run_backtest(request: dict, settings) -> dict:
    """Persist every audit and replay only complete, verified historical inputs."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.app.db.models import (
        BacktestRun,
        CorporateAction,
        FundamentalValue,
        NewsItem,
        PriceBar,
        SourceFetch,
        Stock,
        TradingSession,
        UniverseMember,
        UniverseSnapshot,
    )
    from backend.app.db.session import initialize_database

    config = dict(settings.backtest)
    mode = request.get("mode") or config["default_mode"]
    if mode not in config["modes"]:
        raise ValueError("Unknown backtest mode")
    start = date.fromisoformat(str(request.get("start_date") or "2020-01-01"))
    end = date.fromisoformat(
        str(request.get("end_date") or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date())
    )
    if start >= end:
        raise ValueError("start_date must precede end_date")
    allowed = {
        "mode",
        "start_date",
        "end_date",
        "symbols",
        "top_n",
        "rebalance",
        "buy_fee",
        "sell_fee",
        "sell_tax",
        "slippage",
    }
    if set(request) - allowed:
        raise ValueError(
            "Unsupported backtest parameters: " + ", ".join(sorted(set(request) - allowed))
        )
    for key in ("top_n", "rebalance", "buy_fee", "sell_fee", "sell_tax", "slippage"):
        if request.get(key) is not None:
            config[key] = request[key]
    symbols = list(
        dict.fromkeys(request.get("symbols") or [s.symbol for s in settings.universe.selected])
    )
    if not 1 <= config["top_n"] <= len(symbols):
        raise ValueError("top_n exceeds selected universe")
    if config["rebalance"] not in {"monthly", "quarterly"}:
        raise ValueError("Unknown rebalance frequency")
    sim_config = dict(
        initial_cash=config["initial_cash_vnd"],
        lot_size=config["lot_size"],
        settlement_sessions=config["settlement_sessions"],
        buy_fee=config["buy_fee"],
        sell_fee=config["sell_fee"],
        sell_tax=config["sell_tax"],
        slippage=config["slippage"],
        max_volume_participation=config["max_volume_participation"],
        annual_sessions=config["annual_sessions"],
        risk_free_annual=config["risk_free_annual"],
        execution=config["execution"],
    )
    simulate([], {}, **sim_config)
    source = settings.sources.get("provider_source", "VCI")
    source = source if source.startswith("vnstock/") else "vnstock/" + source.upper()
    reasons, replay, signals = [], [], {}
    engine = initialize_database()
    with Session(engine) as session:
        bars = session.scalars(
            select(PriceBar).where(
                PriceBar.symbol.in_(symbols),
                PriceBar.source == source,
                PriceBar.as_of_date >= start - timedelta(days=1100),
                PriceBar.as_of_date <= end,
            )
        ).all()
        fundamentals = session.scalars(
            select(FundamentalValue).where(
                FundamentalValue.symbol.in_(symbols),
                FundamentalValue.source == source,
                FundamentalValue.available_at <= _close_at(end),
            )
        ).all()
        news = session.scalars(
            select(NewsItem).where(
                NewsItem.available_at <= _close_at(end),
                NewsItem.published_at
                >= _close_at(start)
                - timedelta(days=settings.data_requirements["news_window_days"]),
            )
        ).all()
        associations = session.scalars(
            select(SourceFetch).where(
                SourceFetch.kind == "news_symbol",
                SourceFetch.source == source,
                SourceFetch.symbol.in_(symbols),
            )
        ).all()
        associated_ids = {a.unit_metadata.get("news_id") for a in associations}
        news = [
            n
            for n in news
            if set(n.symbols) & set(symbols) and (n.id in associated_ids or n.source == source)
        ]
        calendar = session.scalars(
            select(TradingSession)
            .where(
                TradingSession.exchange == "HOSE",
                TradingSession.is_open.is_(True),
                TradingSession.session_date >= start,
                TradingSession.session_date <= end,
            )
            .order_by(TradingSession.session_date)
        ).all()
        snapshots = session.scalars(
            select(UniverseSnapshot).where(
                UniverseSnapshot.index_name == "VN30",
                UniverseSnapshot.verified.is_(True),
                UniverseSnapshot.effective_from <= end,
            )
        ).all()
        members = session.scalars(
            select(UniverseMember).where(UniverseMember.snapshot_id.in_([u.id for u in snapshots]))
        ).all()
        actions = session.scalars(
            select(CorporateAction).where(
                CorporateAction.symbol.in_(symbols),
                CorporateAction.ex_date >= start,
                CorporateAction.ex_date <= end,
            )
        ).all()
        sectors = dict(
            session.execute(
                select(Stock.symbol, Stock.sector).where(Stock.symbol.in_(symbols))
            ).all()
        )
        fallback_sectors = {s.symbol: s.sector for s in settings.universe.selected}
        input_ids = dict(
            price_bars=sorted(b.id for b in bars),
            fundamental_values=sorted(f.id for f in fundamentals),
            news_items=sorted(n.id for n in news if set(n.symbols) & set(symbols)),
            news_associations=sorted(a.id for a in associations),
            universe_snapshots=sorted(u.id for u in snapshots),
            corporate_actions=sorted(a.id for a in actions),
            trading_sessions=[f"{c.exchange}:{c.session_date}" for c in calendar],
        )
        days = [c.session_date for c in calendar]
        for symbol in symbols:
            subset = [b for b in bars if b.symbol == symbol and b.as_of_date >= start]
            if not subset:
                reasons.append(f"{symbol}: thiếu lịch sử giá {source} trong kỳ yêu cầu")
            elif any(not b.adjustment_verified or b.price_unit != "VND" for b in subset):
                reasons.append(f"{symbol}: chưa xác minh giá VND điều chỉnh/corporate actions")
            if not any(
                f.symbol == symbol and f.vintage_verified and not f.publication_inferred
                for f in fundamentals
            ):
                reasons.append(f"{symbol}: thiếu BCTC vintage với ngày công bố đã xác minh")
        if not days:
            reasons.append("Thiếu lịch phiên HOSE chính thức để kiểm tra phiên và T+2")
        elif any(b.as_of_date >= start and b.as_of_date not in days for b in bars):
            reasons.append("Giá có ngày ngoài lịch phiên HOSE đã nhập")
        if not snapshots:
            reasons.append("Thiếu thành phần VN30 lịch sử đã xác minh")
        if any(not a.verified for a in actions):
            reasons.append("Corporate action trong kỳ chưa xác minh")
        if mode == "S_full" and not any(
            n.timestamp_verified and set(n.symbols) & set(symbols) for n in news
        ):
            reasons.append("S_full không khả dụng: thiếu tin lịch sử với timestamp đã xác minh")
        if not reasons:
            selected_bars = _latest(
                [
                    b
                    for b in bars
                    if b.as_of_date >= start and b.available_at <= _close_at(b.as_of_date)
                ],
                lambda b: (b.symbol, b.as_of_date),
            )
            for symbol in symbols:
                observed = {b.as_of_date for b in selected_bars if b.symbol == symbol}
                missing = set(days) - observed
                if missing:
                    reasons.append(
                        f"{symbol}: thiếu {len(missing)} bar vintage trên lịch chính thức"
                    )
            signal_days = [days[0]]

            def period(day):
                return (
                    day.year,
                    day.month if config["rebalance"] == "monthly" else (day.month - 1) // 3,
                )

            signal_days += [
                day
                for day, next_day in zip(days, days[1:], strict=False)
                if period(day) != period(next_day) and day != days[0]
            ]
            for day in signal_days:
                eligible_snapshot = [
                    u
                    for u in snapshots
                    if u.effective_from <= day
                    and (u.effective_to is None or day <= u.effective_to)
                    and u.announced_at <= _close_at(day)
                ]
                if not eligible_snapshot:
                    reasons.append(f"{day}: thiếu thành phần VN30 point-in-time")
                    continue
                snapshot = max(eligible_snapshot, key=lambda u: (u.effective_from, u.announced_at))
                eligible = {m.symbol for m in members if m.snapshot_id == snapshot.id}
                scored = []
                for symbol in symbols:
                    if symbol not in eligible:
                        continue
                    sector = fallback_sectors.get(symbol, sectors.get(symbol))
                    if sector not in settings.sector_metrics["sectors"]:
                        reasons.append(f"{symbol}: thiếu cấu hình ngành tại {day}")
                        continue
                    score, reason = _point_in_time_score(
                        symbol,
                        sector,
                        day,
                        bars,
                        fundamentals,
                        news,
                        settings,
                        config["modes"][mode],
                        associations,
                    )
                    if reason:
                        reasons.append(reason)
                    else:
                        scored.append(score)
                if len(scored) < config["top_n"]:
                    reasons.append(f"{day}: không đủ {config['top_n']} mã hợp lệ để chọn Top N")
                ranked = sorted(scored, key=lambda row: (-row["score"], row["symbol"]))
                signals[day.isoformat()] = [row["symbol"] for row in ranked[: config["top_n"]]]
                replay.append(dict(date=day.isoformat(), snapshot_id=snapshot.id, ranking=ranked))

        def fingerprint(record):
            return {
                column.name: getattr(record, column.name) for column in record.__table__.columns
            }

        data_identity = dict(
            inputs=input_ids,
            prices=[fingerprint(b) for b in sorted(bars, key=lambda b: b.id)],
            financials=[fingerprint(f) for f in sorted(fundamentals, key=lambda f: f.id)],
            news=[fingerprint(n) for n in sorted(news, key=lambda n: n.id)],
            news_associations=[fingerprint(a) for a in sorted(associations, key=lambda a: a.id)],
            actions=[fingerprint(a) for a in sorted(actions, key=lambda a: a.id)],
            calendar=[fingerprint(c) for c in calendar],
            snapshots=[fingerprint(u) for u in sorted(snapshots, key=lambda u: u.id)],
            membership=[
                fingerprint(m) for m in sorted(members, key=lambda m: (m.snapshot_id, m.symbol))
            ],
        )
        data_hash = hashlib.sha256(
            json.dumps(data_identity, sort_keys=True, default=str).encode()
        ).hexdigest()
        snapshot_config = dict(
            settings=settings.model_dump(mode="json"),
            effective_backtest=config,
            request=dict(mode=mode, symbols=symbols, start_date=str(start), end_date=str(end)),
        )
        config_hash = hashlib.sha256(
            json.dumps(snapshot_config, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        result = dict(
            status="UNAVAILABLE",
            mode=mode,
            start_date=str(start),
            end_date=str(end),
            reasons=list(dict.fromkeys(reasons)),
            metrics=None,
            equity_curve=[],
            trades=[],
            config_hash=config_hash,
            data_hash=data_hash,
            seed=config["seed"],
            config_snapshot=snapshot_config,
            input_record_ids=input_ids,
            signal_replay=replay,
            limitations=["Không tạo số liệu backtest khi dữ liệu lịch sử chưa đủ xác minh."],
        )
        if not reasons:
            raw = [
                _bar_dict(b) for b in sorted(selected_bars, key=lambda b: (b.as_of_date, b.symbol))
            ]
            action_dicts = [
                dict(
                    symbol=a.symbol,
                    ex_date=str(a.ex_date),
                    payable_date=str(a.payable_date) if a.payable_date else None,
                    action_type=a.action_type,
                    factor=float(a.factor) if a.factor is not None else None,
                    cash_per_share_vnd=float(a.cash_per_share_vnd)
                    if a.cash_per_share_vnd is not None
                    else None,
                )
                for a in actions
            ]
            sim_config.update(
                calendar=[str(day) for day in days],
                corporate_actions=action_dicts,
                price_limit=settings.data_requirements["quality"]["hose_daily_limit"],
                limit_tolerance=settings.data_requirements["quality"]["price_jump_tolerance"],
            )
            try:
                simulated = simulate(raw, signals, **sim_config)
                result.update(simulated, reasons=[])
                result["benchmarks"] = {}
                if "equal_weight_buy_hold" in config["benchmarks"]:
                    initial_members = [row["symbol"] for row in replay[0]["ranking"]]
                    baseline = simulate(raw, {str(days[0]): initial_members}, **sim_config)
                    result["benchmarks"]["equal_weight_buy_hold"] = {
                        "status": "COMPLETE",
                        "metrics": baseline["metrics"],
                        "equity_curve": baseline["equity_curve"],
                    }
                if "random_top_n" in config["benchmarks"]:
                    rng, random_returns = random.Random(config["seed"]), []
                    for _ in range(config["random_baseline_runs"]):
                        random_signals = {
                            period["date"]: rng.sample(
                                [row["symbol"] for row in period["ranking"]], config["top_n"]
                            )
                            for period in replay
                        }
                        random_returns.append(
                            simulate(raw, random_signals, **sim_config)["metrics"]["total_return"]
                        )
                    result["benchmarks"]["random_top_n"] = dict(
                        status="COMPLETE",
                        seed=config["seed"],
                        runs=len(random_returns),
                        mean_total_return=sum(random_returns) / len(random_returns),
                        total_returns=random_returns,
                    )
                for name in ("VN30", "VNINDEX"):
                    if name in config["benchmarks"]:
                        result["benchmarks"][name] = dict(
                            status="UNAVAILABLE", reason="Chưa nhập giá chỉ số lịch sử đã xác minh"
                        )
                result["limitations"].append(
                    "Replay dùng trọng số cố định; chưa thực hiện tối ưu walk-forward "
                    "hoặc kiểm định "
                    "IC/tertiles/sensitivity. Không diễn giải kết quả là bằng chứng thống kê."
                )
                if len(symbols) < config["small_universe_warning_below"]:
                    result["limitations"].append(
                        "Universe nhỏ; kết quả có độ nhạy cao với lựa chọn mã."
                    )
                if len(replay) < config["minimum_periods_for_inference"]:
                    result["limitations"].append("Số kỳ tái cân bằng chưa đủ để suy luận thống kê.")
            except ValueError as exc:
                result.update(
                    status="UNAVAILABLE",
                    reasons=[str(exc)],
                    metrics=None,
                    equity_curve=[],
                    trades=[],
                )
        run_id = str(uuid4())
        result["backtest_run_id"] = run_id
        session.add(
            BacktestRun(
                id=run_id,
                created_at=datetime.now(UTC),
                mode=mode,
                seed=config["seed"],
                config_hash=config_hash,
                data_hash=data_hash,
                config_snapshot=snapshot_config,
                input_record_ids=input_ids,
                results=result,
                limitations=result["limitations"],
            )
        )
        session.commit()
        return result
