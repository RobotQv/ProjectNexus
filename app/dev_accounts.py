"""公开版虚构演示账号；不是学生名单。仅允许本机开发/测试初始化。"""

from sqlalchemy import select

from app.core.security import hash_password
from app.models import User

# 学号必须是字符串，特别是 000000003 不可转成整数。
STUDENT_ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("900000001", "演示成员甲"),
    ("900000002", "演示成员乙"),
    ("000000003", "演示成员丙"),
    ("900000004", "演示成员丁"),
    ("900000005", "演示成员戊"),
    ("900000006", "演示成员己"),
)


def seed_students(db, *, environment: str) -> dict[str, list[str]]:
    """事务由 CLI/调用方管理；只补缺失账号，不重置密码、不修改已有身份。"""
    if environment not in {"development", "test"}:
        raise ValueError("学号初始密码仅允许本地开发/测试环境，生产环境禁止初始化")

    # 先整体校验，发现同学号不同姓名时停止，不擅自接管或覆盖已有用户。
    missing, existing = [], []
    for student_id, name in STUDENT_ACCOUNTS:
        user = db.scalar(select(User).where(User.login_name == student_id))
        if user:
            if user.display_name != name:
                raise ValueError("有学号已对应其他姓名；未覆盖已有账号，请先核对本地用户")
            existing.append(student_id)
        else:
            missing.append((student_id, name))
    for student_id, name in missing:
        db.add(
            User(login_name=student_id, display_name=name, password_hash=hash_password(student_id))
        )
    db.flush()
    return {"created": [student_id for student_id, _ in missing], "existing": existing}
