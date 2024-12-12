"""processor logs

Revision ID: e90a5c7c6211
Revises: 31a5db4f993e
Create Date: 2022-06-28 17:18:27.570620

"""
from typing import Any, List

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = "e90a5c7c6211"
down_revision = "31a5db4f993e"
branch_labels = None
depends_on = None

tables: List[Any] = []


def create_table(table_name, *params) -> None:
    global tables
    if not tables:
        conn = op.get_bind()
        inspector = Inspector.from_engine(conn)
        tables = inspector.get_table_names()

    if table_name in tables:
        return
    op.create_table(table_name, *params)


def upgrade():
    create_table(
        "processor_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String, sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("module_name", sa.String, nullable=True),
        sa.Column("logs", sa.String, nullable=True),
        sa.Column("time", sa.DateTime, nullable=True),
    )


def downgrade():
    pass
