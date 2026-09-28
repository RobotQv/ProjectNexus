"""对话建议、提交追溯、完整任务历史；保留已有业务数据。

Revision ID: 0003
Revises: 0002
"""

import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("workflow_runs") as b:
        b.alter_column("document_id", existing_type=sa.Integer(), nullable=True)
        b.alter_column("document_version", existing_type=sa.Integer(), nullable=True)
        b.add_column(sa.Column("submitted_by", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_workflow_submitter", "users", ["submitted_by"], ["id"])
        b.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        b.add_column(
            sa.Column("source_kind", sa.String(32), nullable=False, server_default="document")
        )
        b.add_column(sa.Column("input_text", sa.Text(), nullable=True))
        b.add_column(sa.Column("response_data", sa.JSON(), nullable=True))
        b.add_column(sa.Column("request_key", sa.String(64), nullable=True))
    bind = op.get_bind()
    # 旧记录没有可靠提交身份时保留 null，不把上传者冒充成发起提取者。
    bind.execute(
        sa.text("UPDATE workflow_runs SET created_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    )
    with op.batch_alter_table("workflow_runs") as b:
        b.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
    op.create_index(
        "uq_assistant_request",
        "workflow_runs",
        ["project_id", "submitted_by", "request_key"],
        unique=True,
    )
    with op.batch_alter_table("suggestions") as b:
        b.add_column(sa.Column("submitted_by", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_suggestion_submitter", "users", ["submitted_by"], ["id"])
        b.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        b.add_column(
            sa.Column("source_kind", sa.String(32), nullable=False, server_default="document")
        )
        b.add_column(sa.Column("original_payload", sa.JSON(), nullable=True))
        b.add_column(sa.Column("review_note", sa.Text(), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE suggestions SET created_at = CURRENT_TIMESTAMP, original_payload = proposed_payload"
        )
    )
    with op.batch_alter_table("suggestions") as b:
        b.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
    with op.batch_alter_table("analysis_runs") as b:
        b.add_column(sa.Column("trigger_job_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_analysis_trigger", "jobs", ["trigger_job_id"], ["id"])
        b.create_unique_constraint("uq_analysis_trigger", ["trigger_job_id"])
    op.create_table(
        "task_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("suggestions.id"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("task_id", "version"),
    )
    op.create_index("ix_task_history_project_id", "task_history", ["project_id"])
    op.create_index("ix_task_history_task_id", "task_history", ["task_id"])
    tasks = sa.Table("tasks", sa.MetaData(), autoload_with=bind)
    history = sa.Table("task_history", sa.MetaData(), autoload_with=bind)

    def encode(value):
        if isinstance(value, datetime):
            return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    for row in bind.execute(sa.select(tasks)).mappings():
        bind.execute(
            history.insert().values(
                project_id=row["project_id"],
                task_id=row["id"],
                version=row["version"],
                snapshot=json.loads(json.dumps(dict(row), default=encode)),
                actor_id=None,
                source="migration_baseline",
                suggestion_id=None,
                recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT COUNT(*) FROM workflow_runs WHERE document_id IS NULL")):
        raise RuntimeError("已有对话记录，不能无损回退到仅文档工作流；请保留 0003")
    op.drop_table("task_history")
    with op.batch_alter_table("analysis_runs") as b:
        b.drop_constraint("uq_analysis_trigger", type_="unique")
        b.drop_constraint("fk_analysis_trigger", type_="foreignkey")
        b.drop_column("trigger_job_id")
    with op.batch_alter_table("suggestions") as b:
        b.drop_constraint("fk_suggestion_submitter", type_="foreignkey")
        for name in (
            "submitted_by",
            "created_at",
            "submitted_at",
            "source_kind",
            "original_payload",
            "review_note",
        ):
            b.drop_column(name)
    op.drop_index("uq_assistant_request", table_name="workflow_runs")
    with op.batch_alter_table("workflow_runs") as b:
        b.drop_constraint("fk_workflow_submitter", type_="foreignkey")
        for name in (
            "submitted_by",
            "created_at",
            "source_kind",
            "input_text",
            "response_data",
            "request_key",
        ):
            b.drop_column(name)
        b.alter_column("document_id", existing_type=sa.Integer(), nullable=False)
        b.alter_column("document_version", existing_type=sa.Integer(), nullable=False)
