"""TXT 解析测试。"""

from pathlib import Path

import pytest

from shared.contracts import FileRef
from shared.errors import AppError
from team_modules.main_rag.adapter import MainRAGAdapter


def make_file_ref(tmp_path: Path, content: str, filename: str = "test.txt") -> FileRef:
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


def test_parse_txt_basic(tmp_path: Path):
    file = make_file_ref(tmp_path, "第一段。\n\n第二段。\n\n第三段。")
    doc = MainRAGAdapter().parse(file)
    assert len(doc.blocks) == 3
    assert doc.blocks[0].block_no == 0
    assert doc.blocks[0].text == "第一段。"
    assert doc.blocks[1].block_no == 1
    assert doc.blocks[2].block_no == 2


def test_parse_txt_empty(tmp_path: Path):
    file = make_file_ref(tmp_path, "   \n\n   ")
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "empty_document"


def test_parse_txt_missing(tmp_path: Path):
    file = FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=tmp_path / "not_exist.txt",
        filename="not_exist.txt",
        content_hash="abc123",
    )
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "file_not_found"


def test_parse_unsupported_format(tmp_path: Path):
    file = make_file_ref(tmp_path, "内容", filename="test.xyz")
    with pytest.raises(AppError) as exc:
        MainRAGAdapter().parse(file)
    assert exc.value.code == "unsupported_format"
