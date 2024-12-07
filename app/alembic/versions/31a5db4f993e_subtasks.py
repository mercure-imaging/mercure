"""tasks can be subtasks

Revision ID: 31a5db4f993e
Revises: 1c51b42f13d5
Create Date: 2022-05-23 20:26:09.644618

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "31a5db4f993e"
down_revision = "1c51b42f13d5"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    dialect = connection.dialect
    if dialect.name == "sqlite":
        op.execute("ALTER TABLE tasks ADD COLUMN parent_id character varying NULL")
        op.execute("ALTER TABLE task_events ADD COLUMN client_timestamp float NULL")
    else:
        op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_id character varying NULL")
        op.execute("ALTER TABLE task_events ADD COLUMN IF NOT EXISTS client_timestamp float NULL")


def downgrade():
    pass
