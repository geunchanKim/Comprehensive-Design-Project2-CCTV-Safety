"""Store per-object Kalman filter state."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "object_motion_states",
        sa.Column("object_id", sa.Integer, sa.ForeignKey("global_objects.id"), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("mean", sa.JSON, nullable=False),
        sa.Column("covariance", sa.JSON, nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_object_motion_states_session_id", "object_motion_states", ["session_id"])


def downgrade():
    op.drop_index("ix_object_motion_states_session_id", table_name="object_motion_states")
    op.drop_table("object_motion_states")
