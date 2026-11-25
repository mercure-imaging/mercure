"""tasks parent_id index

Revision ID: 82e4a600e260
Revises: db4edddaf4a4
Create Date: 2026-11-25 17:05:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "82e4a600e260"
down_revision = "db4edddaf4a4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_tasks_parent_id", "tasks", ["parent_id"])


def downgrade():
    op.drop_index("ix_tasks_parent_id", table_name="tasks")
