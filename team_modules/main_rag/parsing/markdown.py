"""Markdown 解析：按标题和空行切分正文块，保留标题作为 heading。"""

import re

from shared.contracts import FileRef, ParsedBlock, ParsedDocument
from shared.errors import AppError

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_markdown(file: FileRef) -> ParsedDocument:
    """解析 Markdown，按标题和空行切分段落块。

    - 标题行作为 heading 记录
    - 标题行本身也作为一个块，text 为标题文字
    - 空行跳过
    - 没有可提取正文时抛 AppError
    """
    try:
        text = file.path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AppError("file_not_found", "文件不存在或已被移除", 404)
    except UnicodeDecodeError:
        raise AppError("unsupported_encoding", "Markdown 文件不是 UTF-8 编码", 422)

    blocks: list[ParsedBlock] = []
    current_heading: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        match = _HEADING_RE.match(stripped)
        if match:
            current_heading = match.group(2)
            blocks.append(
                ParsedBlock(
                    block_no=len(blocks),
                    text=current_heading,
                    heading=current_heading,
                )
            )
            continue

        blocks.append(
            ParsedBlock(
                block_no=len(blocks),
                text=stripped,
                heading=current_heading,
            )
        )

    if not blocks:
        raise AppError("empty_document", "文件没有可提取正文", 422)

    return ParsedDocument(blocks=blocks)
