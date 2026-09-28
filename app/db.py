"""SQLite 连接与事务边界。每个请求 / Job 都使用独立 Session。"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite 不保留时区；数据库存 UTC，API 读回时显式标注 UTC。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime must include timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value else None


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    url = make_url(database_url)
    if url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _):
        # 显式 BEGIN 确保连续读取位于同一快照；不使用 sqlite3 legacy 自动事务。
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql(
            "BEGIN IMMEDIATE" if connection.get_execution_options().get("sqlite_write") else "BEGIN"
        )

    return engine


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def begin_write(session):
    """写事务先获得 SQLite 写锁，随后才读版本 / 图；防止并发形成环或重复确认。

    调用方必须在业务检查前调用；先前的鉴权只读事务会结束，项目权限在写锁内复核。
    """
    session.rollback()
    session.connection(execution_options={"sqlite_write": True})
