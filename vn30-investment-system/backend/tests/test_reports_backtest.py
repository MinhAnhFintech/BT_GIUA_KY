from datetime import date, timedelta

import pytest

from backend.app.backtest.engine import simulate
from backend.app.reports.pdf import create_report


def bars():
    return [
        dict(
            date=str(date(2026, 1, 5) + timedelta(days=i)),
            symbol="FPT",
            open=10_000 + i * 100,
            close=10_000 + i * 100,
            volume=1_000_000,
        )
        for i in range(6)
    ]


def test_next_session_and_lot_and_settlement():
    result = simulate(bars(), {"2026-01-05": ["FPT"], "2026-01-06": []}, initial_cash=10_000_000)
    assert result["trades"][0]["date"] == "2026-01-06"
    assert result["trades"][0]["quantity"] % 100 == 0
    assert result["trades"][1]["date"] == "2026-01-08"
    assert result["equity_curve"][3]["available_cash"] < 1_000_000
    assert result["equity_curve"][5]["available_cash"] > 9_000_000


def test_fee_reduces_flat_market_return():
    prices = [dict(row, open=10_000, close=10_000) for row in bars()]
    result = simulate(prices, {"2026-01-05": ["FPT"]}, initial_cash=10_000_000)
    assert result["metrics"]["total_return"] < 0
    assert all(t["fees"] > 0 for t in result["trades"])


def test_signal_same_day_cannot_execute():
    result = simulate(bars()[:1], {"2026-01-05": ["FPT"]}, initial_cash=10_000_000)
    assert result["trades"] == []


def test_ambiguous_duplicate_source_and_nonfinite_price_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        simulate(bars() + bars()[:1], {})
    with pytest.raises(ValueError, match="positive raw VND"):
        simulate([dict(bars()[0], open=float("nan"))], {})


def test_vietnamese_pdf():
    path = create_report(
        {
            "as_of_date": "2026-01-01",
            "secondary_ranking": [
                {"symbol": "FPT", "status": "INSUFFICIENT_DATA", "reasons": ["Thiếu dữ liệu"]}
            ],
            "details": {"FPT": {"reasons": ["Thiếu dữ liệu"], "source": "Nguồn công khai"}},
        }
    )
    try:
        assert path.read_bytes().startswith(b"%PDF")
        assert path.stat().st_size > 10_000
    finally:
        path.unlink()


def test_service_payload_pdf_has_charts_without_raw_price_dump(monkeypatch):
    from reportlab.graphics.shapes import Drawing
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    observed = []
    original = SimpleDocTemplate.build

    def inspect_build(self, flowables, *args, **kwargs):
        observed.extend(flowables)
        return original(self, flowables, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", inspect_build)
    payload = {
        "as_of_date": "2026-01-01",
        "scoring_version": "test-1",
        "stocks": [
            {
                "symbol": "FPT",
                "sector": "technology",
                "status": "COMPLETE",
                "breakdown": {
                    "FA": {
                        "score": 70,
                        "weight": 0.45,
                        "detail": {
                            "roe": {
                                "raw": 0.2,
                                "score": 70,
                                "weight": 1,
                                "weighted_contribution": 70,
                            }
                        },
                    }
                },
                "prices": [
                    {
                        "time": str(i),
                        "close": 100 + i,
                        "ma20": 90 + i,
                        "raw_marker": "SHOULD_NOT_DUMP_RAW",
                    }
                    for i in range(1000)
                ],
                "provenance": {"price_ids": list(range(1000))},
            }
        ],
    }
    path = create_report(payload)
    try:
        text = " ".join(item.text for item in observed if isinstance(item, Paragraph))
        assert "SHOULD_NOT_DUMP_RAW" not in text
        assert "1000 bản ghi" in text
        assert sum(isinstance(item, Drawing) for item in observed) == 2
        assert path.stat().st_size < 100_000
    finally:
        path.unlink()
