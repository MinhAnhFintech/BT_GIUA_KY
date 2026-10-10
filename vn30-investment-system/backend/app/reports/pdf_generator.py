"""PDF report generator using ReportLab with Vietnamese font support."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
DISCLAIMER = (
    "Cong cu ho tro phan tich, khong phai khuyen nghi dau tu. "
    "Diem khong dai dien cho xac suat tang gia hoac ty suat loi nhuan du kien."
)


def _safe_text(text: str) -> str:
    """Convert Vietnamese text to safe ASCII for ReportLab basic fonts."""
    replacements = {
        "ă": "a",
        "â": "a",
        "đ": "d",
        "ê": "e",
        "ô": "o",
        "ơ": "o",
        "ư": "u",
        "Ă": "A",
        "Â": "A",
        "Đ": "D",
        "Ê": "E",
        "Ô": "O",
        "Ơ": "O",
        "Ư": "U",
        "à": "a",
        "á": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ằ": "a",
        "ắ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "ầ": "a",
        "ấ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "è": "e",
        "é": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ề": "e",
        "ế": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "ì": "i",
        "í": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ò": "o",
        "ó": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ồ": "o",
        "ố": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ờ": "o",
        "ớ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ù": "u",
        "ú": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ừ": "u",
        "ứ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ỳ": "y",
        "ý": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
        "À": "A",
        "Á": "A",
        "Ả": "A",
        "Ã": "A",
        "Ạ": "A",
        "Ằ": "A",
        "Ắ": "A",
        "Ẳ": "A",
        "Ẵ": "A",
        "Ặ": "A",
        "Ầ": "A",
        "Ấ": "A",
        "Ẩ": "A",
        "Ẫ": "A",
        "Ậ": "A",
        "È": "E",
        "É": "E",
        "Ẻ": "E",
        "Ẽ": "E",
        "Ẹ": "E",
        "Ề": "E",
        "Ế": "E",
        "Ể": "E",
        "Ễ": "E",
        "Ệ": "E",
        "Ì": "I",
        "Í": "I",
        "Ỉ": "I",
        "Ĩ": "I",
        "Ị": "I",
        "Ò": "O",
        "Ó": "O",
        "Ỏ": "O",
        "Õ": "O",
        "Ọ": "O",
        "Ồ": "O",
        "Ố": "O",
        "Ổ": "O",
        "Ỗ": "O",
        "Ộ": "O",
        "Ờ": "O",
        "Ớ": "O",
        "Ở": "O",
        "Ỡ": "O",
        "Ợ": "O",
        "Ù": "U",
        "Ú": "U",
        "Ủ": "U",
        "Ũ": "U",
        "Ụ": "U",
        "Ừ": "U",
        "Ứ": "U",
        "Ử": "U",
        "Ữ": "U",
        "Ự": "U",
        "Ỳ": "Y",
        "Ý": "Y",
        "Ỷ": "Y",
        "Ỹ": "Y",
        "Ỵ": "Y",
    }
    for vn, ascii_char in replacements.items():
        text = text.replace(vn, ascii_char)
    return text


def _fmt_score(score: float | None) -> str:
    if score is None:
        return "N/A"
    return f"{score:.1f}"


def _fmt_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.{decimals}f}T"
    if abs(value) >= 1e9:
        return f"{value / 1e9:.{decimals}f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.{decimals}f}M"
    return f"{value:.{decimals}f}"


def generate_summary_pdf(analysis_data: dict[str, Any], settings: Any, output_path: Path) -> Path:
    """Generate summary ranking PDF report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=18, spaceAfter=6)
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=12, spaceAfter=12, alignment=TA_CENTER
    )
    normal_style = ParagraphStyle("CustomNormal", parent=styles["Normal"], fontSize=9, spaceAfter=6)
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontSize=7, textColor=colors.grey, spaceAfter=6
    )

    elements = []
    now = datetime.now(VN_TZ)

    # Cover page
    elements.append(Spacer(1, 40 * mm))
    elements.append(
        Paragraph(_safe_text("HE THONG PHAN TICH CO HOI DAU TU CO PHIEU VN30"), title_style)
    )
    elements.append(Paragraph(_safe_text("BAO CAO TONG HOP XEP HANG"), subtitle_style))
    elements.append(Spacer(1, 10 * mm))
    elements.append(
        Paragraph(
            f"Ngay phan tich: {analysis_data.get('as_of_date', now.strftime('%Y-%m-%d'))}",
            subtitle_style,
        )
    )
    elements.append(
        Paragraph(
            f"Scoring version: {analysis_data.get('scoring_version', 'scoring-1.0.0')}",
            subtitle_style,
        )
    )

    symbols = [
        r.get("symbol", "")
        for r in analysis_data.get("main_ranking", []) + analysis_data.get("secondary_ranking", [])
    ]
    elements.append(Paragraph(f"Danh sach ma: {', '.join(symbols)}", subtitle_style))
    elements.append(Spacer(1, 20 * mm))
    elements.append(Paragraph(DISCLAIMER, disclaimer_style))
    elements.append(PageBreak())

    # Main ranking table
    elements.append(Paragraph(_safe_text("BANG XEP HANG CHINH"), styles["Heading2"]))
    elements.append(Spacer(1, 5 * mm))

    main_data = [["Hang", "Ma", "Nganh", "FA", "TA", "NEWS", "Tong (S)", "Trang thai"]]
    for r in analysis_data.get("main_ranking", []):
        main_data.append(
            [
                str(r.get("rank", "-")),
                r.get("symbol", ""),
                _safe_text(r.get("sector", "")),
                _fmt_score(r.get("fa_score")),
                _fmt_score(r.get("ta_score")),
                _fmt_score(r.get("news_score")),
                _fmt_score(r.get("total_score")),
                r.get("status", ""),
            ]
        )

    if len(main_data) > 1:
        t = Table(main_data, colWidths=[30, 40, 70, 40, 40, 40, 50, 80])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f0f4f8")],
                    ),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(
            Paragraph(
                _safe_text("Chua co du lieu phan tich. Hay chay phan tich truoc."), normal_style
            )
        )

    elements.append(Spacer(1, 10 * mm))

    # Secondary table
    secondary = analysis_data.get("secondary_ranking", [])
    if secondary:
        elements.append(Paragraph(_safe_text("MA CHUA DU DU LIEU"), styles["Heading2"]))
        sec_data = [["Ma", "Nganh", "FA", "TA", "NEWS", "Trang thai", "Ly do"]]
        for r in secondary:
            reasons = "; ".join(r.get("reasons", [])[:2])
            sec_data.append(
                [
                    r.get("symbol", ""),
                    _safe_text(r.get("sector", "")),
                    _fmt_score(r.get("fa_score")),
                    _fmt_score(r.get("ta_score")),
                    _fmt_score(r.get("news_score")),
                    r.get("status", ""),
                    _safe_text(reasons[:60]),
                ]
            )
        t2 = Table(sec_data, colWidths=[40, 60, 35, 35, 35, 80, 120])
        t2.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#744210")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#fffff0")],
                    ),
                ]
            )
        )
        elements.append(t2)

    elements.append(Spacer(1, 10 * mm))

    # Methodology
    elements.append(Paragraph(_safe_text("PHUONG PHAP LUAN"), styles["Heading2"]))
    elements.append(Paragraph("S = 0.45 x FA + 0.35 x TA + 0.20 x NEWS", normal_style))
    elements.append(
        Paragraph(_safe_text("FA (45%): Phan tich tai chinh theo dac thu nganh"), normal_style)
    )
    elements.append(
        Paragraph(_safe_text("TA (35%): Xu huong gia, MA, RSI, MACD, thanh khoan"), normal_style)
    )
    elements.append(
        Paragraph(_safe_text("NEWS (20%): Tin tuc, muc do anh huong, do moi"), normal_style)
    )
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph(_safe_text("HAN CHE"), styles["Heading3"]))
    elements.append(
        Paragraph(
            _safe_text(
                "- Diem khong phai khuyen nghi dau tu. "
                "- Du lieu co the bi tre hoac thieu. "
                "- Chi ap dung cho co phieu VN30. "
                "- Ket qua qua khu khong dam bao tuong lai."
            ),
            normal_style,
        )
    )

    # Footer disclaimer
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(DISCLAIMER, disclaimer_style))
    elements.append(
        Paragraph(f"Tao luc: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+7)", disclaimer_style)
    )

    doc.build(elements)
    logger.info("Summary PDF generated: %s", output_path)
    return output_path


def generate_stock_pdf(
    symbol: str, analysis_data: dict[str, Any], settings: Any, output_path: Path
) -> Path:
    """Generate individual stock analysis PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("StockTitle", parent=styles["Title"], fontSize=16)
    normal_style = ParagraphStyle("StockNormal", parent=styles["Normal"], fontSize=9, spaceAfter=4)
    disclaimer_style = ParagraphStyle(
        "StockDisclaimer", parent=styles["Normal"], fontSize=7, textColor=colors.grey
    )

    elements = []
    now = datetime.now(VN_TZ)
    detail = analysis_data.get("stock_details", {}).get(symbol, {})

    # Title
    elements.append(Paragraph(f"PHAN TICH CO PHIEU: {symbol}", title_style))
    elements.append(Paragraph(f"Nganh: {_safe_text(detail.get('sector', 'N/A'))}", normal_style))
    elements.append(Paragraph(f"Ngay: {analysis_data.get('as_of_date', '')}", normal_style))
    elements.append(Spacer(1, 5 * mm))

    # Score summary
    composite = detail.get("composite", {})
    elements.append(Paragraph(_safe_text("DIEM TONG HOP"), styles["Heading2"]))
    score_data = [
        ["Thanh phan", "Diem", "Trong so", "Dong gop"],
        [
            "FA",
            _fmt_score(composite.get("FA", {}).get("score")),
            "45%",
            _fmt_score(
                composite.get("FA", {}).get("score", 0) * 0.45
                if composite.get("FA", {}).get("score")
                else None
            ),
        ],
        [
            "TA",
            _fmt_score(composite.get("TA", {}).get("score")),
            "35%",
            _fmt_score(
                composite.get("TA", {}).get("score", 0) * 0.35
                if composite.get("TA", {}).get("score")
                else None
            ),
        ],
        [
            "NEWS",
            _fmt_score(composite.get("NEWS", {}).get("score")),
            "20%",
            _fmt_score(
                composite.get("NEWS", {}).get("score", 0) * 0.20
                if composite.get("NEWS", {}).get("score")
                else None
            ),
        ],
        [
            "TONG (S)",
            _fmt_score(composite.get("total_score")),
            "100%",
            _fmt_score(composite.get("total_score")),
        ],
    ]
    t = Table(score_data, colWidths=[80, 60, 60, 60])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 8 * mm))

    # TA Breakdown
    ta_detail = detail.get("ta", {})
    if ta_detail and ta_detail != {}:
        elements.append(
            Paragraph(_safe_text("CHI TIET PHAN TICH KY THUAT (TA)"), styles["Heading2"])
        )
        ta_rows = [["Chi bao", "Gia tri", "Diem", "Trong so"]]
        for key, val in ta_detail.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            ta_rows.append(
                [
                    key,
                    str(round(val.get("raw", 0), 4)) if val.get("raw") is not None else "N/A",
                    _fmt_score(val.get("score")),
                    f"{val.get('weight', 0):.0%}",
                ]
            )
        if len(ta_rows) > 1:
            t_ta = Table(ta_rows, colWidths=[100, 60, 50, 50])
            t_ta.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            elements.append(t_ta)
        elements.append(Spacer(1, 5 * mm))

    # FA Breakdown
    fa_detail = detail.get("fa", {})
    if fa_detail and fa_detail != {}:
        elements.append(
            Paragraph(_safe_text("CHI TIET PHAN TICH TAI CHINH (FA)"), styles["Heading2"])
        )
        fa_rows = [["Chi tieu", "Gia tri", "Diem", "Trong so"]]
        for key, val in fa_detail.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            fa_rows.append(
                [
                    key,
                    str(round(val.get("raw", 0), 4)) if val.get("raw") is not None else "N/A",
                    _fmt_score(val.get("score")),
                    f"{val.get('weight', 0):.0%}",
                ]
            )
        if len(fa_rows) > 1:
            t_fa = Table(fa_rows, colWidths=[120, 60, 50, 50])
            t_fa.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            elements.append(t_fa)
        elements.append(Spacer(1, 5 * mm))

    # News
    news_detail = detail.get("news", {})
    if isinstance(news_detail, dict) and news_detail.get("items"):
        elements.append(Paragraph(_safe_text("TIN TUC GAN DAY"), styles["Heading2"]))
        for item in news_detail["items"][:5]:
            title = _safe_text(item.get("title", "")[:100])
            sentiment = item.get("direction", "neutral")
            elements.append(Paragraph(f"- [{sentiment}] {title}", normal_style))

    # Disclaimer
    elements.append(Spacer(1, 15 * mm))
    elements.append(Paragraph(DISCLAIMER, disclaimer_style))
    elements.append(
        Paragraph(f"Tao luc: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+7)", disclaimer_style)
    )

    doc.build(elements)
    logger.info("Stock PDF generated: %s (%s)", symbol, output_path)
    return output_path
