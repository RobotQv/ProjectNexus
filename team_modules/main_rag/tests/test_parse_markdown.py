"""Markdown 解析测试。"""

from pathlib import Path

import pytest

from shared.contracts import FileRef
from shared.errors import AppError
from team_modules.main_rag.adapter import MainRAGAdapter


def make_file_ref(tmp_path: Path, content: str, filename: str = "test.md") -> FileRef:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=path,
        filename=filename,
        content_hash="abc123",
    )


def test_parse_markdown_basic(tmp_path: Path):
    content = "# 标题一\n\n第一段。\n\n## 标题二\n\n第二段。"
    file = make_file_ref(tmp_path, content)
    doc = MainRAGAdapter().parse(file)
    assert len(doc.blocks) == 4
    assert doc.blocks[0].text == "标题一"
    assert doc.blocks[0].heading == "标题一"
    assert doc.blocks[1].text == "第一段。"
    assert doc.blocks[1].heading == "标题一"
    assert doc.blocks[2].text == "标题二"
    assert doc.blocks[3].text == "第二段。"
    assert doc.blocks[3].heading == "标题二"


def test_parse_markdown_empty(tmp_path: Path):
    file = make_file_ref(tmp_path, "\n\n\n")
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "empty_document"


def test_parse_markdown_extension(tmp_path: Path):
    file = make_file_ref(tmp_path, "# 标题\n\n正文。", filename="test.markdown")
    doc = MainRAGAdapter().parse(file)
    assert len(doc.blocks) == 2
