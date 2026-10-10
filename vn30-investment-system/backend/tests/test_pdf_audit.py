from datetime import UTC, datetime

from pypdf import PdfReader

from backend.app.reports import pdf


def test_vietnamese_font_extraction_and_footer_on_every_page(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "PROJECT_ROOT", tmp_path)
    payload = {
        "as_of_date": "2026-10-09",
        "scoring_version": "scoring-1.0.0",
        "secondary_ranking": [
            {
                "symbol": "FPT",
                "sector": "Công nghệ thông tin",
                "status": "PARTIAL",
                "reasons": ["Thiếu dữ liệu: Đầu tư, lợi nhuận, cổ phiếu, nguồn công khai"],
            }
        ],
        "stocks": [{"symbol": "FPT", "reasons": ["Dữ liệu chưa đủ"] * 100}],
    }
    reader = PdfReader(pdf.create_report(payload))
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    assert "Công nghệ thông tin" in text
    assert "Đầu tư, lợi nhuận, cổ phiếu, nguồn công khai" in text
    assert "\ufffd" not in text
    assert len(reader.pages) > 1
    for i, page in enumerate(reader.pages, 1):
        extracted = page.extract_text()
        assert "Tạo:" in extracted
        assert "Scoring: scoring-1.0.0" in extracted
        assert f"Trang {i}" in extracted
    assert any(
        "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
        for page in reader.pages
        for font in page["/Resources"]["/Font"].get_object().values()
        if "/FontDescriptor" in font.get_object()
    )


def test_pdf_price_chart_breaks_at_missing_values_and_labels_provenance(tmp_path, monkeypatch):
    from reportlab.graphics.shapes import Drawing, PolyLine
    from reportlab.platypus import SimpleDocTemplate

    monkeypatch.setattr(pdf, "PROJECT_ROOT", tmp_path)
    drawings = []
    original = SimpleDocTemplate.build

    def capture(self, story, *args, **kwargs):
        drawings.extend(item for item in story if isinstance(item, Drawing))
        return original(self, story, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", capture)
    prices = [
        {
            "time": f"2026-10-0{i + 1}",
            "close": value,
            "source": "VCI",
            "price_unit": "VND",
            "fetched_at": "2026-10-09T07:30:00Z",
        }
        for i, value in enumerate([100, 101, None, 103, 104])
    ]
    path = pdf.create_report({"stocks": [{"symbol": "FPT", "prices": prices}]})
    assert len([shape for shape in drawings[0].contents if isinstance(shape, PolyLine)]) == 2
    text = " ".join(page.extract_text() for page in PdfReader(path).pages)
    assert "Đơn vị: VND" in text
    assert "nguồn: VCI" in text
    assert "lấy lúc: 2026-10-09T07:30:00Z" in text


def test_pdf_separates_annual_and_quarterly_values(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "PROJECT_ROOT", tmp_path)
    fundamentals = [
        {
            "period_end": "2025-12-31",
            "period_type": kind,
            "metric": "Doanh thu",
            "value": value,
            "unit": "VND",
            "source": "VCI",
            "fetched_at": datetime.now(UTC),
        }
        for kind, value in [("annual", 999), ("quarter", 123)]
    ]
    path = pdf.create_report({"stocks": [{"symbol": "FPT", "fundamentals": fundamentals}]})
    text = " ".join(page.extract_text() for page in PdfReader(path).pages)
    assert "2025-12-31 (annual)" in text
    assert "2025-12-31 (quarter)" in text
    assert "999" in text and "123" in text
