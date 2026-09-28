import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv

from app import models  # noqa: F401 — 注册全部业务表
from app.db import Base, build_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
load_dotenv()
url = (
    config.attributes.get("database_url")
    or os.getenv("NEXUS_DATABASE_URL")
    or config.get_main_option("sqlalchemy.url")
)
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(url)
    with engine.connect() as connection:
        # SQLite batch 需要重建被引用的表。仅迁移连接临时关闭 FK；
        # 所有迁移在一个事务中完成，提交前检查全库引用，失败全部回滚。
        cursor = connection.connection.dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    render_as_batch=True,
                    compare_type=True,
                    transactional_ddl=True,
                )
                with context.begin_transaction():
                    context.run_migrations()
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                    raise RuntimeError("迁移后外键检查失败，已回滚")
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    engine.dispose()
