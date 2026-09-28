"""PDF 解析：提取可读文字，按空行切分正文块，保留页码。

扫描件没有可提取正文时明确失败，不承诺 OCR。
"""

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

from shared.contracts import FileRef, ParsedBlock, ParsedDocument
from shared.errors import AppError

MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_PDF_PAGES = 500


def parse_pdf(file: FileRef) -> ParsedDocument:
    """解析 PDF，按页提取文字，再按空行切分段落块。

    - 保留真实页码
    - 不伪造标题
    - 扫描件没有可提取正文时抛 AppError
    - 超过大小或页数限制时抛 AppError
    """
    if not file.path.exists():
        raise AppError("file_not_found", "文件不存在或已被移除", 404)

    if file.path.stat().st_size > MAX_PDF_BYTES:
        raise AppError("document_too_large", "PDF 文件超过大小限制", 422)

    try:
        pages = list(extract_pages(str(file.path)))
    except Exception as exc:
        raise AppError("unsupported_document", "PDF 文件无法解析", 422) from exc

    if len(pages) > MAX_PDF_PAGES:
        raise AppError("document_too_large", "PDF 页数超过限制", 422)

    blocks: list[ParsedBlock] = []

    for page_no, layout in enumerate(pages, start=1):
        page_text_parts: list[str] = []
        for element in layout:
            if isinstance(element, LTTextContainer):
                text = element.get_text().strip()
                if text:
                    page_text_parts.append(text)

        page_text = "\n".join(page_text_parts)
        for para in page_text.split("\n\n"):
            stripped = para.strip()
            if not stripped:
                continue
            blocks.append(
                ParsedBlock(
                    block_no=len(blocks),
                    text=stripped,
                    page=page_no,
                )
            )

    if not blocks:
        raise AppError("unsupported_document", "PDF 无可提取正文，可能是扫描件", 422)

    return ParsedDocument(blocks=blocks)
