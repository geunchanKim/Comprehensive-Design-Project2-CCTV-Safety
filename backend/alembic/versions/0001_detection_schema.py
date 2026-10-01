"""Create camera calibration, frame bundle, detection, and track link tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("cameras", sa.Column("id", sa.String(64), primary_key=True),
                    sa.Column("image_width", sa.Integer, nullable=False), sa.Column("image_height", sa.Integer, nullable=False),
                    sa.Column("intrinsic_matrix", sa.JSON, nullable=False), sa.Column("distortion_coefficients", sa.JSON, nullable=False),
                    sa.Column("rotation_matrix", sa.JSON, nullable=False), sa.Column("translation_vector", sa.JSON, nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("frame_bundles", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("sync_delta_ms", sa.Integer, nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("global_objects", sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
                    sa.Column("cls", sa.String(16), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("track_links", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("object_id", sa.Integer, sa.ForeignKey("global_objects.id"), nullable=False),
                    sa.Column("camera1_id", sa.String(64), nullable=False), sa.Column("camera1_track_id", sa.Integer, nullable=False),
                    sa.Column("camera2_id", sa.String(64), nullable=False), sa.Column("camera2_track_id", sa.Integer, nullable=False),
                    sa.Column("cls", sa.String(16), nullable=False),
                    sa.UniqueConstraint("camera1_id", "camera1_track_id", "camera2_id", "camera2_track_id"))
    op.create_index("ix_track_links_object_id", "track_links", ["object_id"])
    op.create_table("detections", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("bundle_id", sa.Integer, sa.ForeignKey("frame_bundles.id"), nullable=False),
                    sa.Column("camera_id", sa.String(64), sa.ForeignKey("cameras.id"), nullable=False),
                    sa.Column("frame_id", sa.Integer, nullable=False), sa.Column("captured_at_ms", sa.BigInteger, nullable=False),
                    sa.Column("track_id", sa.Integer, nullable=False), sa.Column("object_id", sa.Integer),
                    sa.Column("cls", sa.String(16), nullable=False), sa.Column("confidence", sa.Float, nullable=False),
                    sa.Column("bbox", sa.JSON, nullable=False), sa.Column("foot_pixel", sa.JSON, nullable=False),
                    sa.Column("world_x", sa.Float), sa.Column("world_y", sa.Float), sa.Column("world_z", sa.Float),
                    sa.UniqueConstraint("camera_id", "frame_id", "track_id"))
    for name, columns in (("ix_detections_bundle_id", ["bundle_id"]), ("ix_detections_camera_id", ["camera_id"]),
                          ("ix_detections_frame_id", ["frame_id"]), ("ix_detections_captured_at_ms", ["captured_at_ms"]),
                          ("ix_detections_object_id", ["object_id"])):
        op.create_index(name, "detections", columns)


def downgrade():
    op.drop_table("detections")
    op.drop_table("track_links")
    op.drop_table("global_objects")
    op.drop_table("frame_bundles")
    op.drop_table("cameras")
