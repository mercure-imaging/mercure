"""self_tests for study

Revision ID: 1c51b42f13d5
Revises: 6041e3878f32
Create Date: 2022-05-23 15:58:27.767570

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c51b42f13d5"
down_revision = "6041e3878f32"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    dialect = connection.dialect
    if dialect.name == "sqlite":
        op.execute("ALTER TABLE tests ADD COLUMN rule_type character varying NULL")    
    else:
        op.execute("ALTER TABLE tests ADD COLUMN IF NOT EXISTS rule_type character varying NULL")


def downgrade():
    pass
