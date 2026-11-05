"""Database-backed dashboard delivery. No process-local publication counters."""
import asyncio
import json
import math
import os
import time
from uuid import uuid4

import numpy as np
import cv2
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

try:
    from .dashboard import ContractModel, DashboardMap, DashboardSnapshot, ZoneSet, build_snapshot
    from .database import SessionLocal, get_db
    from .models import Camera, DashboardState
    from .schemas import CalibrationProfile, DetectionBundleOut
except ImportError:
    from dashboard import ContractModel, DashboardMap, DashboardSnapshot, ZoneSet, build_snapshot
    from database import SessionLocal, get_db
    from models import Camera, DashboardState
    from schemas import CalibrationProfile, DetectionBundleOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardConfiguration(ContractModel):
    map: DashboardMap
    zones: ZoneSet


def condition(session_id: str | None = None, calibration_profile: CalibrationProfile | None = None,
              algorithm: str | None = None):
    values = (session_id, calibration_profile, algorithm)
    if any(value is not None for value in values) and not all(values):
        raise HTTPException(422, "specify session_id, calibration_profile and algorithm together")
    if not any(values):
        values = tuple(os.getenv(key) for key in (
            "DASHBOARD_SESSION_ID", "DASHBOARD_CALIBRATION_PROFILE", "DASHBOARD_ALGORITHM"))
        if not all(values):
            raise HTTPException(503, "dashboard operating condition is not configured")
    try:
        # Import lazily to avoid the ingestion/router import cycle.
        try:
            from .api import algorithm_features
        except ImportError:
            from api import algorithm_features
        algorithm_features(values[2])
        if values[1] not in {"basic", "precise"} or len(values[0]) > 128:
            raise ValueError("invalid session/profile")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return values


def state_query(key):
    return select(DashboardState).where(
        DashboardState.session_id == key[0], DashboardState.calibration_profile == key[1],
        DashboardState.algorithm == key[2])


def require_state(db, key):
    row = db.scalar(state_query(key))
    if row is None:
        raise HTTPException(404, "dashboard map is not configured for this condition")
    return row


def expected_revision(value):
    if value is None:
        raise HTTPException(428, "If-Match configuration revision is required")
    try:
        return int(value.strip('"'))
    except ValueError as exc:
        raise HTTPException(422, "If-Match must be a quoted integer revision") from exc


@router.put("/configuration", status_code=201)
def configure(body: DashboardConfiguration, key=Depends(condition), db: Session = Depends(get_db)):
    if body.map.coordinate_frame_id != body.zones.coordinate_frame_id:
        raise HTTPException(422, "zone and map coordinate frames must match")
    if db.scalar(state_query(key)) is not None:
        raise HTTPException(409, "configuration exists; use the versioned zones API")
    row = DashboardState(session_id=key[0], calibration_profile=key[1], algorithm=key[2],
                         map_config=body.map.model_dump(mode="json"), zones=body.zones.model_dump(mode="json"),
                         revision=1, stream_id=str(uuid4()), seq=0, observations={})
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "configuration already exists") from exc
    return Response(body.model_dump_json(), status_code=201, media_type="application/json", headers={"ETag": '"1"'})


@router.get("/zones", response_model=ZoneSet)
def get_zones(key=Depends(condition), db: Session = Depends(get_db)):
    row = require_state(db, key)
    return Response(json.dumps(row.zones), media_type="application/json", headers={"ETag": f'"{row.revision}"'})


@router.put("/zones", response_model=ZoneSet)
def put_zones(body: ZoneSet, key=Depends(condition), db: Session = Depends(get_db),
              if_match: str | None = Header(default=None)):
    revision = expected_revision(if_match)
    row = require_state(db, key)
    if body.coordinate_frame_id != row.map_config["coordinate_frame_id"]:
        raise HTTPException(422, "zone and map coordinate frames must match")
    changed = db.execute(update(DashboardState).where(
        DashboardState.session_id == key[0], DashboardState.calibration_profile == key[1],
        DashboardState.algorithm == key[2], DashboardState.revision == revision,
    ).values(zones=body.model_dump(mode="json"), revision=revision + 1,
             snapshot=None).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(412, "configuration revision changed")
    db.commit()
    # Old decisions are invalid after edits. Wait for the next successful detection.
    return Response(body.model_dump_json(), media_type="application/json", headers={"ETag": f'"{revision + 1}"'})


@router.get("/snapshot", response_model=DashboardSnapshot, responses={204: {"description": "No snapshot"}})
def get_snapshot(key=Depends(condition), db: Session = Depends(get_db)):
    row = db.scalar(state_query(key))
    if row is None or row.snapshot is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return Response(json.dumps(row.snapshot), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/events")
def events(key=Depends(condition)):
    def latest():
        with SessionLocal() as db:
            row = db.scalar(state_query(key))
            return row.snapshot if row else None

    async def stream():
        previous = None
        heartbeat = time.monotonic()
        while True:
            snapshot = await run_in_threadpool(latest)
            if snapshot and (snapshot["stream_id"], snapshot["seq"]) != previous:
                previous = snapshot["stream_id"], snapshot["seq"]
                yield f"event: snapshot\nid: {previous[0]}:{previous[1]}\ndata: {json.dumps(snapshot)}\n\n"
                heartbeat = time.monotonic()
            elif time.monotonic() - heartbeat >= 15:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.25)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def publish(db, body, algorithm, result):
    """Called before detection commit; failures roll back both result and snapshot."""
    key = body.session_id, body.calibration_profile, algorithm
    row = db.scalar(state_query(key).with_for_update())
    if row is None:
        return
    now = time.time_ns() // 1_000_000
    row.seq += 1
    row.snapshot = build_snapshot(
        DetectionBundleOut.model_validate(result), algorithm=algorithm,
        captured_at_ms=max(frame.ts for frame in body.frames), emitted_at_ms=now,
        zones=ZoneSet.model_validate(row.zones), map_config=DashboardMap.model_validate(row.map_config),
        stream_id=row.stream_id, seq=row.seq, evaluate_zones=True,
    ).model_dump(mode="json")
    row.observations = {**row.observations, **{
        frame.camera_id: {"server_observed_at_ms": now, "captured_at_ms": frame.ts,
                          "frame_id": frame.frame_id, "detection_count": len(frame.detections)}
        for frame in body.frames}}


def reset_stream(db, session_id, profile, algorithm):
    row = db.scalar(state_query((session_id, profile, algorithm)).with_for_update())
    if row is not None:
        row.stream_id = str(uuid4())
        row.seq = 0
        row.snapshot = None
        row.observations = {}


@router.get("/cameras")
def cameras(key=Depends(condition), db: Session = Depends(get_db)):
    row = require_state(db, key)
    now = time.time_ns() // 1_000_000
    result = []
    for camera in db.scalars(select(Camera).where(Camera.session_id == key[0], Camera.calibration_profile == key[1]).order_by(Camera.id)):
        rotation = np.asarray(camera.rotation_matrix, dtype=float)
        center = -rotation.T @ np.asarray(camera.translation_vector, dtype=float)
        k = np.asarray(camera.intrinsic_matrix, dtype=float)
        # Project center/edge viewing rays into the same world XY plane as the map.
        pixels = np.array([[[u, camera.image_height / 2]]
                           for u in (0, camera.image_width / 2, camera.image_width)], dtype=float)
        distortion = (np.zeros(5) if camera.calibration_profile == "basic"
                      else np.asarray(camera.distortion_coefficients, dtype=float))
        normalized = cv2.undistortPoints(pixels, k, distortion).reshape(-1, 2)
        rays = [rotation.T @ np.array([*point, 1.0]) for point in normalized]
        lengths = [float(np.linalg.norm(ray[:2])) for ray in rays]
        yaw = math.degrees(math.atan2(rays[1][1], rays[1][0])) if lengths[1] > 1e-9 else None
        fov = (math.degrees(math.acos(float(np.clip(np.dot(rays[0][:2], rays[2][:2]) /
                                                  (lengths[0] * lengths[2]), -1, 1))))
               if min(lengths) > 1e-9 else None)
        observed = row.observations.get(camera.id)
        result.append({"camera_id": camera.id, "world": dict(zip(("x", "y", "z"), center.tolist())),
                       "yaw_deg": yaw, "horizontal_fov_deg": fov,
                       "frame_status": ("recent" if now - observed["server_observed_at_ms"] < 1000 else "stale")
                       if observed else "unknown", "online": None, "last_frame": observed})
    return {"coordinate_frame_id": row.map_config["coordinate_frame_id"], "cameras": result,
            "observed_at_ms": now, "frame_stale_after_ms": 1000}
