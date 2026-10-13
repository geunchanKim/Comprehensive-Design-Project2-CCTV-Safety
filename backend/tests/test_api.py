import csv
import io
import os
from math import pi

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")
os.environ.setdefault("APP_COMMIT_SHA", "test-commit")
os.environ.setdefault("MAX_EPIPOLAR_ERROR_PX", "50")

from fastapi.testclient import TestClient

from sqlalchemy import select

import backend.api as api_module
from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import Camera, Detection, FrameBundle, ObjectMotionState, TrackPairState
from backend.schemas import DetectionBundleIn


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


client = TestClient(app)
K = [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]]
SESSION = "unity-classroom-01"


def put_camera(camera_id, tvec, session_id=SESSION):
    response = client.put(f"/cameras/{camera_id}/calibration", json={
        "session_id": session_id,
        "method": "unity-gt",
        "image_size": [1920, 1080],
        "K": K,
        "dist": [0, 0, 0, 0, 0],
        "rvec": [pi / 2, 0, 0],
        "tvec": tvec,
        "reproj_error_px": 0,
    })
    assert response.status_code == 200, response.text


def detection_payload(pair_id=1, session_id=SESSION, ts2=1020):
    return {"session_id": session_id, "pair_id": pair_id, "frames": [
        {"camera_id": "cam1", "frame_id": pair_id, "ts": 1000, "image_size": [1920, 1080],
         "detections": [{"track_id": 7, "cls": "person", "conf": 0.98765,
                         "bbox": [950, 400, 970, 540]}]},
        {"camera_id": "cam2", "frame_id": pair_id, "ts": ts2, "image_size": [1920, 1080],
         "detections": [{"track_id": 9, "cls": "person", "conf": 0.9,
                         "bbox": [850, 400, 870, 540]}]},
    ]}


def create_improved(payload):
    with SessionLocal() as db:
        return api_module._create_detections(
            DetectionBundleIn.model_validate(payload), db, algorithm="improved")


def test_health_exposes_deployment_settings():
    response = client.get("/health")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ok"
    assert result["commit"] == "test-commit"
    assert result["algorithms"]["baseline"] | {
        "matching_method": "epipolar", "kalman_filter": False,
        "track_pair_hold": False, "ankle_pairing": False,
    } == result["algorithms"]["baseline"]
    assert result["algorithms"]["improved"] | {
        "matching_method": "ground-plane", "kalman_filter": True,
        "track_pair_hold": True, "ankle_pairing": True,
    } == result["algorithms"]["improved"]


def test_improved_features_can_be_disabled_individually(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_KALMAN_FILTER", False)
    assert api_module._algorithm_settings("improved") == {
        "matching_method": "ground-plane", "kalman_filter": False,
        "track_pair_hold": True, "ankle_pairing": True,
    }
    monkeypatch.setattr(api_module, "ENABLE_KALMAN_FILTER", True)
    monkeypatch.setattr(api_module, "ENABLE_TRACK_PAIR_HOLD", False)
    assert api_module._algorithm_settings("improved") == {
        "matching_method": "ground-plane", "kalman_filter": True,
        "track_pair_hold": False, "ankle_pairing": True,
    }


def test_box_foot_completion_keeps_people_chairs_and_suitcases():
    assert api_module._should_complete_box_foot("person", "box", "box")
    assert api_module._should_complete_box_foot("chair", "box", "box")
    assert api_module._should_complete_box_foot("suitcase", "box", "box")
    for object_class in ("cart", "desk", "backpack"):
        assert not api_module._should_complete_box_foot(object_class, "box", "box")
    assert not api_module._should_complete_box_foot("chair", "ankle", "box")


def test_box_plane_is_limited_to_chair_and_suitcase(monkeypatch):
    monkeypatch.setattr(api_module, "BBOX_POSITION_METHOD", "plane")
    assert api_module._should_use_box_plane("chair", "box", "box")
    assert api_module._should_use_box_plane("suitcase", "box", "box")
    for object_class in ("person", "cart", "desk", "backpack"):
        assert not api_module._should_use_box_plane(object_class, "box", "box")


def test_corrected_timestamps_drive_session_sync_tolerance():
    session_id = "receive-timestamps"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=208, session_id=session_id)
    payload["max_sync_delta_ms"] = 80
    for frame, pts, recv in zip(payload["frames"], (100.0, 140.5), (10_000, 10_100)):
        frame.update(pts_ms=pts, recv_ms=recv)

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["sync_delta_ms"] == 20
    assert response.json()["pts_delta_ms"] == 40.5
    assert response.json()["recv_delta_ms"] == 100
    assert response.json()["sync_time_basis"] == "ts"
    assert response.json()["max_sync_delta_ms"] == 80

    changed = detection_payload(pair_id=209, session_id=session_id, ts2=2020)
    changed["frames"][0]["ts"] = 2000
    changed["max_sync_delta_ms"] = 50
    assert client.post("/detections", json=changed).status_code == 409


def test_detection_bundle_returns_world_coordinate_and_contract_ids():
    put_camera("cam1", [0, 0, 0])
    put_camera("cam2", [-1, 0, 0])
    response = client.post("/detections", json=detection_payload())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["session_id"] == SESSION
    assert result["pair_id"] == 1
    assert result["sync_delta_ms"] == 20
    assert result["matches"][0]["object_id"] >= 1
    assert result["matches"][0]["observations"][0]["conf"] == 0.988
    assert result["matches"][0]["observations"][0]["foot_pixel"] == [960.0, 540.0]
    assert result["matches"][0]["observations"][0]["foot_src"] == "box"
    assert abs(result["matches"][0]["world"]["y"] - 10) < 0.01
    assert abs(result["matches"][0]["world"]["z"]) < 0.01


def test_profiles_store_independent_results_and_recompute_without_edge_upload(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_KALMAN_FILTER", True)
    monkeypatch.setattr(api_module, "MAX_GROUND_DISTANCE_M", 100.0)
    session_id = "profile-recompute"
    for profile in ("basic", "precise"):
        for camera_id, tvec in (("cam1", [0, 0, 0]), ("cam2", [-1, 0, 0])):
            payload = {
                "session_id": session_id, "calibration_profile": profile,
                "method": "unity-gt", "image_size": [1920, 1080], "K": K,
                "dist": [0, 0, 0, 0, 0], "rvec": [pi / 2, 0, 0],
                "tvec": tvec, "reproj_error_px": 0,
            }
            assert client.put(f"/cameras/{camera_id}/calibration", json=payload).status_code == 200
    payload = detection_payload(pair_id=101, session_id=session_id)
    payload["calibration_profile"] = "basic"
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    response = client.post("/detections", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["calibration_profile"] == "basic"

    response = client.post(f"/sessions/{session_id}/recompute?profile=precise&algorithm=improved")
    assert response.status_code == 200, response.text
    assert response.json()["recomputed_bundles"] == 1
    # 같은 원본 타임스탬프를 다시 처리해도 대상 프로필 상태를 먼저 지우므로
    # 칼만 dt <= 0 오류가 발생하지 않아야 한다.
    response = client.post(f"/sessions/{session_id}/recompute?profile=precise&algorithm=improved")
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        bundles = db.scalars(select(FrameBundle).where(FrameBundle.session_id == session_id)).all()
        detections = db.scalars(select(Detection).where(Detection.session_id == session_id)).all()
        motion_states = db.scalars(select(ObjectMotionState).where(
            ObjectMotionState.session_id == session_id)).all()
    assert {bundle.calibration_profile for bundle in bundles} == {"basic", "precise"}
    assert {row.calibration_profile for row in detections} == {"basic", "precise"}
    assert {(row.calibration_profile, row.algorithm) for row in motion_states} == {
        ("precise", "improved")}
    object_ids = {
        profile: {row.object_id for row in detections if row.calibration_profile == profile}
        for profile in ("basic", "precise")
    }
    assert object_ids["basic"].isdisjoint(object_ids["precise"])


def test_one_upload_produces_all_four_experiment_conditions():
    session_id = "four-conditions"
    for profile in ("basic", "precise"):
        for camera_id, tvec in (("cam1", [0, 0, 0]), ("cam2", [-1, 0, 0])):
            payload = {"session_id": session_id, "calibration_profile": profile,
                       "method": "unity-gt", "image_size": [1920, 1080], "K": K,
                       "dist": [0, 0, 0, 0, 0], "rvec": [pi / 2, 0, 0],
                       "tvec": tvec, "reproj_error_px": 0}
            assert client.put(f"/cameras/{camera_id}/calibration", json=payload).status_code == 200
    payload = detection_payload(pair_id=1, session_id=session_id)
    assert client.post("/detections", json=payload).status_code == 201
    for profile, algorithm in (("precise", "baseline"), ("basic", "improved"),
                               ("precise", "improved")):
        response = client.post(
            f"/sessions/{session_id}/recompute?profile={profile}&algorithm={algorithm}")
        assert response.status_code == 200, response.text
        assert response.json()["algorithm"] == algorithm
        csv_response = client.get(
            f"/sessions/{session_id}/results.csv?profile={profile}&algorithm={algorithm}")
        assert csv_response.status_code == 200
    with SessionLocal() as db:
        conditions = set(db.execute(select(
            FrameBundle.calibration_profile, FrameBundle.algorithm
        ).where(FrameBundle.session_id == session_id)).all())
    assert conditions == {("basic", "baseline"), ("precise", "baseline"),
                          ("basic", "improved"), ("precise", "improved")}
    response = client.post(
        f"/sessions/{session_id}/recompute?profile=basic&algorithm=baseline")
    assert response.status_code == 200, response.text


def test_recompute_preserves_camera_frames_with_no_detections():
    session_id = "empty-camera-recompute"
    for profile in ("basic", "precise"):
        for camera_id, tvec in (("cam1", [0, 0, 0]), ("cam2", [-1, 0, 0])):
            payload = {"session_id": session_id, "calibration_profile": profile,
                       "method": "unity-gt", "image_size": [1920, 1080], "K": K,
                       "dist": [0, 0, 0, 0, 0], "rvec": [pi / 2, 0, 0],
                       "tvec": tvec, "reproj_error_px": 0}
            assert client.put(f"/cameras/{camera_id}/calibration", json=payload).status_code == 200
    payload = detection_payload(pair_id=1, session_id=session_id)
    payload["frames"][1]["detections"] = []
    assert client.post("/detections", json=payload).status_code == 201
    response = client.post(
        f"/sessions/{session_id}/recompute?profile=precise&algorithm=baseline")
    assert response.status_code == 200, response.text


def test_precise_pnp_stores_held_out_validation_error():
    session_id = "precise-pnp"
    grid_world = [(-2, -1, 0), (0, -1, 0), (2, -1, 0),
                  (-2, 1, 0), (0, 1, 0), (2, 1, 0)]
    validation_world = [(-1, 0.5, 0), (1.5, -0.5, 1)]

    def image_point(world):
        x, y, z = world
        return [960 + 1000 * x / (5 - z), 540 - 1000 * y / (5 - z)]

    response = client.post("/cameras/cam1/calibration/solve-pnp", json={
        "session_id": session_id, "image_size": [1920, 1080], "K": K,
        "dist": [0, 0, 0, 0, 0],
        "grid_points": [{"world": point, "image": image_point(point)} for point in grid_world],
        "validation_points": [{"world": point, "image": image_point(point)}
                              for point in validation_world],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["calibration_profile"] == "precise"
    assert result["validation_point_count"] == 2
    assert result["validation_rmse_cm"] < 0.01
    with SessionLocal() as db:
        stored = db.get(Camera, (session_id, "cam1", "precise"))
    assert stored.validation_point_count == 2


def test_download_session_results_csv():
    response = client.get(f"/sessions/{SESSION}/results.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "record_type,pair_id,frame_id,timestamp_ms" in response.text
    assert "position" in response.text
    assert '""matching_method"": ""epipolar""' in response.text


def test_crossing_mispair_keeps_distinct_object_ids_and_csv_rows():
    session_id = "crossing-mispair"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)

    def crossing_payload(pair_id, cam2_tracks):
        payload = detection_payload(pair_id=pair_id, session_id=session_id,
                                    ts2=pair_id * 1000 + 20)
        payload["frames"][0]["ts"] = pair_id * 1000
        payload["frames"][0]["detections"] = [
            {"track_id": 11, "cls": "person", "conf": 0.9,
             "bbox": [950, 400, 970, 540]},
            {"track_id": 12, "cls": "person", "conf": 0.9,
             "bbox": [750, 400, 770, 540]},
        ]
        payload["frames"][1]["detections"] = [
            {"track_id": cam2_tracks[0], "cls": "person", "conf": 0.9,
             "bbox": [850, 400, 870, 540]},
            {"track_id": cam2_tracks[1], "cls": "person", "conf": 0.9,
             "bbox": [650, 400, 670, 540]},
        ]
        return payload

    first = client.post("/detections", json=crossing_payload(1, (21, 22)))
    wrong = client.post("/detections", json=crossing_payload(2, (22, 21)))
    recovered = client.post("/detections", json=crossing_payload(3, (21, 22)))

    assert first.status_code == wrong.status_code == recovered.status_code == 201
    for response in (first, wrong, recovered):
        ids = [match["object_id"] for match in response.json()["matches"]]
        assert len(ids) == 2
        assert len(set(ids)) == 2
    assert {match["object_id"] for match in recovered.json()["matches"]} == {
        match["object_id"] for match in first.json()["matches"]
    }

    csv_response = client.get(f"/sessions/{session_id}/results.csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    positions = [row for row in rows if row["record_type"] == "position"]
    assert [sum(row["pair_id"] == str(pair_id) for row in positions)
            for pair_id in (1, 2, 3)] == [2, 2, 2]
    assert {row["frame_id"] for row in positions} == {"1", "2", "3"}


def test_reconnects_when_old_counterpart_track_is_no_longer_visible():
    session_id = "counterpart-reacquired"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    first = client.post("/detections", json=detection_payload(pair_id=1, session_id=session_id))

    payload = detection_payload(pair_id=2, session_id=session_id, ts2=2020)
    payload["frames"][0]["ts"] = 2000
    payload["frames"][1]["detections"][0]["track_id"] = 10
    reacquired = client.post("/detections", json=payload)

    assert first.status_code == reacquired.status_code == 201
    assert first.json()["matches"][0]["object_id"] == reacquired.json()["matches"][0]["object_id"]


def test_uses_and_stores_explicit_ankle_foot():
    session_id = "ankle-foot"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=20, session_id=session_id)
    payload["frames"][0]["detections"][0].update(foot=[960, 510], foot_src="ankle")
    payload["frames"][1]["detections"][0].update(foot=[860, 510], foot_src="ankle")

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    match = response.json()["matches"][0]
    assert abs(match["world"]["z"] - 0.3) < 0.01
    assert all(item["foot_src"] == "ankle" for item in match["observations"])
    with SessionLocal() as db:
        stored = db.scalars(select(Detection).where(Detection.session_id == session_id)).all()
    assert {row.foot_src for row in stored} == {"ankle"}
    assert {tuple(row.foot_pixel) for row in stored} == {(960, 510), (860, 510)}


def test_uses_midpoint_when_both_ankles_are_visible_and_stores_raw_ankles():
    session_id = "both-ankles"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=201, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 520], foot_src="ankle")
    payload["frames"][0]["detections"][0]["ankles"] = {
        "left": [950, 510, 0.9], "right": [970, 530, 0.8]}
    # Edge labels are intentionally reversed in camera 2.
    payload["frames"][1]["detections"][0]["ankles"] = {
        "left": [870, 530, 0.8], "right": [850, 510, 0.9]}

    result = create_improved(payload)

    match = result["matches"][0]
    assert {camera: tuple(point) for camera, point in match["foot_pixels"].items()} == {
        "cam1": (960.0, 520.0), "cam2": (860.0, 520.0)}
    assert {row["position_method"] for row in match["observations"]} == {"mid"}
    assert match["epipolar_error_px"] == 0
    with SessionLocal() as db:
        stored = db.scalars(select(Detection).where(Detection.session_id == session_id)).all()
    assert stored[0].ankles["left"] == [950.0, 510.0, 0.9]


def test_uses_single_same_side_ankle_when_confident():
    session_id = "single-ankle"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=202, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    payload["frames"][0]["detections"][0]["ankles"] = {"left": [960, 510, 0.9], "right": None}
    payload["frames"][1]["detections"][0]["ankles"] = {"left": [860, 510, 0.8], "right": None}

    result = create_improved(payload)

    match = result["matches"][0]
    assert {row["position_method"] for row in match["observations"]} == {"left"}
    assert abs(match["world"]["z"] - 0.3) < 0.01


def test_pairs_opposite_labels_when_single_ankles_have_lower_error():
    session_id = "opposite-single-ankles"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=207, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    payload["frames"][0]["detections"][0]["ankles"] = {"left": [960, 510, 0.9], "right": None}
    payload["frames"][1]["detections"][0]["ankles"] = {"left": None, "right": [860, 510, 0.9]}

    result = create_improved(payload)

    assert {row["position_method"] for row in result["matches"][0]["observations"]} == {"left"}


def test_single_ankle_below_confidence_threshold_falls_back_to_foot():
    session_id = "low-confidence-ankle"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=203, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
        frame["detections"][0]["ankles"] = {"left": [x, 510, 0.55], "right": None}

    result = create_improved(payload)

    match = result["matches"][0]
    assert {row["position_method"] for row in match["observations"]} == {"foot"}
    assert {camera: tuple(point) for camera, point in match["foot_pixels"].items()} == {
        "cam1": (960.0, 510.0), "cam2": (860.0, 510.0)}


def test_ankle_pairing_can_be_disabled(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_ANKLE_PAIRING", False)
    session_id = "disabled-ankle-pairing"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=204, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
        frame["detections"][0]["ankles"] = {"left": [x, 510, 0.9], "right": None}

    result = create_improved(payload)

    assert {row["position_method"] for row in result["matches"][0]["observations"]} == {"foot"}


def test_baseline_ignores_ankle_pairing_even_when_enabled():
    session_id = "baseline-ankle-pairing"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=205, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 520], foot_src="ankle")
        frame["detections"][0]["ankles"] = {"left": [x, 510, 0.9], "right": None}

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    match = response.json()["matches"][0]
    assert {row["position_method"] for row in match["observations"]} == {"foot"}
    assert match["foot_pixels"] == {"cam1": [960.0, 520.0], "cam2": [860.0, 520.0]}


def test_single_ankle_outside_height_range_falls_back_to_foot():
    session_id = "single-ankle-height-fallback"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=206, session_id=session_id)
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
        frame["detections"][0]["ankles"] = {"left": [x, 100, 0.9], "right": None}

    result = create_improved(payload)

    match = result["matches"][0]
    assert {row["position_method"] for row in match["observations"]} == {"foot"}
    assert {camera: tuple(point) for camera, point in match["foot_pixels"].items()} == {
        "cam1": (960.0, 510.0), "cam2": (860.0, 510.0)}


def test_falls_back_to_box_for_both_cameras_when_only_one_has_ankle():
    session_id = "mixed-foot-fallback"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=24, session_id=session_id)
    payload["frames"][0]["detections"][0].update(foot=[960, 510], foot_src="ankle")

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    observations = response.json()["matches"][0]["observations"]
    assert [item["foot_src"] for item in observations] == ["box", "box"]
    assert [item["foot_pixel"] for item in observations] == [[960.0, 540.0], [860.0, 540.0]]


def test_matches_ankles_first_then_remaining_people_by_box():
    session_id = "two-stage-person-matching"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=25, session_id=session_id)
    payload["frames"][0]["detections"] = [
        {"track_id": 11, "cls": "person", "conf": 0.9, "bbox": [950, 400, 970, 540],
         "foot": [960, 510], "foot_src": "ankle"},
        {"track_id": 12, "cls": "person", "conf": 0.9, "bbox": [750, 430, 770, 570]},
    ]
    payload["frames"][1]["detections"] = [
        {"track_id": 21, "cls": "person", "conf": 0.9, "bbox": [850, 400, 870, 540],
         "foot": [860, 510], "foot_src": "ankle"},
        {"track_id": 22, "cls": "person", "conf": 0.9, "bbox": [650, 430, 670, 570]},
    ]

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    matches = {match["camera_tracks"]["cam1"]: match for match in response.json()["matches"]}
    assert set(matches) == {11, 12}
    assert matches[11]["camera_tracks"]["cam2"] == 21
    assert {item["foot_src"] for item in matches[11]["observations"]} == {"ankle"}
    assert matches[12]["camera_tracks"]["cam2"] == 22
    assert {item["foot_src"] for item in matches[12]["observations"]} == {"box"}


def test_height_filter_rejects_box_pair_above_range():
    session_id = "box-too-high"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=21, session_id=session_id)
    payload["frames"][0]["detections"][0]["bbox"] = [950, 400, 970, 510]
    payload["frames"][1]["detections"][0]["bbox"] = [850, 400, 870, 510]

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["matches"] == []
    assert response.json()["unmatched"] == {"cam1": [7], "cam2": [9]}


def test_rejects_foot_outside_image():
    payload = detection_payload(pair_id=22, session_id="foot-outside")
    payload["frames"][0]["detections"][0]["foot"] = [1920, 540]

    response = client.post("/detections", json=payload)

    assert response.status_code == 422


def test_ignores_foot_source_when_foot_is_omitted():
    session_id = "source-without-foot"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=23, session_id=session_id)
    for frame in payload["frames"]:
        frame["detections"][0]["foot_src"] = "ankle"

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    assert all(item["foot_src"] == "box" for item in response.json()["matches"][0]["observations"])


def test_accepts_suitcase_and_backpack_classes():
    for pair_id, object_class in enumerate(("suitcase", "backpack"), start=10):
        session_id = f"class-{object_class}"
        put_camera("cam1", [0, 0, 0], session_id)
        put_camera("cam2", [-1, 0, 0], session_id)
        payload = detection_payload(pair_id=pair_id, session_id=session_id)
        for frame in payload["frames"]:
            frame["detections"][0]["cls"] = object_class

        response = client.post("/detections", json=payload)

        assert response.status_code == 201, response.text
        assert response.json()["matches"][0]["cls"] == object_class


def test_same_frame_and_tracks_are_allowed_in_another_session():
    other = "unity-classroom-02"
    put_camera("cam1", [0, 0, 0], other)
    put_camera("cam2", [-1, 0, 0], other)
    response = client.post("/detections", json=detection_payload(session_id=other))
    assert response.status_code == 201, response.text
    assert response.json()["matches"][0]["object_id"] != 1


def test_kalman_state_persists_position_and_velocity(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_KALMAN_FILTER", True)
    monkeypatch.setattr(api_module, "MAX_GROUND_DISTANCE_M", 100.0)
    session_id = "kalman-motion"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)

    first_payload = detection_payload(pair_id=30, session_id=session_id)
    for frame, x in zip(first_payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    for frame, recv in zip(first_payload["frames"], (10_000, 10_020)):
        frame["recv_ms"] = recv
    first = create_improved(first_payload)
    assert first["matches"][0]["velocity"] == {"x": 0.0, "y": 0.0, "z": 0.0}

    payload = detection_payload(pair_id=31, session_id=session_id, ts2=2020)
    payload["frames"][0]["ts"] = 2000
    for frame, x in zip(payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
        frame["detections"][0]["bbox"][0] += 10
        frame["detections"][0]["bbox"][2] += 10
        frame["detections"][0]["foot"][0] += 10
    for frame, recv in zip(payload["frames"], (10_001, 10_002)):
        frame["recv_ms"] = recv
    second = create_improved(payload)
    match = second["matches"][0]
    assert match["raw_world"] is not None
    assert abs(match["velocity"]["x"]) > 0
    with SessionLocal() as db:
        stored = db.get(ObjectMotionState, match["object_id"])
        assert stored is not None
        assert stored.timestamp_ms == 2020
        assert abs(stored.mean[3]) > 0


def test_track_pair_hold_persists_across_frames(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_TRACK_PAIR_HOLD", True)
    monkeypatch.setattr(api_module, "MAX_GROUND_DISTANCE_M", 100.0)
    session_id = "track-pair-hold"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)

    first_payload = detection_payload(pair_id=40, session_id=session_id)
    for frame, x in zip(first_payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    create_improved(first_payload)

    second_payload = detection_payload(pair_id=41, session_id=session_id, ts2=2020)
    second_payload["frames"][0]["ts"] = 2000
    for frame, x in zip(second_payload["frames"], (960, 860)):
        frame["detections"][0].update(foot=[x, 510], foot_src="ankle")
    create_improved(second_payload)

    with SessionLocal() as db:
        states = db.scalars(select(TrackPairState).where(TrackPairState.session_id == session_id)).all()
    assert len(states) == 1
    assert states[0].camera1_track_id == 7
    assert states[0].camera2_track_id == 9
    assert states[0].last_pair_id == 41


def test_baseline_keeps_kalman_and_pair_hold_off(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_KALMAN_FILTER", True)
    monkeypatch.setattr(api_module, "ENABLE_TRACK_PAIR_HOLD", True)
    session_id = "baseline-improvements-off"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)

    response = client.post("/detections", json=detection_payload(pair_id=42, session_id=session_id))

    assert response.status_code == 201, response.text
    assert response.json()["matches"][0]["raw_world"] is None
    with SessionLocal() as db:
        assert not db.scalars(select(ObjectMotionState).where(
            ObjectMotionState.session_id == session_id)).all()
        assert not db.scalars(select(TrackPairState).where(
            TrackPairState.session_id == session_id)).all()


def test_risk_analysis_excludes_non_person_pairs(monkeypatch):
    monkeypatch.setattr(api_module, "ENABLE_RISK_ANALYSIS", True)
    session_id = "person-risk-only"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    payload = detection_payload(pair_id=45, session_id=session_id)
    for frame in payload["frames"]:
        base = frame["detections"][0]
        frame["detections"].extend([
            {"track_id": 20, "cls": "chair", "conf": 0.9,
             "bbox": list(base["bbox"])},
            {"track_id": 21, "cls": "chair", "conf": 0.9,
             "bbox": [value + (20 if index in (0, 2) else 0)
                      for index, value in enumerate(base["bbox"])]},
        ])

    response = client.post("/detections", json=payload)

    assert response.status_code == 201, response.text
    result = response.json()
    assert len(result["matches"]) == 3
    person_id = next(match["object_id"] for match in result["matches"]
                     if match["cls"] == "person")
    assert len(result["risks"]) == 2
    assert all(person_id in (risk["object1_id"], risk["object2_id"])
               for risk in result["risks"])


def test_session_rejects_changed_experiment_settings(monkeypatch):
    session_id = "immutable-settings"
    put_camera("cam1", [0, 0, 0], session_id)
    put_camera("cam2", [-1, 0, 0], session_id)
    first = client.post("/detections", json=detection_payload(pair_id=50, session_id=session_id))
    assert first.status_code == 201, first.text
    assert first.json()["settings"]["matching_method"] == "epipolar"

    monkeypatch.setattr(api_module, "BBOX_POSITION_METHOD", "plane")
    payload = detection_payload(pair_id=51, session_id=session_id, ts2=2020)
    payload["frames"][0]["ts"] = 2000
    changed = client.post("/detections", json=payload)

    assert changed.status_code == 409
    assert "different experiment settings" in changed.json()["detail"]


def test_rejects_duplicate_pair_in_same_session():
    assert client.post("/detections", json=detection_payload()).status_code == 409


def test_rejects_out_of_sync_bundle():
    response = client.post("/detections", json=detection_payload(pair_id=2, ts2=1051))
    assert response.status_code == 422


def test_ground_truth_is_stored_and_duplicate_is_rejected():
    payload = {
        "session_id": SESSION,
        "frame": 1,
        "ts": 1000,
        "objects": [{
            "object_id": "person_1",
            "cls": "person",
            "world": [3.12, 4.05, 0],
            "bbox": {"cam1": [810, 298, 907, 612], "cam2": [400, 279, 482, 591]},
        }],
    }
    response = client.post("/ground-truth", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["object_count"] == 1
    assert client.post("/ground-truth", json=payload).status_code == 409
