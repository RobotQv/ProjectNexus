"""记录索引回执，约束工作流唯一性，防止删除的依赖 ID 被 SQLite 重用。

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("index_version", sa.String(128), nullable=True))
    op.add_column("documents", sa.Column("chunk_count", sa.Integer(), nullable=True))
    # 本表无指向它的外键，SQLite batch 重建不会删除上游业务数据。
    table = sa.Table("task_dependencies", sa.MetaData(), autoload_with=op.get_bind())
    # 0001 中两个旧 CHECK 未命名；显式命名后才重建，防止 Alembic 静默遗漏。
    names = {
        "predecessor_task_id != successor_task_id": "ck_dependency_not_self",
        "predecessor_required_progress BETWEEN 1 AND 100": "ck_dependency_required_progress",
    }
    for constraint in table.constraints:
        if isinstance(constraint, sa.CheckConstraint) and not constraint.name:
            constraint.name = names[str(constraint.sqltext)]
    with op.batch_alter_table(
        "task_dependencies",
        copy_from=table,
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.create_check_constraint(
            "ck_dependency_gate",
            "(successor_gate = 'progress' AND successor_gate_progress IS NOT NULL AND successor_gate_progress BETWEEN 1 AND 99) OR (successor_gate IN ('start','finish') AND successor_gate_progress IS NULL)",
        )
    # 使用唯一索引，避免重建已被 Suggestion 引用的 workflow_runs 表。
    op.create_index(
        "uq_workflow_document_kind",
        "workflow_runs",
        ["document_id", "document_version", "kind"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_workflow_document_kind", table_name="workflow_runs")
    with op.batch_alter_table("task_dependencies", recreate="always") as batch:
        batch.drop_constraint("ck_dependency_gate", type_="check")
    op.drop_column("documents", "chunk_count")
    op.drop_column("documents", "index_version")
