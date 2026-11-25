"""Bounded application memory for CSV exports; no DB cursor survives the request."""
import csv
import json
from tempfile import SpooledTemporaryFile
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask

try:
    from .models import Detection, FrameBundle, RiskEvent
except ImportError:
    from models import Detection, FrameBundle, RiskEvent

BATCH_ROWS = 500
SPOOL_BYTES = 1024 * 1024
CHUNK_CHARS = 64 * 1024
FIELDS = ["record_type", "pair_id", "frame_id", "timestamp_ms", "object_id", "object2_id", "cls",
          "x", "y", "z", "distance_m", "ttc_s", "level", "settings"]


def write_results(db, output, session_id, profile, algorithm, settings):
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    settings_json = json.dumps(settings, sort_keys=True)
    # Keep the earliest camera observation per bundle/object, as before. SQL
    # removes duplicates without a Python set growing with the entire session.
    ranked = select(
        FrameBundle.pair_id, Detection.frame_id,
        Detection.captured_at_ms.label("timestamp_ms"), Detection.object_id,
        Detection.cls, Detection.world_x.label("x"), Detection.world_y.label("y"),
        Detection.world_z.label("z"), Detection.bundle_id, Detection.camera_id,
        Detection.track_id,
        func.row_number().over(
            partition_by=(Detection.bundle_id, Detection.object_id),
            order_by=(Detection.captured_at_ms, Detection.camera_id, Detection.track_id),
        ).label("rank"),
    ).join(FrameBundle, Detection.bundle_id == FrameBundle.id).where(
        Detection.session_id == session_id, Detection.calibration_profile == profile,
        Detection.algorithm == algorithm, Detection.object_id.is_not(None),
    ).subquery()
    positions = select(*(ranked.c[name] for name in (
        "pair_id", "frame_id", "timestamp_ms", "object_id", "cls", "x", "y", "z")),
    ).where(ranked.c.rank == 1).order_by(
        ranked.c.timestamp_ms, ranked.c.bundle_id, ranked.c.camera_id, ranked.c.track_id)
    risks = select(
        FrameBundle.pair_id, RiskEvent.captured_at_ms.label("timestamp_ms"),
        RiskEvent.object1_id.label("object_id"), RiskEvent.object2_id.label("object2_id"),
        RiskEvent.distance_m, RiskEvent.ttc_s, RiskEvent.level,
    ).join(FrameBundle, RiskEvent.bundle_id == FrameBundle.id).where(
        RiskEvent.session_id == session_id, FrameBundle.calibration_profile == profile,
        FrameBundle.algorithm == algorithm,
    ).order_by(RiskEvent.captured_at_ms, RiskEvent.id)
    for kind, query in (("position", positions), ("risk", risks)):
        with db.execute(query.execution_options(yield_per=BATCH_ROWS)) as result:
            for row in result.mappings():
                writer.writerow({"record_type": kind, **row, "settings": settings_json})


def file_chunks(output):
    try:
        while chunk := output.read(CHUNK_CHARS):
            yield chunk
    finally:
        output.close()


def export_response(db, session_id, profile, algorithm, settings):
    # Finish DB work before returning: slow clients do not hold a cursor open,
    # and query/disk errors can still produce a normal HTTP error response.
    output = SpooledTemporaryFile(max_size=SPOOL_BYTES, mode="w+", encoding="utf-8", newline="")
    try:
        write_results(db, output, session_id, profile, algorithm, settings)
        output.seek(0)
        return StreamingResponse(
            file_chunks(output), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=\""
                     + quote(f"{session_id}-results.csv", safe="") + "\"; filename*=UTF-8''"
                     + quote(f"{session_id}-results.csv", safe="")},
            background=BackgroundTask(output.close),
        )
    except BaseException:
        output.close()
        raise
