from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.cli import ROOT, migrate
from app.db import build_engine


def test_migration_roundtrip_and_constraints(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    migrate(url)
    engine = build_engine(url)
    inspector = inspect(engine)
    assert len(inspector.get_table_names()) == 16
    assert "task_history" in inspector.get_table_names()
    assert len(inspector.get_check_constraints("task_dependencies")) == 3
    assert "uq_workflow_document_kind" in {
        i["name"] for i in inspector.get_indexes("workflow_runs")
    }
    with engine.connect() as conn:
        ddl = conn.scalar(text("SELECT sql FROM sqlite_master WHERE name='task_dependencies'"))
        assert "AUTOINCREMENT" in ddl
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert len(inspect(engine).get_table_names()) == 16
    engine.dispose()
