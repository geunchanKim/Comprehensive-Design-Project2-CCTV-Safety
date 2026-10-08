"""Store calibration profiles and profile-specific detection results."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # The legacy detection FK depends on the two-column camera primary key.
    op.drop_constraint("detections_session_id_camera_id_fkey", "detections", type_="foreignkey")
    op.add_column("cameras", sa.Column("calibration_profile", sa.String(16),
                                       nullable=False, server_default="basic"))
    op.add_column("cameras", sa.Column("validation_rmse_cm", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("validation_max_error_cm", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("validation_point_count", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.drop_constraint("cameras_pkey", "cameras", type_="primary")
    op.create_primary_key("cameras_pkey", "cameras", ["session_id", "id", "calibration_profile"])

    op.add_column("frame_bundles", sa.Column("calibration_profile", sa.String(16),
                                             nullable=False, server_default="basic"))
    op.drop_constraint("frame_bundles_session_id_pair_id_key", "frame_bundles", type_="unique")
    op.create_unique_constraint("uq_frame_bundle_profile", "frame_bundles",
                                ["session_id", "pair_id", "calibration_profile"])

    op.add_column("detections", sa.Column("calibration_profile", sa.String(16),
                                          nullable=False, server_default="basic"))
    op.drop_constraint("detections_session_id_camera_id_frame_id_track_id_key",
                       "detections", type_="unique")
    op.create_unique_constraint("uq_detection_profile", "detections",
                                ["session_id", "camera_id", "frame_id", "track_id",
                                 "calibration_profile"])
    op.create_foreign_key("fk_detection_camera_profile", "detections", "cameras",
                          ["session_id", "camera_id", "calibration_profile"],
                          ["session_id", "id", "calibration_profile"])

    op.add_column("session_settings", sa.Column("calibration_profile", sa.String(16),
                                                nullable=False, server_default="basic"))
    op.drop_constraint("session_settings_pkey", "session_settings", type_="primary")
    op.create_primary_key("session_settings_pkey", "session_settings",
                          ["session_id", "calibration_profile"])


def downgrade():
    op.drop_constraint("session_settings_pkey", "session_settings", type_="primary")
    op.create_primary_key("session_settings_pkey", "session_settings", ["session_id"])
    op.drop_column("session_settings", "calibration_profile")

    op.drop_constraint("fk_detection_camera_profile", "detections", type_="foreignkey")
    op.drop_constraint("uq_detection_profile", "detections", type_="unique")
    op.create_unique_constraint("detections_session_id_camera_id_frame_id_track_id_key",
                                "detections", ["session_id", "camera_id", "frame_id", "track_id"])
    op.drop_column("detections", "calibration_profile")

    op.drop_constraint("uq_frame_bundle_profile", "frame_bundles", type_="unique")
    op.create_unique_constraint("frame_bundles_session_id_pair_id_key", "frame_bundles",
                                ["session_id", "pair_id"])
    op.drop_column("frame_bundles", "calibration_profile")

    op.drop_constraint("cameras_pkey", "cameras", type_="primary")
    op.create_primary_key("cameras_pkey", "cameras", ["session_id", "id"])
    op.create_foreign_key("detections_session_id_camera_id_fkey", "detections", "cameras",
                          ["session_id", "camera_id"], ["session_id", "id"])
    op.drop_column("cameras", "validation_point_count")
    op.drop_column("cameras", "validation_max_error_cm")
    op.drop_column("cameras", "validation_rmse_cm")
    op.drop_column("cameras", "calibration_profile")
