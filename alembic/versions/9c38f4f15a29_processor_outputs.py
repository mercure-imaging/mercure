"""processor outputs

Revision ID: 9c38f4f15a29
Revises: e90a5c7c6211
Create Date: 2022-08-11 20:20:25.337807

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "9c38f4f15a29"
down_revision = "e90a5c7c6211"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "processor_outputs",
        sa.Column("task_id", sa.String, primary_key=True),
        sa.Column("output", postgresql.JSONB),
    )


def downgrade():
    pass
