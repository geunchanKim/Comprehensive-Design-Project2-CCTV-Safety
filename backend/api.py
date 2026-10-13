import os
import csv
import io
import json
import re
from itertools import combinations
from typing import get_args

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:
    from .database import get_db
    from .geometry import (Calibration, combine_plane_positions, complete_box_foot, foot_point, fundamental_matrix,
                           in_front_of_both, match_by_cost, match_class, position_on_plane,
                           symmetric_epipolar_distance, triangulate, undistort)
    from .models import (Camera, Detection, FloorTrack, FrameBundle, GlobalObject, GroundTruth,
                         ObjectMotionState, RiskEvent, RiskPairState, TrackLink, TrackPairState)
    from .models import SessionSettings
    from .schemas import (Algorithm, CalibrationProfile, CameraCalibrationIn, DetectionBundleIn, DetectionBundleOut,
                          GroundTruthIn, GroundTruthOut, ObjectClass)
    from .schemas import PnPCalibrationIn
    from .tracking import (FLOOR_TRACK_GATE_M, FLOOR_TRACK_MAX_MISSED,
                           KALMAN_MEASUREMENT_NOISE, KALMAN_PROCESS_NOISE, KalmanState,
                           PairHysteresis, associate_floor_tracks, initialize_kalman,
                           predict_floor_position,
                           update_kalman, update_pair_hysteresis)
    from .risk import WARNING_RELEASE_MARGIN_M, calculate_pair_risk, hysteresis_level
except ImportError:  # Docker runs this directory as the import root.
    from database import get_db
    from geometry import (Calibration, combine_plane_positions, complete_box_foot, foot_point, fundamental_matrix,
                          in_front_of_both, match_by_cost, match_class, position_on_plane,
                          symmetric_epipolar_distance, triangulate, undistort)
    from models import (Camera, Detection, FloorTrack, FrameBundle, GlobalObject, GroundTruth,
                        ObjectMotionState, RiskEvent, RiskPairState, TrackLink, TrackPairState)
    from models import SessionSettings
    from schemas import (Algorithm, CalibrationProfile, CameraCalibrationIn, DetectionBundleIn, DetectionBundleOut,
                         GroundTruthIn, GroundTruthOut, ObjectClass)
    from schemas import PnPCalibrationIn
    from tracking import (FLOOR_TRACK_GATE_M, FLOOR_TRACK_MAX_MISSED,
                          KALMAN_MEASUREMENT_NOISE, KALMAN_PROCESS_NOISE, KalmanState,
                          PairHysteresis, associate_floor_tracks, initialize_kalman,
                          predict_floor_position,
                          update_kalman, update_pair_hysteresis)
    from risk import WARNING_RELEASE_MARGIN_M, calculate_pair_risk, hysteresis_level

router = APIRouter()
MAX_SYNC_DELTA_MS = int(os.getenv("MAX_SYNC_DELTA_MS", "50"))
MAX_EPIPOLAR_ERROR_PX = float(os.getenv("MAX_EPIPOLAR_ERROR_PX", "50"))
BOX_FOOT_Z_MIN = float(os.getenv("BOX_FOOT_Z_MIN", "-0.35"))
BOX_FOOT_Z_MAX = float(os.getenv("BOX_FOOT_Z_MAX", "0.2"))
ANKLE_FOOT_Z_MIN = float(os.getenv("ANKLE_FOOT_Z_MIN", "-0.1"))
ANKLE_FOOT_Z_MAX = float(os.getenv("ANKLE_FOOT_Z_MAX", "0.4"))
BBOX_POSITION_METHOD = os.getenv("BBOX_POSITION_METHOD", "triangulate")
MAX_GROUND_DISTANCE_M = float(os.getenv("MAX_GROUND_DISTANCE_M", "2.0"))
ENABLE_KALMAN_FILTER = os.getenv("ENABLE_KALMAN_FILTER", "true").lower() in {"1", "true", "yes"}
ENABLE_TRACK_PAIR_HOLD = os.getenv("ENABLE_TRACK_PAIR_HOLD", "true").lower() in {"1", "true", "yes"}
TRACK_PAIR_CONFIRM_FRAMES = int(os.getenv("TRACK_PAIR_CONFIRM_FRAMES", "3"))
TRACK_PAIR_IMPROVEMENT_RATIO = float(os.getenv("TRACK_PAIR_IMPROVEMENT_RATIO", "0.9"))
ENABLE_RISK_ANALYSIS = os.getenv("ENABLE_RISK_ANALYSIS", "false").lower() in {"1", "true", "yes"}
ENABLE_ANKLE_PAIRING = os.getenv("ENABLE_ANKLE_PAIRING", "true").lower() in {"1", "true", "yes"}
MIN_ANKLE_CONFIDENCE = float(os.getenv("MIN_ANKLE_CONFIDENCE", "0.6"))
WARNING_DISTANCE_M = float(os.getenv("WARNING_DISTANCE_M", "1.0"))
DANGER_DISTANCE_M = float(os.getenv("DANGER_DISTANCE_M", "0.5"))
OBJECT_CLASSES = get_args(ObjectClass)
BOX_FOOT_COMPLETION_CLASSES = frozenset({"person", "chair", "suitcase"})
BOX_PLANE_CLASSES = frozenset({"chair", "suitcase"})

if BBOX_POSITION_METHOD not in {"triangulate", "plane", "weighted-plane"}:
    raise ValueError("BBOX_POSITION_METHOD must be 'triangulate', 'plane', or 'weighted-plane'")


def _height_bounds(*foot_sources: str) -> tuple[float, float]:
    bounds = {
        "box": (BOX_FOOT_Z_MIN, BOX_FOOT_Z_MAX),
        "ankle": (ANKLE_FOOT_Z_MIN, ANKLE_FOOT_Z_MAX),
    }
    selected = [bounds[source] for source in foot_sources]
    return min(bound[0] for bound in selected), max(bound[1] for bound in selected)


def _should_complete_box_foot(object_class: str, source1: str, source2: str) -> bool:
    return object_class in BOX_FOOT_COMPLETION_CLASSES and source1 == source2 == "box"


def _should_use_box_plane(object_class: str, source1: str, source2: str) -> bool:
    return (object_class in BOX_PLANE_CLASSES and source1 == source2 == "box"
            and BBOX_POSITION_METHOD in {"plane", "weighted-plane"})


def _calibration(camera: Camera) -> Calibration:
    return Calibration(
        K=np.asarray(camera.intrinsic_matrix, dtype=float),
        # The basic condition intentionally uses raw pixels without lens correction.
        dist=(np.zeros(5, dtype=float) if camera.calibration_profile == "basic"
              else np.asarray(camera.distortion_coefficients, dtype=float)),
        R=np.asarray(camera.rotation_matrix, dtype=float),
        t=np.asarray(camera.translation_vector, dtype=float),
    )


def _filter_motion(db: Session, session_id: str, profile: str, algorithm: str,
                   object_id: int, world, timestamp_ms: int):
    raw = np.asarray(world, dtype=float)
    if not _algorithm_settings(algorithm)["kalman_filter"]:
        return raw, None
    stored = db.get(ObjectMotionState, object_id)
    if stored is None:
        state = initialize_kalman(raw, timestamp_ms)
        stored = ObjectMotionState(object_id=object_id, session_id=session_id,
                                   calibration_profile=profile, algorithm=algorithm)
        db.add(stored)
    else:
        state = KalmanState(mean=np.asarray(stored.mean, dtype=float),
                            covariance=np.asarray(stored.covariance, dtype=float),
                            timestamp_ms=stored.timestamp_ms)
        state = update_kalman(state, raw, timestamp_ms)
    stored.mean = state.mean.tolist()
    stored.covariance = state.covariance.tolist()
    stored.timestamp_ms = state.timestamp_ms
    return state.mean[:3], state.mean[3:]


# 기능별 실험(ablation)용 알고리즘 이름: baseline, improved, 또는 "f-" + 기능 글자 (알파벳 순, 중복 없이)
#   예) f-g = 기존 + 바닥 짝짓기, f-gk = 기존 + 바닥 짝짓기 + 칼만
FEATURE_CODES = {
    "a": "ankle",    # 같은 쪽 발목끼리 삼각측량
    "c": "floor",    # C 바닥 좌표 추적 (사람 번호를 바닥 움직임으로 이어 붙임, 칼만 포함)
    "d": "fallback", # D 한 카메라 보완 (짝이 안 된 사람을 한 카메라 바닥 투영으로 이어 붙임, c 필요)
    "e": "timesync", # E 시간차 보정 (두 카메라 사진 시각 차이만큼 속도로 보정, c 필요)
    "f": "hysteresis",  # F 경고 유지 (1.0m 안에서 켜진 경고는 1.1m를 넘어야 꺼짐)
    "g": "ground",   # 바닥 위치로 짝짓기
    "h": "hold",     # 카메라 짝 유지
    "k": "kalman",   # 칼만 필터
}
ALGORITHM_RE = re.compile(r"^(baseline|improved|f-[a-z]{1,12})$")
FEATURES_NEEDING_FLOOR = ("d", "e")   # C의 트랙(예측 위치·속도)을 써야 동작

# D 한 카메라 보완: 발목은 이 높이 평면, 박스 발은 바닥(0) 평면과 만나는 점을 위치로 쓴다.
#   한 카메라 위치는 덜 정확하니 칼만 측정 잡음을 크게 준다 (Unity s2·s4 오프라인 시뮬로 정함, 2026-10-13)
SINGLE_CAMERA_ANKLE_Z_M = 0.15
SINGLE_CAMERA_MEASUREMENT_NOISE = 0.05


def algorithm_features(algorithm: str) -> frozenset[str]:
    """알고리즘 이름 → 켜진 기능 이름들. 잘못된 이름이면 ValueError"""
    if not isinstance(algorithm, str) or not ALGORITHM_RE.fullmatch(algorithm):
        raise ValueError(f"algorithm must be baseline, improved, or f-<codes> ({', '.join(FEATURE_CODES)})")
    if algorithm == "baseline":
        return frozenset()
    if algorithm == "improved":
        return frozenset(name for name, enabled in (
            ("ground", True), ("kalman", ENABLE_KALMAN_FILTER),
            ("hold", ENABLE_TRACK_PAIR_HOLD), ("ankle", ENABLE_ANKLE_PAIRING)) if enabled)
    codes = algorithm[2:]
    unknown = sorted(set(codes) - set(FEATURE_CODES))
    if unknown:
        raise ValueError(f"unknown feature code(s): {', '.join(unknown)} (available: {FEATURE_CODES})")
    if codes != "".join(sorted(set(codes))):
        raise ValueError(f"feature codes must be sorted and unique: use f-{''.join(sorted(set(codes)))}")
    needs_floor = sorted(set(codes) & set(FEATURES_NEEDING_FLOOR))
    if needs_floor and "c" not in codes:
        raise ValueError(f"feature(s) {', '.join(needs_floor)} need c (floor tracking): "
                         f"use f-{''.join(sorted(set(codes) | {'c'}))}")
    return frozenset(FEATURE_CODES[code] for code in codes)


def _checked_algorithm(algorithm: str) -> str:
    try:
        algorithm_features(algorithm)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return algorithm


def _algorithm_settings(algorithm: Algorithm):
    """Return the features that are actually active for an algorithm condition."""
    features = algorithm_features(algorithm)
    return {
        "matching_method": "ground-plane" if "ground" in features else "epipolar",
        "kalman_filter": "kalman" in features,
        "track_pair_hold": "hold" in features,
        "ankle_pairing": "ankle" in features,
        "floor_tracking": "floor" in features,
        "single_camera_fallback": "fallback" in features,
        "time_offset_correction": "timesync" in features,
        "warning_hysteresis": "hysteresis" in features,
    }


def _experiment_settings(algorithm: Algorithm):
    return {
        **_algorithm_settings(algorithm),
        "features": sorted(algorithm_features(algorithm)),
        "max_ground_distance_m": MAX_GROUND_DISTANCE_M,
        "kalman_process_noise": KALMAN_PROCESS_NOISE,
        "kalman_measurement_noise": KALMAN_MEASUREMENT_NOISE,
        "floor_track_gate_m": FLOOR_TRACK_GATE_M,
        "floor_track_max_missed": FLOOR_TRACK_MAX_MISSED,
        "single_camera_ankle_z_m": SINGLE_CAMERA_ANKLE_Z_M,
        "single_camera_measurement_noise": SINGLE_CAMERA_MEASUREMENT_NOISE,
        "warning_release_margin_m": WARNING_RELEASE_MARGIN_M,
        "bbox_position_method": BBOX_POSITION_METHOD,
        "track_pair_confirm_frames": TRACK_PAIR_CONFIRM_FRAMES,
        "track_pair_improvement_ratio": TRACK_PAIR_IMPROVEMENT_RATIO,
        "risk_analysis": ENABLE_RISK_ANALYSIS,
        "min_ankle_confidence": MIN_ANKLE_CONFIDENCE,
        "warning_distance_m": WARNING_DISTANCE_M,
        "danger_distance_m": DANGER_DISTANCE_M,
    }


@router.get("/sessions/{session_id}/results.csv")
def download_session_results(session_id: str, profile: CalibrationProfile = "basic",
                             algorithm: Algorithm = "baseline",
                             db: Session = Depends(get_db)):
    _checked_algorithm(algorithm)
    stored_settings = db.get(SessionSettings, (session_id, profile, algorithm))
    if stored_settings is None:
        raise HTTPException(404, "session results not found")
    output = io.StringIO()
    fields = ["record_type", "pair_id", "frame_id", "timestamp_ms", "object_id", "object2_id", "cls",
              "x", "y", "z", "distance_m", "ttc_s", "level", "settings"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    settings_json = json.dumps(stored_settings.settings, sort_keys=True)
    detections = db.execute(select(Detection, FrameBundle.pair_id).join(
        FrameBundle, Detection.bundle_id == FrameBundle.id).where(
        Detection.session_id == session_id,
        Detection.calibration_profile == profile,
        Detection.algorithm == algorithm,
        Detection.object_id.is_not(None),
    ).order_by(Detection.captured_at_ms, Detection.bundle_id,
               Detection.camera_id, Detection.track_id)).all()
    seen = set()
    for item, pair_id in detections:
        key = (item.bundle_id, item.object_id)   # 짝이 된 두 카메라 탐지는 같은 사람 번호라 한 줄만
        if key in seen:
            continue
        seen.add(key)
        writer.writerow({"record_type": "position", "pair_id": pair_id,
                         "frame_id": item.frame_id, "timestamp_ms": item.captured_at_ms,
                         "object_id": item.object_id, "cls": item.cls,
                         "x": item.world_x, "y": item.world_y, "z": item.world_z,
                         "settings": settings_json})
    events = db.execute(select(RiskEvent, FrameBundle.pair_id).join(
                        FrameBundle, RiskEvent.bundle_id == FrameBundle.id).where(
                        RiskEvent.session_id == session_id,
                        FrameBundle.calibration_profile == profile,
                        FrameBundle.algorithm == algorithm)
                        .order_by(RiskEvent.captured_at_ms, RiskEvent.id)).all()
    for event, pair_id in events:
        writer.writerow({"record_type": "risk", "pair_id": pair_id,
                         "timestamp_ms": event.captured_at_ms,
                         "object_id": event.object1_id, "object2_id": event.object2_id,
                         "distance_m": event.distance_m, "ttc_s": event.ttc_s,
                         "level": event.level, "settings": settings_json})
    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{session_id}-results.csv"'})


@router.put("/cameras/{camera_id}/calibration", response_model=CameraCalibrationIn)
def upsert_camera_calibration(camera_id: str, body: CameraCalibrationIn, db: Session = Depends(get_db)):
    rotation_matrix, _ = cv2.Rodrigues(np.asarray(body.rvec, dtype=float))
    key = (body.session_id, camera_id, body.calibration_profile)
    camera = db.get(Camera, key) or Camera(session_id=body.session_id, id=camera_id,
                                           calibration_profile=body.calibration_profile)
    camera.method = body.method
    camera.image_width, camera.image_height = body.image_size
    camera.intrinsic_matrix = body.K
    camera.distortion_coefficients = body.dist
    camera.rotation_vector = list(body.rvec)
    camera.rotation_matrix = rotation_matrix.tolist()
    camera.translation_vector = list(body.tvec)
    camera.reprojection_error_px = body.reproj_error_px
    camera.validation_rmse_cm = body.validation_rmse_cm
    camera.validation_max_error_cm = body.validation_max_error_cm
    camera.validation_point_count = body.validation_point_count
    db.add(camera)
    db.commit()
    return body


@router.post("/cameras/{camera_id}/calibration/solve-pnp", response_model=CameraCalibrationIn)
def solve_precise_calibration(camera_id: str, body: PnPCalibrationIn,
                              db: Session = Depends(get_db)):
    object_points = np.asarray([point.world for point in body.grid_points], dtype=np.float64)
    image_points = np.asarray([point.image for point in body.grid_points], dtype=np.float64)
    if np.linalg.matrix_rank(object_points[:, :2] - object_points[:, :2].mean(axis=0)) < 2:
        raise HTTPException(422, "grid points must cover the floor in two dimensions, not one line")
    if np.linalg.matrix_rank(image_points - image_points.mean(axis=0)) < 2:
        raise HTTPException(422, "grid image points must not lie on one line")
    image_span = np.ptp(image_points, axis=0)
    if image_span[0] < body.image_size[0] * 0.25 or image_span[1] < body.image_size[1] * 0.25:
        raise HTTPException(422, "grid image points must span at least 25% of image width and height")
    K = np.asarray(body.K, dtype=np.float64)
    dist = np.asarray(body.dist, dtype=np.float64)
    solved, rvec, tvec = cv2.solvePnP(object_points, image_points, K, dist,
                                     flags=cv2.SOLVEPNP_ITERATIVE)
    if not solved:
        raise HTTPException(422, "PnP calibration could not be solved")
    projected, _ = cv2.projectPoints(object_points, rvec, tvec, K, dist)
    reprojection = np.linalg.norm(projected.reshape(-1, 2) - image_points, axis=1)
    rotation, _ = cv2.Rodrigues(rvec)
    calibration = Calibration(K=K, dist=dist, R=rotation, t=tvec.reshape(3))
    validation_errors_cm = []
    for point in body.validation_points:
        normalized = undistort(point.image, calibration)
        try:
            estimated = position_on_plane(normalized, calibration, point.world[2])
        except ValueError as exc:
            raise HTTPException(422, "validation ray is parallel to its reference plane") from exc
        validation_errors_cm.append(float(np.linalg.norm(
            estimated - np.asarray(point.world, dtype=float))) * 100.0)
    result = CameraCalibrationIn(
        session_id=body.session_id, calibration_profile="precise", method="charuco-aruco",
        image_size=body.image_size, K=body.K, dist=body.dist,
        rvec=tuple(float(value) for value in rvec.reshape(3)),
        tvec=tuple(float(value) for value in tvec.reshape(3)),
        reproj_error_px=float(np.sqrt(np.mean(np.square(reprojection)))),
        validation_rmse_cm=float(np.sqrt(np.mean(np.square(validation_errors_cm)))),
        validation_max_error_cm=max(validation_errors_cm),
        validation_point_count=len(validation_errors_cm),
    )
    return upsert_camera_calibration(camera_id, result, db)


def _object_id(db: Session, session_id, profile, algorithm,
               camera1, track1, camera2, track2, cls: str,
               visible_tracks: tuple[set[int], set[int]], used_object_ids: set[int]) -> int:
    link = db.scalar(
        select(TrackLink).where(
            TrackLink.session_id == session_id,
            TrackLink.calibration_profile == profile,
            TrackLink.algorithm == algorithm,
            TrackLink.camera1_id == camera1,
            TrackLink.camera1_track_id == track1,
            TrackLink.camera2_id == camera2,
            TrackLink.camera2_track_id == track2,
            TrackLink.cls == cls,
        )
    )
    if link and link.object_id not in used_object_ids:
        return link.object_id

    def new_object_id() -> int:
        global_object = GlobalObject(session_id=session_id, calibration_profile=profile,
                                     algorithm=algorithm, cls=cls)
        db.add(global_object)
        db.flush()
        return global_object.id

    # A historical bad pairing may have assigned this exact pair an ID already used
    # by another person in the current bundle. Split it instead of merging positions.
    if link:
        link.object_id = new_object_id()
        return link.object_id

    # Reconnect only when one local track is stable and the old counterpart has
    # disappeared. If that counterpart is still visible, this is a crossing/mispair.
    link = db.scalar(
        select(TrackLink).where(
            TrackLink.session_id == session_id,
            TrackLink.calibration_profile == profile,
            TrackLink.algorithm == algorithm,
            TrackLink.cls == cls,
            or_(
                ((TrackLink.camera1_id == camera1) &
                 (TrackLink.camera1_track_id == track1) &
                 TrackLink.camera2_track_id.not_in(visible_tracks[1])),
                ((TrackLink.camera2_id == camera2) &
                 (TrackLink.camera2_track_id == track2) &
                 TrackLink.camera1_track_id.not_in(visible_tracks[0])),
            ),
        ).order_by(TrackLink.id.desc())
    )
    if link and link.object_id not in used_object_ids:
        next_id = link.object_id
    else:
        next_id = new_object_id()
    db.add(TrackLink(session_id=session_id, calibration_profile=profile, algorithm=algorithm,
                     object_id=next_id,
                     camera1_id=camera1, camera1_track_id=track1,
                     camera2_id=camera2, camera2_track_id=track2, cls=cls))
    return next_id


def _time_corrected_position(raw, velocity_xy, normalized_pair, frame_ts, timestamp_ms: int, calibrations):
    """E 시간차 보정: 두 카메라 사진 시각이 다르면 사람이 그 사이 움직인 만큼 위치가 섞인다.

    카메라마다 (기준 시각 - 사진 시각) 동안 속도만큼 움직인 위치를 그 카메라에 투영해서
    발 픽셀을 옮기고, 다시 삼각측량한 변화량만큼 원래 위치를 고친다. 기준 시각 = 더 늦은 사진 시각"""
    raw = np.asarray(raw, dtype=float)
    velocity = np.array([float(velocity_xy[0]), float(velocity_xy[1]), 0.0])
    if not any(int(ts) != int(timestamp_ms) for ts in frame_ts):
        return raw
    corrected = []
    for point, ts, calibration in zip(normalized_pair, frame_ts, calibrations):
        dt = (int(timestamp_ms) - int(ts)) / 1000.0
        before = calibration.R @ raw + calibration.t.reshape(3)
        after = calibration.R @ (raw + velocity * dt) + calibration.t.reshape(3)
        if before[2] <= 0 or after[2] <= 0:
            return raw
        corrected.append(np.asarray(point, dtype=float) + (after[:2] / after[2] - before[:2] / before[2]))
    try:
        original = triangulate(np.asarray(normalized_pair[0], dtype=float),
                               np.asarray(normalized_pair[1], dtype=float), *calibrations)
        moved = triangulate(corrected[0], corrected[1], *calibrations)
    except ValueError:
        return raw
    return raw + (moved - original)


def _apply_floor_tracking(db: Session, session_id: str, profile: str, algorithm: str, settings: dict,
                          entries: list, singles: list, frames, calibrations) -> list:
    """C 바닥 좌표 추적 (+ D 한 카메라 보완, E 시간차 보정).

    entries: 두 카메라 짝이 된 사람 [{match, records, raw, normalized, used}]
    singles: 짝이 안 된 사람 탐지 [{camera, item, record, foot, foot_source, normalized, used}]
    1) 트랙마다 지금 시각의 바닥 위치를 예측  2) 예측과 가까운 사람끼리 짝 (FLOOR_TRACK_GATE_M 안)
    3) 짝이 된 트랙은 칼만 갱신(E: 시간차 보정한 위치로), 짝이 없는 사람은 새 트랙(새 사람 번호)
    4) D: 이번에 못 본 트랙은 짝 없는 한 카메라 탐지로 이어 붙임 (새 트랙은 만들지 않음)
    5) 그래도 못 본 트랙은 missed를 올리고 FLOOR_TRACK_MAX_MISSED를 넘으면 지운다
    반환: D가 새로 만든 응답 match 목록"""
    timestamp_ms = max(frame.ts for frame in frames)
    frame_ts = [frame.ts for frame in frames]
    tracks = list(db.scalars(select(FloorTrack).where(
        FloorTrack.session_id == session_id,
        FloorTrack.calibration_profile == profile,
        FloorTrack.algorithm == algorithm,
        FloorTrack.cls == "person",
    ).order_by(FloorTrack.id)).all())
    states = [KalmanState(mean=np.asarray(track.mean, dtype=float),
                          covariance=np.asarray(track.covariance, dtype=float),
                          timestamp_ms=track.timestamp_ms) for track in tracks]

    def write(track, state, match, records):
        track.mean, track.covariance = state.mean.tolist(), state.covariance.tolist()
        track.timestamp_ms, track.missed = state.timestamp_ms, 0
        world = [float(v) for v in state.mean[:3]]
        match["object_id"] = track.object_id
        match["world"] = dict(zip(("x", "y", "z"), world))
        match["velocity"] = dict(zip(("x", "y", "z"), (float(v) for v in state.mean[3:])))
        for record in records:
            record.object_id = track.object_id
            record.world_x, record.world_y, record.world_z = world

    pairs = associate_floor_tracks([predict_floor_position(state, timestamp_ms) for state in states],
                                   [entry["raw"][:2] for entry in entries])
    track_for_entry = {entry: track for track, entry in pairs}
    seen = set()
    for n, entry in enumerate(entries):
        if n in track_for_entry:
            index = track_for_entry[n]
            measured = entry["raw"]
            if settings["time_offset_correction"]:
                measured = _time_corrected_position(measured, states[index].mean[3:5], entry["normalized"],
                                                    frame_ts, timestamp_ms, calibrations)
            track, state = tracks[index], update_kalman(states[index], measured, timestamp_ms)
            seen.add(index)
        else:
            global_object = GlobalObject(session_id=session_id, calibration_profile=profile,
                                         algorithm=algorithm, cls="person")
            db.add(global_object)
            db.flush()
            track = FloorTrack(session_id=session_id, calibration_profile=profile, algorithm=algorithm,
                               cls="person", object_id=global_object.id)
            db.add(track)
            state = initialize_kalman(entry["raw"], timestamp_ms)
        write(track, state, entry["match"], entry["records"])

    added = []
    free = [index for index in range(len(tracks)) if index not in seen]
    if settings["single_camera_fallback"] and singles and free:
        positions, usable = [], []
        for single in singles:
            camera = single["camera"]
            plane_z = SINGLE_CAMERA_ANKLE_Z_M if single["foot_source"] == "ankle" else 0.0
            try:
                positions.append(position_on_plane(single["normalized"], calibrations[camera], plane_z))
                usable.append(single)
            except ValueError:
                continue
        pairs = associate_floor_tracks([predict_floor_position(states[index], timestamp_ms) for index in free],
                                       [position[:2] for position in positions])
        for slot, n in pairs:
            index, single, position = free[slot], usable[n], positions[n]
            state = update_kalman(states[index], position, timestamp_ms,
                                  measurement_noise=SINGLE_CAMERA_MEASUREMENT_NOISE)
            seen.add(index)
            frame, item = frames[single["camera"]], single["item"]
            match = {"cls": "person",
                     "camera_tracks": {frame.camera_id: item.track_id},
                     "foot_pixels": {frame.camera_id: single["foot"]},
                     "observations": [{"camera_id": frame.camera_id, "frame_id": frame.frame_id, "ts": frame.ts,
                                       "track_id": item.track_id, "cls": item.cls, "conf": round(item.conf, 3),
                                       "bbox": item.bbox, "image_size": frame.image_size,
                                       "foot_pixel": single["foot"], "foot_src": single["foot_source"],
                                       "position_method": "single-camera"}],
                     "raw_world": dict(zip(("x", "y", "z"), (float(v) for v in position))),
                     "epipolar_error_px": None,
                     "matching_method": "single-camera",
                     "ground_distance_m": None}
            write(tracks[index], state, match, [single["record"]])
            single["used"].add(single["index"])
            added.append(match)

    for index, track in enumerate(tracks):
        if index in seen:
            continue
        track.missed += 1
        if track.missed > FLOOR_TRACK_MAX_MISSED:
            db.delete(track)
    return added


def _risk_level_with_hysteresis(db: Session, session_id: str, profile: str, algorithm: str,
                                object1_id: int, object2_id: int, distance_m: float) -> str:
    """F 경고 유지: 이 두 사람의 직전 경고 단계를 기억해서, 켜진 경고는 여유 거리만큼 더 멀어져야 끈다"""
    state = db.scalar(select(RiskPairState).where(
        RiskPairState.session_id == session_id,
        RiskPairState.calibration_profile == profile,
        RiskPairState.algorithm == algorithm,
        RiskPairState.object1_id == object1_id,
        RiskPairState.object2_id == object2_id,
    ))
    previous = state.level if state else "safe"
    level = hysteresis_level(distance_m, previous, WARNING_DISTANCE_M, DANGER_DISTANCE_M)
    if state is None:
        db.add(RiskPairState(session_id=session_id, calibration_profile=profile, algorithm=algorithm,
                             object1_id=object1_id, object2_id=object2_id, level=level))
    else:
        state.level = level
    return level


def _create_detections(body: DetectionBundleIn, db: Session, algorithm: Algorithm):
    frames = sorted(body.frames, key=lambda frame: frame.camera_id)
    visible_tracks = tuple({item.track_id for item in frame.detections} for frame in frames)
    used_object_ids: set[int] = set()
    profile = body.calibration_profile
    max_sync_delta_ms = body.max_sync_delta_ms if body.max_sync_delta_ms is not None else MAX_SYNC_DELTA_MS
    settings = {**_experiment_settings(algorithm),
                "calibration_profile": profile, "algorithm": algorithm,
                "max_sync_delta_ms": max_sync_delta_ms}
    matching_method = settings["matching_method"]
    stored_settings = db.get(SessionSettings, (body.session_id, profile, algorithm))
    if stored_settings is None:
        db.add(SessionSettings(session_id=body.session_id, calibration_profile=profile,
                               algorithm=algorithm, settings=settings))
    elif stored_settings.settings != settings:
        raise HTTPException(409, "session was already processed with different experiment settings")
    duplicate = db.scalar(select(FrameBundle.id).where(
        FrameBundle.session_id == body.session_id,
        FrameBundle.pair_id == body.pair_id,
        FrameBundle.calibration_profile == profile,
        FrameBundle.algorithm == algorithm,
    ))
    if duplicate is not None:
        raise HTTPException(409, "this session/pair detection bundle was already stored")
    pts_delta = (abs(frames[0].pts_ms - frames[1].pts_ms)
                 if all(frame.pts_ms is not None for frame in frames) else None)
    recv_delta = (abs(frames[0].recv_ms - frames[1].recv_ms)
                  if all(frame.recv_ms is not None for frame in frames) else None)
    # `ts` includes the edge's measured per-camera delay correction. Keep the
    # raw receive and presentation times for diagnostics only.
    sync_time_basis = "ts"
    sync_delta = abs(frames[0].ts - frames[1].ts)
    if sync_delta > max_sync_delta_ms:
        raise HTTPException(422, f"frame {sync_time_basis} differ by {sync_delta}ms "
                                 f"(session maximum {max_sync_delta_ms}ms)")

    cameras = [db.get(Camera, (body.session_id, frame.camera_id, profile)) for frame in frames]
    missing = [frame.camera_id for frame, camera in zip(frames, cameras) if camera is None]
    if missing:
        raise HTTPException(404, f"camera calibration not found: {', '.join(missing)}")
    for frame, camera in zip(frames, cameras):
        if tuple(frame.image_size) != (camera.image_width, camera.image_height):
            raise HTTPException(422, f"image_size does not match calibration for {frame.camera_id}")

    calibrations = [_calibration(camera) for camera in cameras]
    essential = fundamental_matrix(*calibrations)
    pixel_scale = float(np.mean([c.K[0, 0] for c in calibrations] + [c.K[1, 1] for c in calibrations]))
    bundle = FrameBundle(session_id=body.session_id, pair_id=body.pair_id,
                         calibration_profile=profile, algorithm=algorithm, sync_delta_ms=sync_delta,
                         source_frames=[frame.model_dump(mode="json") for frame in frames])
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
                               camera_id=frame.camera_id, calibration_profile=profile,
                               algorithm=algorithm,
                               frame_id=frame.frame_id,
                               captured_at_ms=frame.ts, track_id=item.track_id, cls=item.cls,
                               confidence=round(item.conf, 3), bbox=list(item.bbox),
                               foot_pixel=list(foot), foot_src=foot_source,
                               ankles=(item.ankles.model_dump(mode="json") if item.ankles else None))
            db.add(record)
            records[frame.camera_id].append((item, record, foot, foot_source))
            normalized[frame.camera_id].append(undistort(foot, calibration))

    matches, used = [], [set(), set()]
    floor_entries = []   # C 바닥 좌표 추적에 넘길 사람 위치들

    def match_stage(object_class, indexes, forced_source=None):
        points = [[normalized[frame.camera_id][i] for i in indexes[n]] for n, frame in enumerate(frames)]
        candidate_worlds, candidate_points, candidate_pixels, ground_distances = {}, {}, {}, {}

        def source(n, local):
            if forced_source is not None:
                return forced_source
            return records[frames[n].camera_id][indexes[n][local]][3]

        def points_for_pair(local1, local2):
            key = (local1, local2)
            if key in candidate_points:
                return candidate_points[key]
            pair = (points[0][local1], points[1][local2])
            if _should_complete_box_foot(object_class, source(0, local1), source(1, local2)):
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
                rows = (records[frames[0].camera_id][indexes[0][local1]],
                        records[frames[1].camera_id][indexes[1][local2]])
                candidate_pixels[key] = tuple(
                    foot_point(row[0].bbox) if forced_source == "box" else row[2]
                    for row in rows
                )
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

        def ground_cost(local1, local2):
            key = (local1, local2)
            point1, point2 = points_for_pair(local1, local2)
            plane_z = 0.1 if source(0, local1) == source(1, local2) == "ankle" else 0.0
            positions = [position_on_plane(point, calibration, plane_z)
                         for point, calibration in zip((point1, point2), calibrations)]
            distance = float(np.linalg.norm(positions[0][:2] - positions[1][:2]))
            ground_distances[key] = distance
            return distance

        if matching_method == "ground-plane":
            stage_matches = match_by_cost(len(points[0]), len(points[1]), ground_cost,
                                          MAX_GROUND_DISTANCE_M, valid_candidate)
            max_matching_cost = MAX_GROUND_DISTANCE_M

            def pair_cost(row, col):
                return ground_cost(row, col)
        else:
            stage_matches = match_class(points[0], points[1], essential, pixel_scale,
                                        MAX_EPIPOLAR_ERROR_PX, valid_candidate, points_for_pair)
            max_matching_cost = MAX_EPIPOLAR_ERROR_PX

            def pair_cost(row, col):
                return symmetric_epipolar_distance(*points_for_pair(row, col), essential) * pixel_scale

        if settings["track_pair_hold"]:
            stabilized, claimed_cols = [], set()
            candidates = []
            for local1, local2, cost in stage_matches:
                i = indexes[0][local1]
                track1 = records[frames[0].camera_id][i][0].track_id
                state = db.scalar(select(TrackPairState).where(
                    TrackPairState.session_id == body.session_id,
                    TrackPairState.calibration_profile == profile,
                    TrackPairState.algorithm == algorithm,
                    TrackPairState.cls == object_class,
                    TrackPairState.camera1_id == frames[0].camera_id,
                    TrackPairState.camera1_track_id == track1,
                ))
                candidates.append((state is None, local1, local2, cost, state))
            for _, local1, proposed_col, proposed_cost, state in sorted(candidates, key=lambda row: row[0]):
                chosen_col, chosen_cost = proposed_col, proposed_cost
                next_hysteresis = PairHysteresis()
                if state is not None:
                    incumbent_col = next((col for col, index in enumerate(indexes[1])
                                          if records[frames[1].camera_id][index][0].track_id
                                          == state.camera2_track_id), None)
                    challenger_col = next((col for col, index in enumerate(indexes[1])
                                           if records[frames[1].camera_id][index][0].track_id
                                           == state.challenger_track_id), None)
                    row_costs = []
                    for col in range(len(indexes[1])):
                        try:
                            cost = pair_cost(local1, col)
                            row_costs.append(cost if cost <= max_matching_cost and valid_candidate(local1, col)
                                             else np.inf)
                        except ValueError:
                            row_costs.append(np.inf)
                    locked_col, next_hysteresis = update_pair_hysteresis(
                        row_costs, incumbent_col,
                        PairHysteresis(challenger_col, state.challenger_streak),
                        TRACK_PAIR_CONFIRM_FRAMES, TRACK_PAIR_IMPROVEMENT_RATIO,
                    )
                    if locked_col is not None:
                        chosen_col, chosen_cost = locked_col, row_costs[locked_col]
                if chosen_col in claimed_cols and proposed_col not in claimed_cols:
                    chosen_col, chosen_cost = proposed_col, proposed_cost
                    next_hysteresis = PairHysteresis()
                if chosen_col in claimed_cols or not np.isfinite(chosen_cost):
                    continue
                claimed_cols.add(chosen_col)
                stabilized.append((local1, chosen_col, float(chosen_cost)))
                i, j = indexes[0][local1], indexes[1][chosen_col]
                item1 = records[frames[0].camera_id][i][0]
                item2 = records[frames[1].camera_id][j][0]
                if state is None:
                    state = TrackPairState(session_id=body.session_id,
                                           calibration_profile=profile, algorithm=algorithm,
                                           cls=object_class,
                                           camera1_id=frames[0].camera_id,
                                           camera1_track_id=item1.track_id,
                                           camera2_id=frames[1].camera_id,
                                           camera2_track_id=item2.track_id)
                    db.add(state)
                switched = state.camera2_track_id != item2.track_id
                state.camera2_id = frames[1].camera_id
                state.camera2_track_id = item2.track_id
                state.challenger_track_id = (None if switched or next_hysteresis.challenger is None
                                             else records[frames[1].camera_id]
                                             [indexes[1][next_hysteresis.challenger]][0].track_id)
                state.challenger_streak = (0 if switched else next_hysteresis.streak)
                state.last_pair_id = body.pair_id
            stage_matches = stabilized
        for local1, local2, matching_cost in stage_matches:
            i, j = indexes[0][local1], indexes[1][local2]
            item1, record1, _, _ = records[frames[0].camera_id][i]
            item2, record2, _, _ = records[frames[1].camera_id][j]
            source1, source2 = source(0, local1), source(1, local2)
            normalized_pair = points_for_pair(local1, local2)
            foot1, foot2 = candidate_pixels[(local1, local2)]
            epipolar_error = symmetric_epipolar_distance(*normalized_pair, essential) * pixel_scale
            world = candidate_worlds[(local1, local2)]
            position_method = "foot"
            if (settings["ankle_pairing"]
                    and object_class == "person" and item1.ankles and item2.ankles):
                ankle1 = {side: getattr(item1.ankles, side) for side in ("left", "right")
                          if getattr(item1.ankles, side) is not None}
                ankle2 = {side: getattr(item2.ankles, side) for side in ("left", "right")
                          if getattr(item2.ankles, side) is not None}
                layouts = (
                    (("left", "left"), ("right", "right")),
                    (("left", "right"), ("right", "left")),
                )
                layout_candidates = []
                for layout in layouts:
                    pairs = []
                    for side1, side2 in layout:
                        if side1 not in ankle1 or side2 not in ankle2:
                            continue
                        point1, point2 = ankle1[side1], ankle2[side2]
                        if min(point1.root[2], point2.root[2]) < MIN_ANKLE_CONFIDENCE:
                            continue
                        normalized_ankles = (
                            undistort(point1.root[:2], calibrations[0]),
                            undistort(point2.root[:2], calibrations[1]),
                        )
                        error = symmetric_epipolar_distance(
                            *normalized_ankles, essential) * pixel_scale
                        pairs.append((side1, side2, point1, point2, normalized_ankles, error))
                    if pairs:
                        layout_candidates.append((float(np.mean([pair[5] for pair in pairs])), pairs))

                ankle_worlds = []
                accepted_pairs = []
                if layout_candidates:
                    _, selected_pairs = min(layout_candidates, key=lambda candidate: candidate[0])
                else:
                    selected_pairs = []
                for side1, side2, point1, point2, ankle_pair, error in selected_pairs:
                    try:
                        ankle_world = triangulate(*ankle_pair, *calibrations)
                        if ANKLE_FOOT_Z_MIN <= ankle_world[2] <= ANKLE_FOOT_Z_MAX:
                            ankle_worlds.append(ankle_world)
                            accepted_pairs.append((side1, side2, point1, point2, error))
                    except ValueError:
                        pass
                if accepted_pairs:
                    world = np.mean(ankle_worlds, axis=0)
                    foot1 = tuple(np.mean([pair[2].root[:2] for pair in accepted_pairs], axis=0))
                    foot2 = tuple(np.mean([pair[3].root[:2] for pair in accepted_pairs], axis=0))
                    normalized_pair = tuple(undistort(pixel, calibration)
                                            for pixel, calibration in zip((foot1, foot2), calibrations))
                    position_method = "mid" if len(accepted_pairs) == 2 else accepted_pairs[0][0]
                    source1 = source2 = "ankle"
                    epipolar_error = float(np.mean([pair[4] for pair in accepted_pairs]))
            if _should_use_box_plane(object_class, source1, source2):
                try:
                    positions = [position_on_plane(point, calibration, 0.0)
                                 for point, calibration in zip(normalized_pair, calibrations)]
                except ValueError as exc:
                    if "parallel" not in str(exc):
                        continue
                    positions = [world, world]
                world = (combine_plane_positions(positions, calibrations)
                         if BBOX_POSITION_METHOD == "weighted-plane" else np.mean(positions, axis=0))
            object_id = _object_id(db, body.session_id, profile, algorithm,
                                   frames[0].camera_id, item1.track_id,
                                   frames[1].camera_id, item2.track_id, object_class,
                                   visible_tracks, used_object_ids)
            used_object_ids.add(object_id)
            raw_world = np.asarray(world, dtype=float)
            timestamp_ms = max(frame.ts for frame in frames)
            use_floor = settings["floor_tracking"] and object_class == "person"
            if use_floor:   # 사람은 C가 묶음 끝에서 번호·위치를 다시 정한다 (칼만 포함)
                world, velocity = raw_world, None
            else:
                world, velocity = _filter_motion(db, body.session_id, profile, algorithm,
                                                 object_id, raw_world, timestamp_ms)
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
                                 "foot_pixel": foot1, "foot_src": source1,
                                 "position_method": position_method},
                                {"camera_id": frames[1].camera_id, "frame_id": frames[1].frame_id, "ts": frames[1].ts,
                                 "track_id": item2.track_id, "cls": item2.cls, "conf": round(item2.conf, 3),
                                 "bbox": item2.bbox, "image_size": frames[1].image_size,
                                 "foot_pixel": foot2, "foot_src": source2,
                                 "position_method": position_method},
                            ],
                            "world": {"x": world[0], "y": world[1], "z": world[2]},
                            "raw_world": ({"x": raw_world[0], "y": raw_world[1], "z": raw_world[2]}
                                          if settings["kalman_filter"] or use_floor else None),
                            "velocity": ({"x": velocity[0], "y": velocity[1], "z": velocity[2]}
                                         if velocity is not None else None),
                            "epipolar_error_px": round(epipolar_error, 3),
                            "matching_method": matching_method,
                            "ground_distance_m": (round(matching_cost, 4)
                                                  if matching_method == "ground-plane" else None)})
            if use_floor:
                floor_entries.append({"match": matches[-1], "records": (record1, record2), "raw": raw_world,
                                      "normalized": normalized_pair})

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
    if settings["floor_tracking"]:
        singles = []
        if settings["single_camera_fallback"]:   # 짝이 안 된 사람 탐지 (D가 C 트랙에 이어 붙일 후보)
            for n, frame in enumerate(frames):
                for i, (item, record, foot, foot_source) in enumerate(records[frame.camera_id]):
                    if item.cls == "person" and i not in used[n]:
                        singles.append({"camera": n, "index": i, "used": used[n], "item": item,
                                        "record": record, "foot": foot, "foot_source": foot_source,
                                        "normalized": normalized[frame.camera_id][i]})
        if floor_entries or singles:
            matches.extend(_apply_floor_tracking(db, body.session_id, profile, algorithm, settings,
                                                 floor_entries, singles, frames, calibrations))
    risks = []
    hysteresis = settings["warning_hysteresis"]
    if ENABLE_RISK_ANALYSIS or hysteresis:
        for first, second in combinations(matches, 2):
            if first["cls"] != "person" and second["cls"] != "person":
                continue
            people = first["cls"] == "person" and second["cls"] == "person"
            if not ENABLE_RISK_ANALYSIS and not people:   # F만 켜면 사람-사람 경고만 계산
                continue
            position1 = [first["world"][axis] for axis in ("x", "y", "z")]
            position2 = [second["world"][axis] for axis in ("x", "y", "z")]
            velocity1 = ([first["velocity"][axis] for axis in ("x", "y", "z")]
                         if first.get("velocity") else [0.0, 0.0, 0.0])
            velocity2 = ([second["velocity"][axis] for axis in ("x", "y", "z")]
                         if second.get("velocity") else [0.0, 0.0, 0.0])
            result = calculate_pair_risk(position1, velocity1, position2, velocity2,
                                         WARNING_DISTANCE_M, DANGER_DISTANCE_M)
            object1_id, object2_id = sorted((first["object_id"], second["object_id"]))
            level = result.level
            if hysteresis and people:
                level = _risk_level_with_hysteresis(db, body.session_id, profile, algorithm,
                                                    object1_id, object2_id, result.distance_m)
            risk = {"object1_id": object1_id, "object2_id": object2_id,
                    "distance_m": result.distance_m, "ttc_s": result.ttc_s, "level": level}
            risks.append(risk)
            db.add(RiskEvent(bundle_id=bundle.id, session_id=body.session_id,
                             captured_at_ms=max(frame.ts for frame in frames), **risk))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "this camera/frame/track detection was already stored") from exc
    unmatched = {frame.camera_id: [row[0].track_id for i, row in enumerate(records[frame.camera_id]) if i not in used[n]]
                 for n, frame in enumerate(frames)}
    return {"bundle_id": bundle.id, "session_id": body.session_id, "pair_id": body.pair_id,
            "calibration_profile": profile, "sync_delta_ms": sync_delta,
            "pts_delta_ms": pts_delta, "recv_delta_ms": recv_delta,
            "sync_time_basis": sync_time_basis, "max_sync_delta_ms": max_sync_delta_ms,
            "matches": matches, "unmatched": unmatched,
            "risks": risks, "settings": settings}


@router.post("/detections", response_model=DetectionBundleOut, status_code=status.HTTP_201_CREATED)
def create_detections(body: DetectionBundleIn, db: Session = Depends(get_db)):
    return _create_detections(body, db, algorithm="baseline")


@router.post("/sessions/{session_id}/recompute")
def recompute_session(session_id: str, profile: CalibrationProfile,
                      algorithm: Algorithm = "baseline", db: Session = Depends(get_db)):
    """Re-run the original edge observations for one experiment condition."""
    _checked_algorithm(algorithm)
    source_profile, source_algorithm = "basic", "baseline"
    if (profile, algorithm) == (source_profile, source_algorithm):
        source_profile = "precise"
    source_bundles = db.scalars(select(FrameBundle).where(
        FrameBundle.session_id == session_id,
        FrameBundle.calibration_profile == source_profile,
        FrameBundle.algorithm == source_algorithm,
    ).order_by(FrameBundle.pair_id)).all()
    if not source_bundles:
        raise HTTPException(404, f"no {source_profile}/{source_algorithm} detections found for this session")

    payloads = []
    for bundle in source_bundles:
        frames = bundle.source_frames
        if not frames:
            raise HTTPException(409, "stored bundle has no source frames; upload it again after migration")
        source_settings = db.get(SessionSettings, (session_id, source_profile, source_algorithm))
        max_sync_delta_ms = ((source_settings.settings or {}).get("max_sync_delta_ms", MAX_SYNC_DELTA_MS)
                             if source_settings else MAX_SYNC_DELTA_MS)
        payloads.append(DetectionBundleIn(session_id=session_id, pair_id=bundle.pair_id,
                                          calibration_profile=profile, frames=frames,
                                          max_sync_delta_ms=max_sync_delta_ms))

    camera_ids = {frame.camera_id for payload in payloads for frame in payload.frames}
    missing_targets = [camera_id for camera_id in sorted(camera_ids)
                       if db.get(Camera, (session_id, camera_id, profile)) is None]
    if missing_targets:
        raise HTTPException(404, f"target calibration not found: {', '.join(missing_targets)}")

    target_bundle_ids = list(db.scalars(select(FrameBundle.id).where(
        FrameBundle.session_id == session_id,
        FrameBundle.calibration_profile == profile,
        FrameBundle.algorithm == algorithm,
    )).all())
    if target_bundle_ids:
        db.execute(delete(RiskEvent).where(RiskEvent.bundle_id.in_(target_bundle_ids)))
        db.execute(delete(Detection).where(Detection.bundle_id.in_(target_bundle_ids)))
        db.execute(delete(FrameBundle).where(FrameBundle.id.in_(target_bundle_ids)))
    target_objects = list(db.scalars(select(GlobalObject.id).where(
        GlobalObject.session_id == session_id,
        GlobalObject.calibration_profile == profile,
        GlobalObject.algorithm == algorithm,
    )).all())
    for table in (FloorTrack, RiskPairState):
        db.execute(delete(table).where(
            table.session_id == session_id,
            table.calibration_profile == profile,
            table.algorithm == algorithm,
        ))
    if target_objects:
        db.execute(delete(ObjectMotionState).where(ObjectMotionState.object_id.in_(target_objects)))
        db.execute(delete(TrackLink).where(TrackLink.object_id.in_(target_objects)))
        db.execute(delete(GlobalObject).where(GlobalObject.id.in_(target_objects)))
    db.execute(delete(TrackPairState).where(
        TrackPairState.session_id == session_id,
        TrackPairState.calibration_profile == profile,
        TrackPairState.algorithm == algorithm,
    ))
    db.commit()

    results = [_create_detections(payload, db, algorithm=algorithm) for payload in payloads]
    return {"session_id": session_id, "source_profile": source_profile,
            "source_algorithm": source_algorithm, "calibration_profile": profile,
            "algorithm": algorithm, "recomputed_bundles": len(results)}


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
