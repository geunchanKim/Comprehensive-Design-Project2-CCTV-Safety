"""Store the source of the foot pixel used for triangulation."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "detections",
        sa.Column("foot_src", sa.String(16), nullable=False, server_default="box"),
    )


def downgrade():
    op.drop_column("detections", "foot_src")
