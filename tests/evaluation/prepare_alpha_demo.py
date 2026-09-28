"""创建隔离演示数据。只允许空库，随机密码仅写入被忽略的本地 data 目录。"""

import json
import secrets
from pathlib import Path

from app.cli import migrate, seed_demo
from app.db import begin_write, build_engine, session_factory


def main():
    root = Path("data/alpha-demo").resolve()
    root.mkdir(parents=True, exist_ok=True)
    database = "sqlite:///" + (root / "demo.db").as_posix()
    password = secrets.token_urlsafe(24)
    migrate(database)
    engine = build_engine(database)
    try:
        with session_factory(engine)() as db:
            begin_write(db)
            users = seed_demo(db, password)
            db.commit()
        # 演示账号不是实际组员账号，凭证不进入 Git 和验收材料包。
        (root / "local-credentials.json").write_text(
            json.dumps({"logins": users, "password": password}, ensure_ascii=False),
            encoding="utf-8",
        )
        print("isolated demo initialized; credentials stored locally (not printed)")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
