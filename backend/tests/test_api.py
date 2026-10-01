import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")

from fastapi.testclient import TestClient

from backend.database import Base, engine
from backend.main import app


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


client = TestClient(app)
K = [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]]


def put_camera(camera_id, t):
    response = client.put(f"/cameras/{camera_id}", json={"camera_id": camera_id, "image_size": [1920, 1080],
                          "K": K, "dist": [0, 0, 0, 0, 0],
                          "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "t": t})
    assert response.status_code == 200


def test_detection_bundle_returns_world_coordinate_and_stable_id():
    put_camera("cam1", [0, 0, 0])
    put_camera("cam2", [-1, 0, 0])
    payload = {"frames": [
        {"camera_id": "cam1", "frame_id": 1, "ts": 1000, "image_size": [1920, 1080],
         "detections": [{"track_id": 7, "cls": "person", "conf": 0.98765, "bbox": [950, 400, 970, 540]}]},
        {"camera_id": "cam2", "frame_id": 1, "ts": 1020, "image_size": [1920, 1080],
         "detections": [{"track_id": 9, "cls": "person", "conf": 0.9, "bbox": [850, 400, 870, 540]}]},
    ]}
    response = client.post("/detections", json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["sync_delta_ms"] == 20
    assert result["matches"][0]["object_id"] == 1
    assert result["matches"][0]["observations"][0]["conf"] == 0.988
    assert result["matches"][0]["observations"][0]["foot_pixel"] == [960.0, 540.0]
    assert abs(result["matches"][0]["world"]["z"] - 10) < 0.01


def test_rejects_out_of_sync_bundle():
    payload = {"frames": [
        {"camera_id": "cam1", "frame_id": 2, "ts": 1000, "detections": []},
        {"camera_id": "cam2", "frame_id": 2, "ts": 1051, "detections": []},
    ]}
    assert client.post("/detections", json=payload).status_code == 422
