"""task_events task_id index

Revision ID: db4edddaf4a4
Revises: 9c38f4f15a29
Create Date: 2026-11-23 21:55:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "db4edddaf4a4"
down_revision = "9c38f4f15a29"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])


def downgrade():
    op.drop_index("ix_task_events_task_id", table_name="task_events")
