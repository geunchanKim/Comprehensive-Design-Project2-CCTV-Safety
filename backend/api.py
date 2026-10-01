import os

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:
    from .database import get_db
    from .geometry import Calibration, foot_point, fundamental_matrix, match_class, triangulate, undistort
    from .models import Camera, Detection, FrameBundle, GlobalObject, TrackLink
    from .schemas import CameraUpsert, DetectionBundleIn, DetectionBundleOut
except ImportError:  # Docker runs this directory as the import root.
    from database import get_db
    from geometry import Calibration, foot_point, fundamental_matrix, match_class, triangulate, undistort
    from models import Camera, Detection, FrameBundle, GlobalObject, TrackLink
    from schemas import CameraUpsert, DetectionBundleIn, DetectionBundleOut

router = APIRouter()
MAX_SYNC_DELTA_MS = int(os.getenv("MAX_SYNC_DELTA_MS", "50"))
MAX_EPIPOLAR_ERROR_PX = float(os.getenv("MAX_EPIPOLAR_ERROR_PX", "5"))


def _calibration(camera: Camera) -> Calibration:
    return Calibration(
        K=np.asarray(camera.intrinsic_matrix, dtype=float),
        dist=np.asarray(camera.distortion_coefficients, dtype=float),
        R=np.asarray(camera.rotation_matrix, dtype=float),
        t=np.asarray(camera.translation_vector, dtype=float),
    )


@router.put("/cameras/{camera_id}", response_model=CameraUpsert)
def upsert_camera(camera_id: str, body: CameraUpsert, db: Session = Depends(get_db)):
    if camera_id != body.camera_id:
        raise HTTPException(422, "path camera_id and body camera_id must match")
    camera = db.get(Camera, camera_id) or Camera(id=camera_id)
    camera.image_width, camera.image_height = body.image_size
    camera.intrinsic_matrix = body.K
    camera.distortion_coefficients = body.dist
    camera.rotation_matrix = body.R
    camera.translation_vector = body.t
    db.add(camera)
    db.commit()
    return body


def _object_id(db: Session, camera1, track1, camera2, track2, cls: str) -> int:
    link = db.scalar(
        select(TrackLink).where(
            TrackLink.camera1_id == camera1,
            TrackLink.camera1_track_id == track1,
            TrackLink.camera2_id == camera2,
            TrackLink.camera2_track_id == track2,
            TrackLink.cls == cls,
        )
    )
    if link:
        return link.object_id

    # Re-use identity when one camera reacquires its counterpart under a new local ID.
    link = db.scalar(
        select(TrackLink).where(
            TrackLink.cls == cls,
            or_(
                (TrackLink.camera1_id == camera1) & (TrackLink.camera1_track_id == track1),
                (TrackLink.camera2_id == camera2) & (TrackLink.camera2_track_id == track2),
            ),
        ).order_by(TrackLink.id.desc())
    )
    if link:
        next_id = link.object_id
    else:
        global_object = GlobalObject(cls=cls)
        db.add(global_object)
        db.flush()
        next_id = global_object.id
    db.add(TrackLink(object_id=next_id,
                     camera1_id=camera1, camera1_track_id=track1,
                     camera2_id=camera2, camera2_track_id=track2, cls=cls))
    return next_id


@router.post("/detections", response_model=DetectionBundleOut, status_code=status.HTTP_201_CREATED)
def create_detections(body: DetectionBundleIn, db: Session = Depends(get_db)):
    frames = sorted(body.frames, key=lambda frame: frame.camera_id)
    sync_delta = abs(frames[0].ts - frames[1].ts)
    if sync_delta > MAX_SYNC_DELTA_MS:
        raise HTTPException(422, f"frame timestamps differ by {sync_delta}ms (maximum {MAX_SYNC_DELTA_MS}ms)")

    cameras = [db.get(Camera, frame.camera_id) for frame in frames]
    missing = [frame.camera_id for frame, camera in zip(frames, cameras) if camera is None]
    if missing:
        raise HTTPException(404, f"camera calibration not found: {', '.join(missing)}")
    for frame, camera in zip(frames, cameras):
        if tuple(frame.image_size) != (camera.image_width, camera.image_height):
            raise HTTPException(422, f"image_size does not match calibration for {frame.camera_id}")

    calibrations = [_calibration(camera) for camera in cameras]
    essential = fundamental_matrix(*calibrations)
    pixel_scale = float(np.mean([c.K[0, 0] for c in calibrations] + [c.K[1, 1] for c in calibrations]))
    bundle = FrameBundle(sync_delta_ms=sync_delta)
    db.add(bundle)
    db.flush()

    records = {}
    normalized = {}
    for frame, calibration in zip(frames, calibrations):
        records[frame.camera_id], normalized[frame.camera_id] = [], []
        for item in frame.detections:
            foot = foot_point(item.bbox)
            record = Detection(bundle_id=bundle.id, camera_id=frame.camera_id, frame_id=frame.frame_id,
                               captured_at_ms=frame.ts, track_id=item.track_id, cls=item.cls,
                               confidence=round(item.conf, 3), bbox=list(item.bbox), foot_pixel=list(foot))
            db.add(record)
            records[frame.camera_id].append((item, record, foot))
            normalized[frame.camera_id].append(undistort(foot, calibration))

    matches, used = [], [set(), set()]
    for object_class in ("person", "chair", "cart", "desk"):
        indexes = [[i for i, row in enumerate(records[frame.camera_id]) if row[0].cls == object_class] for frame in frames]
        points = [[normalized[frame.camera_id][i] for i in indexes[n]] for n, frame in enumerate(frames)]
        for local1, local2, error in match_class(points[0], points[1], essential, pixel_scale, MAX_EPIPOLAR_ERROR_PX):
            i, j = indexes[0][local1], indexes[1][local2]
            item1, record1, foot1 = records[frames[0].camera_id][i]
            item2, record2, foot2 = records[frames[1].camera_id][j]
            try:
                world = triangulate(normalized[frames[0].camera_id][i], normalized[frames[1].camera_id][j], *calibrations)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            object_id = _object_id(db, frames[0].camera_id, item1.track_id, frames[1].camera_id, item2.track_id, object_class)
            for record in (record1, record2):
                record.object_id = object_id
                record.world_x, record.world_y, record.world_z = map(float, world)
            used[0].add(i); used[1].add(j)
            matches.append({"object_id": object_id, "cls": object_class,
                            "camera_tracks": {frames[0].camera_id: item1.track_id, frames[1].camera_id: item2.track_id},
                            "foot_pixels": {frames[0].camera_id: foot1, frames[1].camera_id: foot2},
                            "observations": [
                                {"camera_id": frames[0].camera_id, "frame_id": frames[0].frame_id, "ts": frames[0].ts,
                                 "track_id": item1.track_id, "cls": item1.cls, "conf": round(item1.conf, 3),
                                 "bbox": item1.bbox, "image_size": frames[0].image_size, "foot_pixel": foot1},
                                {"camera_id": frames[1].camera_id, "frame_id": frames[1].frame_id, "ts": frames[1].ts,
                                 "track_id": item2.track_id, "cls": item2.cls, "conf": round(item2.conf, 3),
                                 "bbox": item2.bbox, "image_size": frames[1].image_size, "foot_pixel": foot2},
                            ],
                            "world": {"x": world[0], "y": world[1], "z": world[2]},
                            "epipolar_error_px": round(error, 3)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "this camera/frame/track detection was already stored") from exc
    unmatched = {frame.camera_id: [row[0].track_id for i, row in enumerate(records[frame.camera_id]) if i not in used[n]]
                 for n, frame in enumerate(frames)}
    return {"bundle_id": bundle.id, "sync_delta_ms": sync_delta, "matches": matches, "unmatched": unmatched}
