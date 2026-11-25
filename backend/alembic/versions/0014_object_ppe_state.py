"""Persist PPE smoothing with the global object and its experiment condition."""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("global_objects", sa.Column("ppe_state", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("global_objects", "ppe_state")
