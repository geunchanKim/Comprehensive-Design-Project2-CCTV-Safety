"""Persist alert occurrences and acknowledgement independently of objects."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_alerts",
        sa.Column("alert_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("calibration_profile", sa.String(16), nullable=False),
        sa.Column("algorithm", sa.String(16), nullable=False),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("active_key", sa.String(160), nullable=True),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("reached_danger", sa.Boolean, nullable=False),
        sa.Column("started_at_ms", sa.BigInteger, nullable=False),
        sa.Column("last_seen_at_ms", sa.BigInteger, nullable=False),
        sa.Column("ended_at_ms", sa.BigInteger, nullable=True),
        sa.Column("acknowledged_at_ms", sa.BigInteger, nullable=True),
        sa.Column("action", sa.String(16), nullable=True),
        sa.UniqueConstraint("session_id", "calibration_profile", "algorithm", "active_key"),
    )
    op.create_index("ix_dashboard_alerts_session_id", "dashboard_alerts", ["session_id"])


def downgrade():
    op.drop_index("ix_dashboard_alerts_session_id", table_name="dashboard_alerts")
    op.drop_table("dashboard_alerts")
