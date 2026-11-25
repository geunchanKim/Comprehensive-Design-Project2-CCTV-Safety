"""Fill short chair occlusions from durable, real two-camera observations."""
import os

from sqlalchemy import func, select

try:
    from .models import Detection
except ImportError:
    from models import Detection

CHAIR_HOLD_MS = int(os.getenv("CHAIR_HOLD_MS", "3000"))
if not 0 <= CHAIR_HOLD_MS <= 10000:
    raise ValueError("CHAIR_HOLD_MS must be between 0 and 10000")


def hold_chairs(db, session_id, profile, algorithm, timestamp_ms, matches):
    if CHAIR_HOLD_MS == 0:
        return
    # Flush real observations in this transaction. Synthetic positions are never
    # stored as detections, so holding cannot renew its own expiry.
    db.flush()
    ranked = select(
        Detection.id.label("id"),
        func.row_number().over(
            partition_by=Detection.object_id,
            order_by=(Detection.captured_at_ms.desc(), Detection.id.desc()),
        ).label("rank"),
    ).where(
        Detection.session_id == session_id,
        Detection.calibration_profile == profile,
        Detection.algorithm == algorithm,
        Detection.cls == "chair",
        Detection.object_id.is_not(None),
        Detection.world_x.is_not(None),
        Detection.captured_at_ms >= timestamp_ms - CHAIR_HOLD_MS,
        Detection.captured_at_ms <= timestamp_ms,
    ).subquery()
    visible = {m["object_id"] for m in matches}
    rows = db.scalars(select(Detection).join(ranked, Detection.id == ranked.c.id)
                      .where(ranked.c.rank == 1).order_by(Detection.object_id))
    for row in rows:
        if row.object_id in visible:
            continue
        matches.append({
            "object_id": row.object_id, "cls": "chair",
            "world": {"x": row.world_x, "y": row.world_y, "z": row.world_z},
            "velocity": None, "camera_tracks": {}, "foot_pixels": {},
            "observations": [], "position_source": "held", "matching_method": "held",
            "position_observed_at_ms": row.captured_at_ms,
        })
