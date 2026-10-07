import os
from math import pi

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")
os.environ.setdefault("APP_COMMIT_SHA", "test-commit")
os.environ.setdefault("MAX_EPIPOLAR_ERROR_PX", "50")

from fastapi.testclient import TestClient

from sqlalchemy import select

from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import Detection


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


def test_health_exposes_deployment_settings():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "commit": "test-commit",
        "max_epipolar_error_px": 50.0,
        "box_foot_z_min": -0.35,
        "box_foot_z_max": 0.2,
        "ankle_foot_z_min": -0.1,
        "ankle_foot_z_max": 0.4,
        "bbox_position_method": "triangulate",
    }


def test_detection_bundle_returns_world_coordinate_and_contract_ids():
    put_camera("cam1", [0, 0, 0])
    put_camera("cam2", [-1, 0, 0])
    response = client.post("/detections", json=detection_payload())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["session_id"] == SESSION
    assert result["pair_id"] == 1
    assert result["sync_delta_ms"] == 20
    assert result["matches"][0]["object_id"] == 1
    assert result["matches"][0]["observations"][0]["conf"] == 0.988
    assert result["matches"][0]["observations"][0]["foot_pixel"] == [960.0, 540.0]
    assert result["matches"][0]["observations"][0]["foot_src"] == "box"
    assert abs(result["matches"][0]["world"]["y"] - 10) < 0.01
    assert abs(result["matches"][0]["world"]["z"]) < 0.01


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
