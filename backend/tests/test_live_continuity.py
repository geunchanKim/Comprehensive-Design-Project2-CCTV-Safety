"""Live condition, durable grace, and stale input regressions."""
import pytest
from backend.tests.test_week2 import configured, client, setup_module
from backend.tests.test_api import detection_payload
from backend.dashboard import DashboardSnapshot
from backend.database import SessionLocal
from backend.schemas import RiskResult


def test_live_algorithm_routes_results_and_snapshot(configured, monkeypatch):
    import backend.api as api
    key, config = configured
    key = {**key, "algorithm": "f-cd"}
    assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201
    monkeypatch.setattr(api, "LIVE_ALGORITHM", "f-cd")
    response = client.post("/detections", json=detection_payload(session_id=key["session_id"]))
    assert response.status_code == 201, response.text
    assert response.json()["settings"]["single_camera_fallback"]
    snapshot = client.get("/dashboard/snapshot", params=key).json()
    assert snapshot["algorithm"] == "f-cd" and snapshot["seq"] == 1
    assert client.get("/dashboard/snapshot", params={**key, "algorithm": "baseline"}).status_code == 204


def test_collision_grace_preserves_ack_and_expires(configured):
    from backend.alerts import sync_alerts
    key, _ = configured
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    snapshot = DashboardSnapshot.model_validate(client.get("/dashboard/snapshot", params=key).json())
    snapshot.zone_evaluated = False
    snapshot.collision_evaluated = True
    risk = RiskResult(object1_id=10, object2_id=20, distance_m=.8, ttc_s=None, level="warning")
    def save(now, present):
        snapshot.risks = [risk] if present else []
        with SessionLocal() as db:
            rows = sync_alerts(db, tuple(key.values()), snapshot, now)
            db.commit()
            return [r for r in rows if r.kind == "collision"]
    first, = save(1000, True)
    path = f"/alerts/{first.alert_id}/ack"
    assert client.post(path, params=key, json={"action": "radio"}).status_code == 204
    held, = save(1300, False)
    assert held.alert_id == first.alert_id and held.last_seen_at_ms == 1000
    same, = save(2000, True)
    assert same.alert_id == first.alert_id and same.acknowledged
    assert save(3001, False) == []
    new, = save(3100, True)
    assert new.alert_id != first.alert_id
    save(3300, False)
    later, = save(4200, True)
    assert later.alert_id != new.alert_id


@pytest.mark.parametrize("reader", ["/alerts", "/dashboard/snapshot"])
def test_stale_input_closes_alert_once(configured, monkeypatch, reader):
    from backend import dashboard_api
    key, _ = configured
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    before = client.get("/dashboard/snapshot", params=key).json()
    assert any(a["active"] for a in before["alerts"])
    monkeypatch.setattr(dashboard_api.time, "time_ns", lambda: (before["emitted_at_ms"] + 3000) * 1_000_000)
    assert client.get(reader, params=key).status_code == 200
    after = client.get("/dashboard/snapshot", params=key).json()
    assert after["seq"] == before["seq"] + 1
    assert all(not a["active"] for a in after["alerts"])
    assert all(a["ended_at_ms"] == before["emitted_at_ms"] + 3000 for a in after["alerts"])
    assert client.get("/dashboard/snapshot", params=key).json() == after


def test_position_source_uses_current_camera_observations(configured):
    from backend.dashboard import build_snapshot, DashboardMap, ZoneSet
    from backend.schemas import DetectionBundleOut
    key, config = configured
    response = client.post("/detections", json=detection_payload(session_id=key["session_id"]))
    result = DetectionBundleOut.model_validate(response.json())
    assert result.matches
    def build():
        return build_snapshot(result, algorithm="f-cd", captured_at_ms=1000,
                              emitted_at_ms=1000, zones=ZoneSet.model_validate(config["zones"]),
                              stream_id="test", seq=1, map_config=DashboardMap.model_validate(config["map"]))
    assert build().objects[0].position_source == "two_camera"
    result.matches[0].camera_tracks = {"cam1": 1}
    assert build().objects[0].position_source == "single_camera"
