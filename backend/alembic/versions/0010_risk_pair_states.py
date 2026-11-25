"""Store per-pair warning level for F (warning hysteresis)."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "risk_pair_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"),
        sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"),
        sa.Column("object1_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
        sa.Column("object2_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.UniqueConstraint("session_id", "calibration_profile", "algorithm", "object1_id", "object2_id"),
    )
    op.create_index("ix_risk_pair_states_session_id", "risk_pair_states", ["session_id"])


def downgrade():
    op.drop_index("ix_risk_pair_states_session_id", table_name="risk_pair_states")
    op.drop_table("risk_pair_states")
