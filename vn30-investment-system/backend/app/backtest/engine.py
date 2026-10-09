"""Execution simulation; never substitutes generated prices for missing history."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, time


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
    **kwargs,
) -> dict:
    """Signals produced after close execute at next observed session's open.

    All bars must contain date/time, symbol, raw VND open/close and volume.
    Both purchased shares and sale proceeds settle after two session advances.
    """
    if initial_cash <= 0 or lot_size <= 0 or settlement_sessions < 0:
        raise ValueError("Invalid cash, lot size or settlement period")
    if not math.isfinite(initial_cash) or any(
        not math.isfinite(rate) or not 0 <= rate < 1
        for rate in (buy_fee, sell_fee, sell_tax, slippage)
    ):
        raise ValueError("Fees, taxes and slippage must be finite fractions in [0,1)")
    if not 0 < max_volume_participation <= 1:
        raise ValueError("Volume participation must be in (0,1]")
    bars = defaultdict(dict)
    for row in prices:
        day = str(row.get("date", row.get("time")))[:10]
        date.fromisoformat(day)
        if any(
            not math.isfinite(float(row[key])) or float(row[key]) <= 0 for key in ("open", "close")
        ):
            raise ValueError("Prices must be positive raw VND")
        if row["symbol"] in bars[day]:
            raise ValueError("Duplicate symbol/session bar; select an audited source vintage")
        bars[day][row["symbol"]] = row
    sessions = sorted(bars)
    signals = {str(k)[:10]: list(dict.fromkeys(v)) for k, v in signals.items()}
    cash = float(initial_cash)
    holdings = defaultdict(list)
    pending_cash, trades, equity = [], [], []
    marks = {}
    target = None
    for i, day in enumerate(sessions):
        matured = [item for item in pending_cash if item[0] <= i]
        cash += sum(item[1] for item in matured)
        pending_cash = [item for item in pending_cash if item[0] > i]
        # Only information from a strictly earlier session can affect this open.
        if i and sessions[i - 1] in signals:
            target = signals[sessions[i - 1]]
        if target is not None:
            for symbol in list(holdings):
                row = bars[day].get(symbol)
                if symbol in target or not row or row.get("suspended"):
                    continue
                lots = holdings[symbol]
                settled = sum(q for q, at in lots if at <= i)
                limit = (
                    int(float(row.get("volume", 0)) * max_volume_participation / lot_size)
                    * lot_size
                )
                qty = min(settled, limit)
                if qty <= 0:
                    continue
                price = float(row["open"]) * (1 - slippage)
                proceeds = qty * price * (1 - sell_fee - sell_tax)
                if settlement_sessions == 0:
                    cash += proceeds
                else:
                    pending_cash.append((i + settlement_sessions, proceeds))
                remaining = qty
                new_lots = []
                for count, at in lots:
                    sold = min(count, remaining) if at <= i else 0
                    remaining -= sold
                    if count - sold:
                        new_lots.append((count - sold, at))
                holdings[symbol] = new_lots
                trades.append(
                    dict(
                        date=day,
                        symbol=symbol,
                        side="SELL",
                        quantity=qty,
                        price=price,
                        fees=qty * price * (sell_fee + sell_tax),
                    )
                )
            eligible = [
                s
                for s in target
                if not holdings[s] and s in bars[day] and not bars[day][s].get("suspended")
            ]
            budget = cash / max(len(eligible), 1)
            for symbol in eligible:
                row = bars[day][symbol]
                price = float(row["open"]) * (1 + slippage)
                qty = int(budget / (price * (1 + buy_fee)) / lot_size) * lot_size
                limit = (
                    int(float(row.get("volume", 0)) * max_volume_participation / lot_size)
                    * lot_size
                )
                qty = min(qty, limit)
                if qty <= 0:
                    continue
                cash -= qty * price * (1 + buy_fee)
                holdings[symbol].append((qty, i + settlement_sessions))
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
        nav = cash + sum(v for _, v in pending_cash)
        nav += sum(sum(q for q, _ in lots) * marks[s] for s, lots in holdings.items() if lots)
        equity.append(dict(date=day, equity=round(nav, 2), available_cash=round(cash, 2)))
    values = [initial_cash] + [x["equity"] for x in equity]
    returns = [b / a - 1 for a, b in zip(values, values[1:], strict=False)]
    peak, drawdown = initial_cash, 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    mean = sum(returns) / len(returns) if returns else 0
    variance = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
    total = values[-1] / initial_cash - 1
    return dict(
        status="COMPLETE",
        equity_curve=equity,
        trades=trades,
        metrics=dict(
            total_return=total,
            max_drawdown=drawdown,
            cagr=(values[-1] / initial_cash) ** (252 / len(sessions)) - 1 if sessions else None,
            sharpe=mean / math.sqrt(variance) * math.sqrt(252) if variance else None,
            trade_count=len(trades),
        ),
        limitations=[
            "Mô phỏng theo phiên; T+2 cho phép bán từ phiên T+2 mở cửa, "
            "chưa mô phỏng giờ thanh toán nội phiên."
        ],
    )


def run_backtest(request: dict, settings) -> dict:
    """Audit historical prerequisites before offering any performance numbers."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.app.db.models import (
        FundamentalValue,
        NewsItem,
        PriceBar,
        TradingSession,
        UniverseSnapshot,
    )
    from backend.app.db.session import initialize_database

    config = settings.backtest
    mode = request.get("mode", config["default_mode"])
    if mode not in config["modes"]:
        raise ValueError("Unknown backtest mode")
    start = date.fromisoformat(str(request.get("start_date", "2020-01-01")))
    end = date.fromisoformat(str(request.get("end_date", date.today().isoformat())))
    if start >= end:
        raise ValueError("start_date must precede end_date")
    symbols = request.get("symbols") or [s.symbol for s in settings.universe.selected]
    end_at = datetime.combine(end, time.max, tzinfo=UTC)
    reasons = []
    with Session(initialize_database()) as session:
        bars = session.scalars(
            select(PriceBar).where(
                PriceBar.symbol.in_(symbols),
                PriceBar.as_of_date >= start,
                PriceBar.as_of_date <= end,
            )
        ).all()
        for symbol in symbols:
            subset = [b for b in bars if b.symbol == symbol]
            if not subset:
                reasons.append(f"{symbol}: thiếu lịch sử giá trong kỳ yêu cầu")
            elif any(not b.adjustment_verified for b in subset):
                reasons.append(f"{symbol}: chưa xác minh giá điều chỉnh/corporate actions")
            fundamentals = session.scalars(
                select(FundamentalValue).where(
                    FundamentalValue.symbol == symbol, FundamentalValue.available_at <= end_at
                )
            ).all()
            if not any(f.vintage_verified and not f.publication_inferred for f in fundamentals):
                reasons.append(f"{symbol}: thiếu BCTC vintage với ngày công bố đã xác minh")
        snapshots = session.scalars(
            select(UniverseSnapshot).where(
                UniverseSnapshot.verified.is_(True), UniverseSnapshot.effective_from <= start
            )
        ).all()
        if not snapshots:
            reasons.append("Thiếu thành phần VN30 lịch sử đã xác minh tại đầu kỳ")
        if not session.scalar(select(TradingSession).where(TradingSession.session_date == start)):
            reasons.append("Thiếu lịch giao dịch chính thức để kiểm tra phiên và T+2")
        if mode == "S_full" and not session.scalar(
            select(NewsItem).where(
                NewsItem.timestamp_verified.is_(True),
                NewsItem.as_of_date >= start,
                NewsItem.as_of_date <= end,
            )
        ):
            reasons.append("S_full không khả dụng: thiếu tin lịch sử với timestamp đã xác minh")
    # Current records are not historical signals. Require an audited replay import.
    reasons.append(
        "Chưa có chuỗi tín hiệu lịch sử đã kiểm toán theo available_at; "
        "không dùng điểm hiện tại cho quá khứ"
    )
    return dict(
        status="UNAVAILABLE",
        mode=mode,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        reasons=reasons,
        metrics=None,
        equity_curve=[],
        trades=[],
        config_hash=settings.config_hash,
        limitations=["Không tạo số liệu backtest khi dữ liệu lịch sử chưa đủ xác minh."],
        required_data=[
            "giá VND và corporate actions xác minh",
            "BCTC point-in-time",
            "thành phần VN30 lịch sử",
            "lịch phiên",
            "tín hiệu point-in-time",
        ],
    )
