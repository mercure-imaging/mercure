"""remove task_fk

Revision ID: af102cd510bd
Revises: ee4575e2cf40
Create Date: 2022-04-20 22:01:30.081888

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "af102cd510bd"
down_revision = "ee4575e2cf40"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    dialect = connection.dialect
    if dialect.name == "sqlite":
        pass
    else:
        op.drop_constraint("task_events_task_fk", "task_events", type_="foreignkey")


def downgrade():
    pass  # can't actually add the constraint back in if it's been violated since it was dropped...
