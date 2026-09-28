"""契约 smoke 测试：验证 parse 对缺失文件抛 AppError，而不是假装成功。"""

import pytest

from shared.contracts import FileRef
from shared.errors import AppError
from team_modules.main_rag.adapter import MainRAGAdapter


def test_parse_missing_file_is_not_success(tmp_path):
    reference = FileRef(
        project_id=1,
        document_id=1,
        version=1,
        path=tmp_path / "sample.txt",
        filename="sample.txt",
        content_hash="test",
    )
    with pytest.raises(AppError) as error:
        MainRAGAdapter().parse(reference)
    assert error.value.code == "file_not_found"
