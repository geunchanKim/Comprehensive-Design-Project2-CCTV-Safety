"""Persist dashboard configuration and latest committed snapshot."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_states",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("calibration_profile", sa.String(16), primary_key=True),
        sa.Column("algorithm", sa.String(16), primary_key=True),
        sa.Column("map_config", sa.JSON, nullable=False),
        sa.Column("zones", sa.JSON, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=True),
        sa.Column("observations", sa.JSON, nullable=False),
    )


def downgrade():
    op.drop_table("dashboard_states")
