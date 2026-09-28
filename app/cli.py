"""运维入口。迁移与建账号显式执行；不提供匿名注册或默认管理员密码。"""

import argparse
import getpass
import os
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import begin_write, build_engine, session_factory
from app.dev_accounts import seed_students
from app.models import User
from app.schemas import ProjectCreate, TaskCreate
from app.services.business import create_task

ROOT = Path(__file__).resolve().parents[1]


def migrate(database_url):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def init_env():
    """仅首次生成本地配置；不覆盖已经填写的密钥。"""
    target = ROOT / ".env"
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    text = text.replace(
        "replace-with-a-random-secret-at-least-32-characters", secrets.token_hex(32)
    )
    try:
        with target.open("x", encoding="utf-8") as file:
            file.write(text)
    except FileExistsError:
        print(".env 已存在，未覆盖。")
        return
    print("已生成 .env 与随机登录签名密钥；算法 / 大模型默认不启用。")


def add_user(db, login_name, display_name, password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("密码长度须为 12—256 个字符")
    if (
        not login_name.strip()
        or len(login_name) > 64
        or not display_name.strip()
        or len(display_name) > 100
    ):
        raise ValueError("登录名须为 1—64 字符，显示名须为 1—100 字符")
    if db.scalar(select(User).where(User.login_name == login_name)):
        raise ValueError("该登录名已存在；未修改原账号")
    user = User(
        login_name=login_name, display_name=display_name, password_hash=hash_password(password)
    )
    db.add(user)
    db.flush()
    return user


def seed_demo(db, password):
    """只向空用户库写入小型联调数据；不是审计文档所指的冻结评测数据集。"""
    from app.models import Project, ProjectMember
    from app.services.common import enqueue

    if db.scalar(select(User.id).limit(1)):
        raise ValueError("seed-demo 仅允许在空用户库执行，不覆盖现有数据")
    users = [
        add_user(db, f"demo{i}", name, password)
        for i, name in enumerate(
            ["后端架构", "前端开发", "测试", "主 RAG", "工作流与轻 RAG", "依赖与风险"], start=1
        )
    ]
    for n in (1, 2):
        project = Project(**ProjectCreate(name=f"联调项目{n}").model_dump(), owner_id=users[0].id)
        db.add(project)
        db.flush()
        for user in users if n == 1 else [users[0], users[2]]:
            member = ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role="owner" if user.id == users[0].id else "member",
            )
            db.add(member)
            db.flush()
            enqueue(
                db,
                project.id,
                "entity_sync",
                "member",
                user.id,
                member.version,
                key=f"member:{project.id}:{user.id}:v1",
            )
        create_task(
            db,
            project.id,
            users[0].id,
            TaskCreate(title=f"项目{n}后端接口联调", assignee_id=users[0].id),
        )
    return [u.login_name for u in users]


def main():
    parser = argparse.ArgumentParser(description="ProjectNexus 后端工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-env", help="生成 .env，不覆盖已有文件")
    sub.add_parser("migrate", help="迁移数据库到当前最新版本")
    user_parser = sub.add_parser("create-user", help="交互式创建预设账号")
    user_parser.add_argument("--login", required=True)
    user_parser.add_argument("--name", required=True)
    sub.add_parser("seed-demo", help="空库写入 6 个联调账号和 2 个小型项目（交互式设置共同密码）")
    sub.add_parser("seed-students", help="本地课设：初始化六个虚构演示账号，示例登录名为初始密码")
    args = parser.parse_args()
    if args.command == "init-env":
        init_env()
        return
    settings = get_settings()
    if args.command == "migrate":
        migrate(settings.database_url)
        return
    if args.command == "seed-students":
        engine = build_engine(settings.database_url)
        try:
            with session_factory(engine)() as db:
                begin_write(db)
                result = seed_students(db, environment=settings.environment)
                db.commit()
                print(
                    f"学号账号初始化完成：新增 {len(result['created'])} 个，保留已有 {len(result['existing'])} 个。"
                )
                print("初始密码与学号相同；仅用于课设本地联调。重复执行不会覆盖已有密码。")
        finally:
            engine.dispose()
        return
    password = os.getenv("NEXUS_BOOTSTRAP_PASSWORD") or getpass.getpass(
        "设置密码（至少 12 字符，不会显示）："
    )
    engine = build_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            begin_write(db)
            if args.command == "create-user":
                user = add_user(db, args.login, args.name, password)
                print(f"已创建账号 {user.login_name}，用户 ID={user.id}")
            else:
                if settings.environment == "production":
                    raise ValueError("生产环境不允许 seed-demo")
                names = seed_demo(db, password)
                print("已创建联调账号：" + ", ".join(names))
            db.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
