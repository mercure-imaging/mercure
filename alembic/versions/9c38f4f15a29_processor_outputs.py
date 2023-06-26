"""processor outputs

Revision ID: 9c38f4f15a29
Revises: e90a5c7c6211
Create Date: 2022-08-11 20:20:25.337807

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision = "9c38f4f15a29"
down_revision = "e90a5c7c6211"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "processor_outputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("time", sa.DateTime(timezone=True), server_default=func.now()),
        sa.Column("task_id", sa.String, sa.ForeignKey("tasks.id"),nullable=True),
        sa.Column("task_acc", sa.String),
        sa.Column("task_mrn", sa.String),
        sa.Column("module", sa.String),
        sa.Column("index", sa.Integer),
        sa.Column("settings", postgresql.JSONB),
        sa.Column("output", postgresql.JSONB),

    )


def downgrade():
    op.drop_table("processor_outputs")
    pass
