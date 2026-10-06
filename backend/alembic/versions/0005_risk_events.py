"""Store per-frame object-pair risk results."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("bundle_id", sa.Integer, sa.ForeignKey("frame_bundles.id"), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("captured_at_ms", sa.BigInteger, nullable=False),
        sa.Column("object1_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
        sa.Column("object2_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("ttc_s", sa.Float, nullable=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.UniqueConstraint("bundle_id", "object1_id", "object2_id"),
    )
    op.create_index("ix_risk_events_bundle_id", "risk_events", ["bundle_id"])
    op.create_index("ix_risk_events_session_id", "risk_events", ["session_id"])
    op.create_index("ix_risk_events_captured_at_ms", "risk_events", ["captured_at_ms"])


def downgrade():
    op.drop_index("ix_risk_events_captured_at_ms", table_name="risk_events")
    op.drop_index("ix_risk_events_session_id", table_name="risk_events")
    op.drop_index("ix_risk_events_bundle_id", table_name="risk_events")
    op.drop_table("risk_events")
