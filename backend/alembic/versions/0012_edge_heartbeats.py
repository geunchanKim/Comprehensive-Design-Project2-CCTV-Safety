"""Persist edge heartbeat independently of detection delivery."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("edge_heartbeats",
                    sa.Column("session_id", sa.String(128), primary_key=True),
                    sa.Column("camera_id", sa.String(128), primary_key=True),
                    sa.Column("payload", sa.JSON, nullable=False),
                    sa.Column("received_at_ms", sa.BigInteger, nullable=False))


def downgrade():
    op.drop_table("edge_heartbeats")
