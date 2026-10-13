"""Store floor-plane person tracks for C (floor tracking)."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "floor_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"),
        sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"),
        sa.Column("cls", sa.String(16), nullable=False),
        sa.Column("object_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
        sa.Column("mean", sa.JSON, nullable=False),
        sa.Column("covariance", sa.JSON, nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger, nullable=False),
        sa.Column("missed", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_floor_tracks_session_id", "floor_tracks", ["session_id"])
    op.create_index("ix_floor_tracks_object_id", "floor_tracks", ["object_id"])


def downgrade():
    op.drop_index("ix_floor_tracks_object_id", table_name="floor_tracks")
    op.drop_index("ix_floor_tracks_session_id", table_name="floor_tracks")
    op.drop_table("floor_tracks")
