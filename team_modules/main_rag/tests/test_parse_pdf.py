"""PDF 解析测试。"""

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from shared.contracts import FileRef
from shared.errors import AppError
from team_modules.main_rag.adapter import MainRAGAdapter


def make_pdf(tmp_path: Path, pages: list[str]) -> FileRef:
    """生成一个简单的可提取文字 PDF。"""
    path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(path))
    for text in pages:
        c.drawString(100, 750, text)
        c.showPage()
    c.save()
    return FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=path,
        filename="test.pdf",
        content_hash="abc123",
    )


def test_parse_pdf_basic(tmp_path: Path):
    file = make_pdf(tmp_path, ["第一页第一段。", "第二页第一段。"])
    doc = MainRAGAdapter().parse(file)
    assert len(doc.blocks) >= 2
    assert doc.blocks[0].page == 1
    assert doc.blocks[-1].page == 2


def test_parse_pdf_missing(tmp_path: Path):
    file = FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=tmp_path / "not_exist.pdf",
        filename="not_exist.pdf",
        content_hash="abc123",
    )
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "file_not_found"


def test_parse_pdf_scanned_no_text(tmp_path: Path):
    path = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(path))
    c.showPage()  # 空白页，没有文字
    c.save()
    file = FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=path,
        filename="scanned.pdf",
        content_hash="abc123",
    )
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "unsupported_document"


def test_parse_pdf_too_large(tmp_path: Path, monkeypatch):
    file = make_pdf(tmp_path, ["内容。"])
    monkeypatch.setattr(
        "team_modules.main_rag.parsing.pdf.MAX_PDF_BYTES",
        1,
    )
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "document_too_large"


def test_parse_pdf_too_many_pages(tmp_path: Path, monkeypatch):
    file = make_pdf(tmp_path, ["第一页。", "第二页。"])
    monkeypatch.setattr(
        "team_modules.main_rag.parsing.pdf.MAX_PDF_PAGES",
        1,
    )
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "document_too_large"
