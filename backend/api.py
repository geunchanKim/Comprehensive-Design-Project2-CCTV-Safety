import os
from typing import get_args

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:
    from .database import get_db
    from .geometry import (Calibration, complete_box_foot, foot_point, fundamental_matrix,
                           in_front_of_both, match_class, position_on_plane, triangulate, undistort)
    from .models import Camera, Detection, FrameBundle, GlobalObject, GroundTruth, TrackLink
    from .schemas import (CameraCalibrationIn, DetectionBundleIn, DetectionBundleOut,
                          GroundTruthIn, GroundTruthOut, ObjectClass)
except ImportError:  # Docker runs this directory as the import root.
    from database import get_db
    from geometry import (Calibration, complete_box_foot, foot_point, fundamental_matrix,
                          in_front_of_both, match_class, position_on_plane, triangulate, undistort)
    from models import Camera, Detection, FrameBundle, GlobalObject, GroundTruth, TrackLink
    from schemas import (CameraCalibrationIn, DetectionBundleIn, DetectionBundleOut,
                         GroundTruthIn, GroundTruthOut, ObjectClass)

router = APIRouter()
MAX_SYNC_DELTA_MS = int(os.getenv("MAX_SYNC_DELTA_MS", "50"))
MAX_EPIPOLAR_ERROR_PX = float(os.getenv("MAX_EPIPOLAR_ERROR_PX", "50"))
BOX_FOOT_Z_MIN = float(os.getenv("BOX_FOOT_Z_MIN", "-0.35"))
BOX_FOOT_Z_MAX = float(os.getenv("BOX_FOOT_Z_MAX", "0.2"))
ANKLE_FOOT_Z_MIN = float(os.getenv("ANKLE_FOOT_Z_MIN", "-0.1"))
ANKLE_FOOT_Z_MAX = float(os.getenv("ANKLE_FOOT_Z_MAX", "0.4"))
OBJECT_CLASSES = get_args(ObjectClass)


def _height_bounds(*foot_sources: str) -> tuple[float, float]:
    bounds = {
        "box": (BOX_FOOT_Z_MIN, BOX_FOOT_Z_MAX),
        "ankle": (ANKLE_FOOT_Z_MIN, ANKLE_FOOT_Z_MAX),
    }
    selected = [bounds[source] for source in foot_sources]
    return min(bound[0] for bound in selected), max(bound[1] for bound in selected)


def _calibration(camera: Camera) -> Calibration:
    return Calibration(
        K=np.asarray(camera.intrinsic_matrix, dtype=float),
        dist=np.asarray(camera.distortion_coefficients, dtype=float),
        R=np.asarray(camera.rotation_matrix, dtype=float),
        t=np.asarray(camera.translation_vector, dtype=float),
    )


@router.put("/cameras/{camera_id}/calibration", response_model=CameraCalibrationIn)
def upsert_camera_calibration(camera_id: str, body: CameraCalibrationIn, db: Session = Depends(get_db)):
    rotation_matrix, _ = cv2.Rodrigues(np.asarray(body.rvec, dtype=float))
    camera = db.get(Camera, (body.session_id, camera_id)) or Camera(session_id=body.session_id, id=camera_id)
    camera.method = body.method
    camera.image_width, camera.image_height = body.image_size
    camera.intrinsic_matrix = body.K
    camera.distortion_coefficients = body.dist
    camera.rotation_vector = list(body.rvec)
    camera.rotation_matrix = rotation_matrix.tolist()
    camera.translation_vector = list(body.tvec)
    camera.reprojection_error_px = body.reproj_error_px
    db.add(camera)
    db.commit()
    return body


def _object_id(db: Session, session_id, camera1, track1, camera2, track2, cls: str) -> int:
    link = db.scalar(
        select(TrackLink).where(
            TrackLink.session_id == session_id,
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
            TrackLink.session_id == session_id,
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
        global_object = GlobalObject(session_id=session_id, cls=cls)
        db.add(global_object)
        db.flush()
        next_id = global_object.id
    db.add(TrackLink(session_id=session_id, object_id=next_id,
                     camera1_id=camera1, camera1_track_id=track1,
                     camera2_id=camera2, camera2_track_id=track2, cls=cls))
    return next_id


@router.post("/detections", response_model=DetectionBundleOut, status_code=status.HTTP_201_CREATED)
def create_detections(body: DetectionBundleIn, db: Session = Depends(get_db)):
    frames = sorted(body.frames, key=lambda frame: frame.camera_id)
    duplicate = db.scalar(select(FrameBundle.id).where(
        FrameBundle.session_id == body.session_id,
        FrameBundle.pair_id == body.pair_id,
    ))
    if duplicate is not None:
        raise HTTPException(409, "this session/pair detection bundle was already stored")
    sync_delta = abs(frames[0].ts - frames[1].ts)
    if sync_delta > MAX_SYNC_DELTA_MS:
        raise HTTPException(422, f"frame timestamps differ by {sync_delta}ms (maximum {MAX_SYNC_DELTA_MS}ms)")

    cameras = [db.get(Camera, (body.session_id, frame.camera_id)) for frame in frames]
    missing = [frame.camera_id for frame, camera in zip(frames, cameras) if camera is None]
    if missing:
        raise HTTPException(404, f"camera calibration not found: {', '.join(missing)}")
    for frame, camera in zip(frames, cameras):
        if tuple(frame.image_size) != (camera.image_width, camera.image_height):
            raise HTTPException(422, f"image_size does not match calibration for {frame.camera_id}")

    calibrations = [_calibration(camera) for camera in cameras]
    essential = fundamental_matrix(*calibrations)
    pixel_scale = float(np.mean([c.K[0, 0] for c in calibrations] + [c.K[1, 1] for c in calibrations]))
    bundle = FrameBundle(session_id=body.session_id, pair_id=body.pair_id, sync_delta_ms=sync_delta)
    db.add(bundle)
    db.flush()

    records = {}
    normalized = {}
    for frame, calibration in zip(frames, calibrations):
        records[frame.camera_id], normalized[frame.camera_id] = [], []
        for item in frame.detections:
            foot = item.foot if item.foot is not None else foot_point(item.bbox)
            foot_source = (item.foot_src or "box") if item.foot is not None else "box"
            record = Detection(bundle_id=bundle.id, session_id=body.session_id,
                               camera_id=frame.camera_id, frame_id=frame.frame_id,
                               captured_at_ms=frame.ts, track_id=item.track_id, cls=item.cls,
                               confidence=round(item.conf, 3), bbox=list(item.bbox),
                               foot_pixel=list(foot), foot_src=foot_source)
            db.add(record)
            records[frame.camera_id].append((item, record, foot, foot_source))
            normalized[frame.camera_id].append(undistort(foot, calibration))

    matches, used = [], [set(), set()]

    def match_stage(object_class, indexes, forced_source=None):
        points = [[normalized[frame.camera_id][i] for i in indexes[n]] for n, frame in enumerate(frames)]
        candidate_worlds, candidate_points, candidate_pixels = {}, {}, {}

        def source(n, local):
            if forced_source is not None:
                return forced_source
            return records[frames[n].camera_id][indexes[n][local]][3]

        def points_for_pair(local1, local2):
            key = (local1, local2)
            if key in candidate_points:
                return candidate_points[key]
            pair = (points[0][local1], points[1][local2])
            if source(0, local1) == source(1, local2) == "box":
                i, j = indexes[0][local1], indexes[1][local2]
                item1 = records[frames[0].camera_id][i][0]
                item2 = records[frames[1].camera_id][j][0]
                pixels = (foot_point(item1.bbox), foot_point(item2.bbox))
                pair = tuple(undistort(pixel, calibration)
                             for pixel, calibration in zip(pixels, calibrations))
                try:
                    rough_world = triangulate(*pair, *calibrations)
                    depths = [float((c.R @ rough_world + c.t.reshape(3))[2]) for c in calibrations]
                    pixels = (
                        complete_box_foot(item1.bbox, frames[0].image_size[0], item2.bbox,
                                          depths[0], depths[1]),
                        complete_box_foot(item2.bbox, frames[1].image_size[0], item1.bbox,
                                          depths[1], depths[0]),
                    )
                    pair = tuple(undistort(pixel, calibration)
                                 for pixel, calibration in zip(pixels, calibrations))
                except ValueError:
                    pass
                candidate_pixels[key] = pixels
            else:
                candidate_pixels[key] = (records[frames[0].camera_id][indexes[0][local1]][0].foot,
                                         records[frames[1].camera_id][indexes[1][local2]][0].foot)
            candidate_points[key] = pair
            return pair

        def valid_candidate(local1, local2):
            point1, point2 = points_for_pair(local1, local2)
            try:
                world = triangulate(point1, point2, *calibrations)
            except ValueError:
                return False
            if not in_front_of_both(world, *calibrations):
                return False
            candidate_worlds[(local1, local2)] = world
            z_min, z_max = _height_bounds(source(0, local1), source(1, local2))
            return z_min <= world[2] <= z_max

        stage_matches = match_class(points[0], points[1], essential, pixel_scale,
                                    MAX_EPIPOLAR_ERROR_PX, valid_candidate, points_for_pair)
        for local1, local2, error in stage_matches:
            i, j = indexes[0][local1], indexes[1][local2]
            item1, record1, _, _ = records[frames[0].camera_id][i]
            item2, record2, _, _ = records[frames[1].camera_id][j]
            source1, source2 = source(0, local1), source(1, local2)
            normalized_pair = points_for_pair(local1, local2)
            foot1, foot2 = candidate_pixels[(local1, local2)]
            plane_z = 0.1 if source1 == source2 == "ankle" else 0.0
            try:
                positions = [position_on_plane(point, calibration, plane_z)
                             for point, calibration in zip(normalized_pair, calibrations)]
            except ValueError as exc:
                if "parallel" not in str(exc):
                    continue
                fallback = candidate_worlds[(local1, local2)].copy()
                fallback[2] = plane_z
                positions = [fallback, fallback]
            world = np.mean(positions, axis=0)
            object_id = _object_id(db, body.session_id, frames[0].camera_id, item1.track_id,
                                   frames[1].camera_id, item2.track_id, object_class)
            for record, foot, foot_source in ((record1, foot1, source1), (record2, foot2, source2)):
                record.object_id = object_id
                record.world_x, record.world_y, record.world_z = map(float, world)
                record.foot_pixel, record.foot_src = list(foot), foot_source
            used[0].add(i); used[1].add(j)
            matches.append({"object_id": object_id, "cls": object_class,
                            "camera_tracks": {frames[0].camera_id: item1.track_id, frames[1].camera_id: item2.track_id},
                            "foot_pixels": {frames[0].camera_id: foot1, frames[1].camera_id: foot2},
                            "observations": [
                                {"camera_id": frames[0].camera_id, "frame_id": frames[0].frame_id, "ts": frames[0].ts,
                                 "track_id": item1.track_id, "cls": item1.cls, "conf": round(item1.conf, 3),
                                 "bbox": item1.bbox, "image_size": frames[0].image_size,
                                 "foot_pixel": foot1, "foot_src": source1},
                                {"camera_id": frames[1].camera_id, "frame_id": frames[1].frame_id, "ts": frames[1].ts,
                                 "track_id": item2.track_id, "cls": item2.cls, "conf": round(item2.conf, 3),
                                 "bbox": item2.bbox, "image_size": frames[1].image_size,
                                 "foot_pixel": foot2, "foot_src": source2},
                            ],
                            "world": {"x": world[0], "y": world[1], "z": world[2]},
                            "epipolar_error_px": round(error, 3)})

    for object_class in OBJECT_CLASSES:
        class_indexes = [[i for i, row in enumerate(records[frame.camera_id]) if row[0].cls == object_class]
                         for frame in frames]
        if object_class == "person":
            ankle_indexes = [[i for i in side if records[frames[n].camera_id][i][3] == "ankle"]
                              for n, side in enumerate(class_indexes)]
            match_stage(object_class, ankle_indexes, "ankle")
            remaining = [[i for i in side if i not in used[n]] for n, side in enumerate(class_indexes)]
            match_stage(object_class, remaining, "box")
        else:
            match_stage(object_class, class_indexes)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "this camera/frame/track detection was already stored") from exc
    unmatched = {frame.camera_id: [row[0].track_id for i, row in enumerate(records[frame.camera_id]) if i not in used[n]]
                 for n, frame in enumerate(frames)}
    return {"bundle_id": bundle.id, "session_id": body.session_id, "pair_id": body.pair_id,
            "sync_delta_ms": sync_delta, "matches": matches, "unmatched": unmatched}


@router.post("/ground-truth", response_model=GroundTruthOut, status_code=status.HTTP_201_CREATED)
def create_ground_truth(body: GroundTruthIn, db: Session = Depends(get_db)):
    record = GroundTruth(session_id=body.session_id, frame=body.frame,
                         captured_at_ms=body.ts,
                         objects=[item.model_dump(mode="json") for item in body.objects])
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "ground truth for this session/frame was already stored") from exc
    db.refresh(record)
    return {"ground_truth_id": record.id, "session_id": record.session_id,
            "frame": record.frame, "object_count": len(record.objects)}
