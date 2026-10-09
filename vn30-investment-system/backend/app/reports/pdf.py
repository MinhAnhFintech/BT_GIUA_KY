"""Generate auditable Vietnamese PDF reports from an immutable analysis payload."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from backend.app.core.config import PROJECT_ROOT


def create_report(payload: dict, kind: str = "ranking", symbol: str | None = None) -> Path:
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
    folder = PROJECT_ROOT / "reports_out"
    folder.mkdir(exist_ok=True)
    path = folder / f"{kind}-{uuid4().hex}.pdf"
    story = []

    def para(value, style="Normal"):
        story.append(Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style]))
        story.append(Spacer(1, 0.15 * cm))

    para("BÁO CÁO PHÂN TÍCH CỔ PHIẾU VN30", "Title")
    para(f"Loại: {kind}; mã: {symbol or 'Toàn bộ'}")
    para(f"Xuất lúc: {datetime.now(UTC).isoformat()}")
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
        data = [["Mã", "FA", "TA", "NEWS", "Tổng", "Trạng thái"]]
        for row in rows:
            if symbol and row.get("symbol") != symbol:
                continue
            data.append(
                [
                    str(row.get(key, "—") if row.get(key) is not None else "—")
                    for key in (
                        "symbol",
                        "fa_score",
                        "ta_score",
                        "news_score",
                        "total_score",
                        "status",
                    )
                ]
            )
        table = Table(
            data, repeatRows=1, colWidths=[1.4 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 8 * cm]
        )
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Vietnamese"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ]
            )
        )
        story.extend([table, Spacer(1, 0.3 * cm)])
    details = payload.get("stock_details", payload.get("results", payload.get("details", {})))
    if isinstance(details, list):
        details = {str(item.get("symbol", i)): item for i, item in enumerate(details)}
    if isinstance(details, dict):
        for key, value in details.items():
            if symbol and key != symbol:
                continue
            para(f"Chi tiết: {key}", "Heading2")
            # JSON includes source URLs, input IDs, raw values and missing reasons as supplied.
            para(json.dumps(value, ensure_ascii=False, default=str, indent=2))
    for key in ("sources", "provenance", "input_record_ids", "backtest", "limitations", "reasons"):
        if payload.get(key):
            para(key, "Heading2")
            para(json.dumps(payload[key], ensure_ascii=False, default=str, indent=2))
    para(
        "Công cụ hỗ trợ phân tích, không phải khuyến nghị đầu tư. Điểm không đại diện "
        "cho xác suất tăng giá hoặc tỷ suất lợi nhuận dự kiến."
    )
    SimpleDocTemplate(str(path), topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(story)
    return path
