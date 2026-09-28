"""DOCX 解析：按段落切分正文块，保留标题作为 heading，不伪造页码。"""

from docx import Document

from shared.contracts import FileRef, ParsedBlock, ParsedDocument
from shared.errors import AppError

MAX_DOCX_BYTES = 50 * 1024 * 1024  # 50 MB


def _is_heading(paragraph) -> bool:
    """判断段落是否为标题样式。"""
    style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
    return style_name.startswith("heading") or style_name.startswith("标题")


def parse_docx(file: FileRef) -> ParsedDocument:
    """解析 DOCX，按段落切分正文块。

    - 标题样式段落作为 heading
    - DOCX 不伪造页码，page 留空
    - 空段落跳过
    - 没有可提取正文时抛 AppError
    """
    if not file.path.exists():
        raise AppError("file_not_found", "文件不存在或已被移除", 404)

    if file.path.stat().st_size > MAX_DOCX_BYTES:
        raise AppError("document_too_large", "DOCX 文件超过大小限制", 422)

    try:
        document = Document(str(file.path))
    except Exception as exc:
        raise AppError("unsupported_document", "DOCX 文件无法解析", 422) from exc

    blocks: list[ParsedBlock] = []
    current_heading: str | None = None

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        if _is_heading(paragraph):
            current_heading = text
            blocks.append(
                ParsedBlock(
                    block_no=len(blocks),
                    text=text,
                    heading=current_heading,
                )
            )
            continue

        blocks.append(
            ParsedBlock(
                block_no=len(blocks),
                text=text,
                heading=current_heading,
            )
        )

    if not blocks:
        raise AppError("empty_document", "文件没有可提取正文", 422)

    return ParsedDocument(blocks=blocks)
