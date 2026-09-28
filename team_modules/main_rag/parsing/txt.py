"""TXT 解析：读取 UTF-8 文本，按空行切分正文块。"""

from shared.contracts import FileRef, ParsedBlock, ParsedDocument
from shared.errors import AppError


def parse_txt(file: FileRef) -> ParsedDocument:
    """解析 UTF-8 TXT，按空行切分段落块。

    - block_no 从 0 开始，同一文档版本内唯一
    - 空段落跳过
    - 没有可提取正文时抛 AppError
    """
    try:
        text = file.path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AppError("file_not_found", "文件不存在或已被移除", 404)
    except UnicodeDecodeError:
        raise AppError("unsupported_encoding", "TXT 文件不是 UTF-8 编码", 422)

    blocks: list[ParsedBlock] = []
    for para in text.split("\n\n"):
        stripped = para.strip()
        if not stripped:
            continue
        blocks.append(
            ParsedBlock(
                block_no=len(blocks),
                text=stripped,
            )
        )

    if not blocks:
        raise AppError("empty_document", "文件没有可提取正文", 422)

    return ParsedDocument(blocks=blocks)
