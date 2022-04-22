"""empty message

Revision ID: 6041e3878f32
Revises: af102cd510bd
Create Date: 2022-04-22 16:18:48.034963

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "6041e3878f32"
down_revision = "af102cd510bd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tests",
        sa.Column("id", sa.String()),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("time_begin", sa.DateTime(), nullable=True),
        sa.Column("time_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("data", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("tests")
