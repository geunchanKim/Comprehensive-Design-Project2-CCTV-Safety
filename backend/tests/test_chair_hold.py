"""Chair occlusion lifetime, risk path and condition isolation."""
import pytest
from backend.tests.test_week2 import configured, client, setup_module
from backend.tests.test_api import detection_payload


@pytest.mark.parametrize("algorithm", ["f-cd", "baseline"])
def test_chair_hold_lifetime_and_risks(configured, monkeypatch, algorithm):
    import backend.api as api
    monkeypatch.setattr(api, "LIVE_ALGORITHM", algorithm)
    monkeypatch.setattr(api, "ENABLE_RISK_ANALYSIS", True)
    key, config = configured
    key = {**key, "algorithm": algorithm}
    if algorithm != "baseline":
        assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201

    def send(pair, timestamp, chair):
        payload = detection_payload(pair_id=pair, session_id=key["session_id"], ts2=timestamp)
        for frame in payload["frames"]:
            frame["ts"] = timestamp
            if chair:
                frame["detections"].append({
                    "track_id": 99, "cls": "chair", "conf": .9,
                    "bbox": list(frame["detections"][0]["bbox"]),
                })
        response = client.post("/detections", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    first = send(1, 1000, True)
    real, = [m for m in first["matches"] if m["cls"] == "chair"]
    for pair, timestamp in [(2, 2000), (3, 4000)]:
        result = send(pair, timestamp, False)
        chairs = [m for m in result["matches"] if m["cls"] == "chair"]
        if algorithm == "baseline":
            assert chairs == []
            continue
        held, = chairs
        assert held["object_id"] == real["object_id"]
        assert held["world"] == real["world"]
        assert held["position_source"] == "held"
        assert held["position_observed_at_ms"] == 1000
        assert held["observations"] == [] and held["camera_tracks"] == {}
        assert any(real["object_id"] in (r["object1_id"], r["object2_id"]) for r in result["risks"])
        snapshot = client.get("/dashboard/snapshot", params=key).json()
        assert next(o for o in snapshot["objects"] if o["cls"] == "chair")["position_source"] == "held"
    assert not any(m["cls"] == "chair" for m in send(4, 4001, False)["matches"])
    renewed = send(5, 4100, True)
    chairs = [m for m in renewed["matches"] if m["cls"] == "chair"]
    assert len(chairs) == 1 and chairs[0]["position_source"] != "held"


def test_hold_isolation_and_future_observation(configured, monkeypatch):
    from backend.chair_hold import hold_chairs
    from backend.database import SessionLocal
    from backend.models import Detection
    from sqlalchemy import select
    key, _ = configured
    payload = detection_payload(session_id=key["session_id"])
    for frame in payload["frames"]:
        frame["detections"][0]["cls"] = "chair"
    response = client.post("/detections", json=payload)
    assert response.status_code == 201
    assert response.json()["matches"]
    with SessionLocal() as db:
        for session, profile, algorithm, timestamp in [
            (key["session_id"] + "other", "basic", "baseline", 2000),
            (key["session_id"], "precise", "baseline", 2000),
            (key["session_id"], "basic", "f-cd", 2000),
            (key["session_id"], "basic", "baseline", 999),
        ]:
            matches = []
            hold_chairs(db, session, profile, algorithm, timestamp, matches)
            assert matches == []
        matches = []
        hold_chairs(db, key["session_id"], "basic", "baseline", 2000, matches)
        assert len(matches) == 1
        # The held result did not create fake observations in persistent history.
        assert len(list(db.scalars(select(Detection).where(
            Detection.session_id == key["session_id"])))) == 2
