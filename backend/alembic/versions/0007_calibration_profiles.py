"""Store independent calibration and algorithm experiment conditions."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _named(kind, table, columns=None, referred_table=None):
    inspector = sa.inspect(op.get_bind())
    if kind == "primary":
        return inspector.get_pk_constraint(table)["name"]
    candidates = (inspector.get_unique_constraints(table) if kind == "unique"
                  else inspector.get_foreign_keys(table))
    expected = set(columns or [])
    for item in candidates:
        actual = item.get("column_names") or item.get("constrained_columns") or []
        if set(actual) == expected and (not referred_table or item.get("referred_table") == referred_table):
            return item["name"]
    raise RuntimeError(f"{kind} constraint not found on {table}: {sorted(expected)}")


def upgrade():
    op.drop_constraint(_named("foreign", "detections", ["session_id", "camera_id"], "cameras"),
                       "detections", type_="foreignkey")
    op.add_column("cameras", sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"))
    op.add_column("cameras", sa.Column("validation_rmse_cm", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("validation_max_error_cm", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("validation_point_count", sa.Integer(), nullable=False, server_default="0"))
    op.drop_constraint(_named("primary", "cameras"), "cameras", type_="primary")
    op.create_primary_key("cameras_pkey", "cameras", ["session_id", "id", "calibration_profile"])

    op.add_column("frame_bundles", sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"))
    op.add_column("frame_bundles", sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"))
    op.add_column("frame_bundles", sa.Column("source_frames", sa.JSON(), nullable=False, server_default="[]"))
    op.drop_constraint(_named("unique", "frame_bundles", ["session_id", "pair_id"]), "frame_bundles", type_="unique")
    op.create_unique_constraint("uq_frame_bundle_condition", "frame_bundles",
        ["session_id", "pair_id", "calibration_profile", "algorithm"])

    op.add_column("detections", sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"))
    op.add_column("detections", sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"))
    op.drop_constraint(_named("unique", "detections", ["session_id", "camera_id", "frame_id", "track_id"]),
                       "detections", type_="unique")
    op.create_unique_constraint("uq_detection_condition", "detections",
        ["session_id", "camera_id", "frame_id", "track_id", "calibration_profile", "algorithm"])
    op.create_foreign_key("fk_detection_camera_profile", "detections", "cameras",
        ["session_id", "camera_id", "calibration_profile"], ["session_id", "id", "calibration_profile"])

    op.add_column("session_settings", sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"))
    op.add_column("session_settings", sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"))
    op.drop_constraint(_named("primary", "session_settings"), "session_settings", type_="primary")
    op.create_primary_key("session_settings_pkey", "session_settings", ["session_id", "calibration_profile", "algorithm"])

    for table in ("global_objects", "track_links", "object_motion_states", "track_pair_states"):
        op.add_column(table, sa.Column("calibration_profile", sa.String(16), nullable=False, server_default="basic"))
        op.add_column(table, sa.Column("algorithm", sa.String(16), nullable=False, server_default="baseline"))
    op.drop_constraint(_named("unique", "track_links", ["session_id", "camera1_id", "camera1_track_id",
                       "camera2_id", "camera2_track_id"]), "track_links", type_="unique")
    op.create_unique_constraint("uq_track_link_condition", "track_links",
        ["session_id", "calibration_profile", "algorithm", "camera1_id", "camera1_track_id",
         "camera2_id", "camera2_track_id"])
    op.drop_constraint(_named("unique", "track_pair_states",
                       ["session_id", "cls", "camera1_id", "camera1_track_id"]),
                       "track_pair_states", type_="unique")
    op.create_unique_constraint("uq_track_pair_condition", "track_pair_states",
        ["session_id", "calibration_profile", "algorithm", "cls", "camera1_id", "camera1_track_id"])


def downgrade():
    op.drop_constraint("uq_track_pair_condition", "track_pair_states", type_="unique")
    op.create_unique_constraint("uq_track_pair_legacy", "track_pair_states", ["session_id", "cls", "camera1_id", "camera1_track_id"])
    op.drop_constraint("uq_track_link_condition", "track_links", type_="unique")
    op.create_unique_constraint("uq_track_link_legacy", "track_links",
        ["session_id", "camera1_id", "camera1_track_id", "camera2_id", "camera2_track_id"])
    for table in ("track_pair_states", "object_motion_states", "track_links", "global_objects"):
        op.drop_column(table, "algorithm")
        op.drop_column(table, "calibration_profile")
    op.drop_constraint("session_settings_pkey", "session_settings", type_="primary")
    op.create_primary_key("session_settings_pkey", "session_settings", ["session_id"])
    op.drop_column("session_settings", "algorithm")
    op.drop_column("session_settings", "calibration_profile")
    op.drop_constraint("fk_detection_camera_profile", "detections", type_="foreignkey")
    op.drop_constraint("uq_detection_condition", "detections", type_="unique")
    op.create_unique_constraint("uq_detection_legacy", "detections", ["session_id", "camera_id", "frame_id", "track_id"])
    op.drop_column("detections", "algorithm")
    op.drop_column("detections", "calibration_profile")
    op.drop_constraint("uq_frame_bundle_condition", "frame_bundles", type_="unique")
    op.create_unique_constraint("uq_frame_bundle_legacy", "frame_bundles", ["session_id", "pair_id"])
    op.drop_column("frame_bundles", "algorithm")
    op.drop_column("frame_bundles", "source_frames")
    op.drop_column("frame_bundles", "calibration_profile")
    op.drop_constraint("cameras_pkey", "cameras", type_="primary")
    op.create_primary_key("cameras_pkey", "cameras", ["session_id", "id"])
    op.create_foreign_key("fk_detection_camera_legacy", "detections", "cameras",
                          ["session_id", "camera_id"], ["session_id", "id"])
    op.drop_column("cameras", "validation_point_count")
    op.drop_column("cameras", "validation_max_error_cm")
    op.drop_column("cameras", "validation_rmse_cm")
    op.drop_column("cameras", "calibration_profile")
