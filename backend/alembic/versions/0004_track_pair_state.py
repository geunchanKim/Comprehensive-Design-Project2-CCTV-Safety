"""Persist cross-camera track-pair hysteresis state."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "track_pair_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("cls", sa.String(16), nullable=False),
        sa.Column("camera1_id", sa.String(64), nullable=False),
        sa.Column("camera1_track_id", sa.Integer, nullable=False),
        sa.Column("camera2_id", sa.String(64), nullable=False),
        sa.Column("camera2_track_id", sa.Integer, nullable=False),
        sa.Column("challenger_track_id", sa.Integer, nullable=True),
        sa.Column("challenger_streak", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_pair_id", sa.BigInteger, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "cls", "camera1_id", "camera1_track_id"),
    )
    op.create_index("ix_track_pair_states_session_id", "track_pair_states", ["session_id"])


def downgrade():
    op.drop_index("ix_track_pair_states_session_id", table_name="track_pair_states")
    op.drop_table("track_pair_states")
