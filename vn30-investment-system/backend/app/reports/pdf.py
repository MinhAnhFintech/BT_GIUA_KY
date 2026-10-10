"""Generate auditable Vietnamese PDF reports from an immutable analysis payload."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from backend.app.core.config import PROJECT_ROOT


def create_report(payload: dict, kind: str = "ranking", symbol: str | None = None) -> Path:
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    fonts = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font = next((p for p in fonts if p.exists()), None)
    if font is None:
        raise RuntimeError("Cần font Arial hoặc DejaVuSans để xuất PDF tiếng Việt.")
    pdfmetrics.registerFont(TTFont("Vietnamese", str(font)))
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "Vietnamese"
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 12
    folder = PROJECT_ROOT / "reports_out"
    folder.mkdir(exist_ok=True)
    path = folder / f"{kind}-{uuid4().hex}.pdf"
    story = []
    created_at = datetime.now(UTC)

    def para(value, style="Normal"):
        story.append(Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style]))
        story.append(Spacer(1, 0.15 * cm))

    def number(value):
        if value is None:
            return "—"
        if isinstance(value, (int, float)) and math.isfinite(value):
            return f"{value:,.3f}".rstrip("0").rstrip(".")
        return str(value)

    def table(rows, widths):
        cells = [[Paragraph(escape(str(cell)), styles["Normal"]) for cell in row] for row in rows]
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([result, Spacer(1, 0.25 * cm)])

    def source_caption(records, unit_key="unit"):
        records = [row for row in records if isinstance(row, dict)]
        units = sorted({str(row[unit_key]) for row in records if row.get(unit_key)})
        sources = sorted(
            {
                str(row.get("source_url") or row.get("source"))
                for row in records
                if row.get("source_url") or row.get("source")
            }
        )
        fetched = sorted({str(row["fetched_at"]) for row in records if row.get("fetched_at")})
        fetched_label = (
            " → ".join([fetched[0], fetched[-1]])
            if len(fetched) > 1
            else (fetched[0] if fetched else "Chưa ghi nhận")
        )
        para(
            f"Đơn vị: {', '.join(units) or 'Chưa xác minh'}; "
            f"nguồn: {'; '.join(sources) or 'Chưa có nguồn'}; "
            f"lấy lúc: {fetched_label}"
        )

    def price_chart(records):
        records = records[-120:]
        if len(records) < 2:
            return
        keys = ["close"] + [
            key
            for key in ("ma20", "ma50", "ma200")
            if any(row.get(key) is not None for row in records)
        ]
        values = [
            float(row[key])
            for row in records
            for key in keys
            if isinstance(row.get(key), (int, float)) and math.isfinite(row[key])
        ]
        if not values:
            return
        low, high = min(values), max(values)
        spread = high - low or max(high * 0.02, 1)
        drawing = Drawing(460, 165)
        drawing.add(Line(55, 28, 450, 28, strokeColor=colors.lightgrey))
        palette = [colors.HexColor(c) for c in ("#1465ad", "#c27d13", "#7c4da5", "#31866b")]
        for k, key in enumerate(keys):
            points = []
            for i, row in enumerate(records):
                value = row.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    points.extend(
                        [55 + i * 395 / (len(records) - 1), 28 + (value - low) * 100 / spread]
                    )
                else:
                    if len(points) >= 4:
                        drawing.add(PolyLine(points, strokeColor=palette[k], strokeWidth=1.3))
                    points = []
            if len(points) >= 4:
                drawing.add(PolyLine(points, strokeColor=palette[k], strokeWidth=1.3))
            drawing.add(
                String(
                    65 + k * 95,
                    145,
                    "Giá đóng cửa" if key == "close" else key.upper(),
                    fontName="Vietnamese",
                    fontSize=8,
                    fillColor=palette[k],
                )
            )
        for y, value in [(28, low), (128, high)]:
            drawing.add(String(2, y, number(value), fontName="Vietnamese", fontSize=7))
        for x, row in [(55, records[0]), (360, records[-1])]:
            drawing.add(
                String(
                    x,
                    9,
                    str(row.get("time", row.get("date", "")))[:10],
                    fontName="Vietnamese",
                    fontSize=8,
                )
            )
        story.extend([drawing, Spacer(1, 0.2 * cm)])
        source_caption(records, "price_unit")

    def contribution_chart(detail):
        drawing = Drawing(460, 90)
        breakdown = detail.get("breakdown", detail.get("composite", {}))
        plotted = False
        for i, key in enumerate(("FA", "TA", "NEWS")):
            component = breakdown.get(key, {})
            score = component.get("score", detail.get(f"{key.lower()}_score"))
            weight = component.get("weight")
            # A missing weight cannot be replaced by an assumed contribution.
            contribution = (
                score * weight
                if isinstance(score, (int, float)) and isinstance(weight, (int, float))
                else None
            )
            y = 68 - i * 25
            drawing.add(String(0, y + 2, key, fontName="Vietnamese", fontSize=9))
            if contribution is None:
                drawing.add(
                    String(65, y + 2, "Chưa đủ điểm/trọng số", fontName="Vietnamese", fontSize=8)
                )
            else:
                plotted = True
                drawing.add(
                    Rect(
                        65,
                        y,
                        max(contribution, 0) * 5,
                        12,
                        fillColor=colors.HexColor("#1465ad"),
                        strokeColor=None,
                    )
                )
                drawing.add(
                    String(
                        325, y + 2, f"{contribution:.2f} điểm", fontName="Vietnamese", fontSize=8
                    )
                )
        if plotted:
            story.append(drawing)

    para("BÁO CÁO PHÂN TÍCH CỔ PHIẾU VN30", "Title")
    para(f"Loại: {kind}; mã: {symbol or 'Toàn bộ'}")
    para(f"Xuất lúc: {created_at.isoformat()}")
    para(f"Ngày phân tích: {payload.get('as_of_date', 'Chưa xác định')}")
    para(
        f"Run: {payload.get('run_id', payload.get('id', 'Chưa có'))}; "
        f"config_hash: {payload.get('config_hash', 'Chưa có')}"
    )
    para("S = 45% FA + 35% TA + 20% NEWS. Thiếu thành phần: không xếp hạng tổng.")
    entries = payload.get("main_ranking", payload.get("ranking", [])) or []
    secondary = payload.get("secondary_ranking", payload.get("secondary", [])) or []
    for title, rows in [("Bảng xếp hạng chính", entries), ("Bảng dữ liệu chưa đủ", secondary)]:
        para(title, "Heading2")
        if not rows:
            para("Chưa có kết quả phù hợp.")
            continue
        data = [["Hạng", "Mã", "Ngành", "FA", "TA", "NEWS", "Tổng", "Trạng thái", "Giải thích"]]
        for row in rows:
            if symbol and row.get("symbol") != symbol:
                continue
            data.append(
                [
                    row.get("rank") or "—",
                    row.get("symbol", "—"),
                    row.get("sector", "—"),
                    number(row.get("fa_score")),
                    number(row.get("ta_score")),
                    number(row.get("news_score")),
                    number(row.get("total_score")),
                    row.get("status", "—"),
                    "; ".join(row.get("reasons", [])) or "—",
                ]
            )
        table(data, [v * cm for v in (0.7, 1, 2, 1, 1, 1, 1, 3.2, 6.8)])
    details = payload.get(
        "stocks", payload.get("stock_details", payload.get("results", payload.get("details", {})))
    )
    if isinstance(details, list):
        details = {str(item.get("symbol", i)): item for i, item in enumerate(details)}
    if isinstance(details, dict):
        for key, value in details.items():
            if symbol and key != symbol:
                continue
            para(f"Chi tiết: {key}", "Heading2")
            para(
                f"Ngành: {value.get('sector', 'Chưa có')}; "
                f"trạng thái: {value.get('status', 'Chưa có')}"
            )
            for reason in value.get("reasons", []):
                para(f"• {reason}")
            price_chart(value.get("prices", []))
            contribution_chart(value)
            fundamentals = [r for r in value.get("fundamentals", []) if isinstance(r, dict)]
            if fundamentals:
                para("Dữ liệu tài chính qua các kỳ", "Heading3")
                periods = sorted(
                    {
                        (str(r.get("period_end", "")), str(r.get("period_type", "Chưa xác minh")))
                        for r in fundamentals
                    },
                    reverse=True,
                )[:5]
                metric_names = list(dict.fromkeys(str(r.get("metric", "")) for r in fundamentals))
                preferred = [
                    m
                    for m in metric_names
                    if any(
                        term in m.lower()
                        for term in (
                            "doanh thu",
                            "lợi nhuận",
                            "tổng tài sản",
                            "vốn chủ sở hữu",
                            "roe",
                            "p/e",
                            "p/b",
                            "ebitda",
                            "lưu chuyển tiền",
                        )
                    )
                ]
                displayed = (preferred or metric_names)[:12]
                rows = [["Chỉ tiêu / đơn vị", *[f"{end} ({kind})" for end, kind in periods]]]
                for metric in displayed:
                    metric_rows = [r for r in fundamentals if str(r.get("metric", "")) == metric]
                    units = sorted({str(r["unit"]) for r in metric_rows if r.get("unit")})
                    rows.append(
                        [
                            f"{metric} ({', '.join(units) or 'Chưa xác minh'})",
                            *[
                                number(
                                    next(
                                        (
                                            r.get("value")
                                            for r in reversed(metric_rows)
                                            if str(r.get("period_end", "")) == period
                                            and str(r.get("period_type", "Chưa xác minh"))
                                            == period_type
                                        ),
                                        None,
                                    )
                                )
                                for period, period_type in periods
                            ],
                        ]
                    )
                table(rows, [6 * cm] + [11.7 * cm / len(periods)] * len(periods))
                para(
                    f"Trích {len(displayed)}/{len(metric_names)} chỉ tiêu "
                    f"và {len(periods)} kỳ mới nhất. "
                    "Kỳ năm và quý được ghi theo metadata nguồn."
                )
                source_caption(fundamentals)
            breakdown = value.get("breakdown", value.get("composite", {}))
            for component in ("FA", "TA"):
                detail = breakdown.get(component, {}).get(
                    "detail", value.get(component.lower(), {})
                )
                metrics = [
                    (name, row)
                    for name, row in detail.items()
                    if not name.startswith("_") and isinstance(row, dict)
                ]
                if metrics:
                    para(f"Chỉ tiêu {component}", "Heading3")
                    selected = metrics if symbol else metrics[:5]
                    rows = [["Chỉ tiêu", "Giá trị gốc", "Điểm", "Trọng số", "Đóng góp / lý do"]]
                    for name, row in selected:
                        rows.append(
                            [
                                name,
                                f"{number(row.get('raw'))} {row.get('unit') or ''}",
                                number(row.get("score")),
                                number(row.get("weight")),
                                row.get("reason") or number(row.get("weighted_contribution")),
                            ]
                        )
                    table(rows, [4.2 * cm, 3 * cm, 1.6 * cm, 1.8 * cm, 5.4 * cm])
                    if len(metrics) > len(selected):
                        para(
                            f"Hiển thị {len(selected)}/{len(metrics)} chỉ tiêu; "
                            "PDF từng mã chứa đầy đủ."
                        )
            news_detail = breakdown.get("NEWS", {}).get("detail", value.get("news", {}))
            items = news_detail.get("items", []) if isinstance(news_detail, dict) else news_detail
            if items:
                para("Tin tức và sự kiện", "Heading3")
                for item in items[: 10 if symbol else 3]:
                    para(f"{item.get('published_at', '')}: {item.get('title', '')}")
                    para(
                        f"Sự kiện: {item.get('event_type', 'chưa phân loại')}; "
                        f"độ tin cậy: {number(item.get('confidence'))}; "
                        f"điểm: {number(item.get('sentiment_score'))}. {item.get('url', '')}"
                    )
                source_caption(value.get("news", []))
            provenance = value.get("provenance", {})
            if provenance:
                para("Truy xuất dữ liệu", "Heading3")
                for name, record in provenance.items():
                    if isinstance(record, list):
                        para(
                            f"{name}: {len(record)} bản ghi; "
                            f"ID đầu: {', '.join(map(str, record[:8]))}"
                        )
                    else:
                        para(f"{name}: {record}")
            sources = sorted(
                {
                    str(row.get("source_url"))
                    for section in ("prices", "fundamentals", "news")
                    for row in value.get(section, [])
                    if isinstance(row, dict) and row.get("source_url")
                }
            )
            for source in sources[:8]:
                para(f"Nguồn: {source}")
    for key in ("sources", "provenance", "input_record_ids", "backtest", "limitations", "reasons"):
        if payload.get(key):
            para(key, "Heading2")
            para(json.dumps(payload[key], ensure_ascii=False, default=str, indent=2))
    para(
        "Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư. Điểm không đại diện "
        "cho xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến."
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Vietnamese", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(
            1.5 * cm,
            0.8 * cm,
            f"Ngày: {payload.get('as_of_date', '—')} | "
            f"Tạo: {created_at:%Y-%m-%d %H:%M} UTC | "
            f"Scoring: {payload.get('scoring_version', 'Chưa có')}",
        )
        canvas.drawRightString(19.5 * cm, 0.8 * cm, f"Trang {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        str(path),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return path
