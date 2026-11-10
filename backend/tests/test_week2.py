import json
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")

import pytest
import anyio
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.dashboard import RiskZone, evaluate_zone
from backend.dashboard_api import events
from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import DashboardState
from backend.tests.test_api import detection_payload, put_camera

client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def configured():
    session = "week2-" + uuid4().hex
    key = {"session_id": session, "calibration_profile": "basic", "algorithm": "baseline"}
    zones = {"coordinate_frame_id": "test-world", "zones": [
        {"zone_id": "one", "name": "test", "vertices": [[-1, -1], [11, -1], [11, 11], [-1, 11]],
         "warning_distance_m": 0.5}]}
    config = {"map": {"coordinate_frame_id": "test-world", "bounds": {
        "x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5}}, "zones": zones}
    response = client.put("/dashboard/configuration", params=key, json=config)
    assert response.status_code == 201, response.text
    put_camera("cam1", [0, 0, 0], session)
    put_camera("cam2", [-1, 0, 0], session)
    return key, config


def test_alert_ack_retention_recurrence_and_isolation(configured):
    from backend.models import DashboardAlert

    key, _ = configured
    payload = detection_payload(session_id=key["session_id"])
    assert client.post("/detections", json=payload).status_code == 201
    first = client.get("/dashboard/snapshot", params=key).json()
    alert = first["alerts"][0]
    assert alert["kind"] == "zone" and alert["level"] == "danger"
    assert alert["active"] and not alert["acknowledged"]
    assert client.post("/detections", json=payload).status_code == 409
    assert client.get("/alerts", params=key).json() == first["alerts"]
    wrong = {**key, "algorithm": "improved"}
    assert client.get("/alerts", params=wrong).json() == []
    path = f'/alerts/{alert["alert_id"]}/ack'
    assert client.post(path, params=wrong, json={"action": "radio"}).status_code == 404
    assert client.post(path, params=key, json={"action": "invalid"}).status_code == 422
    assert client.post("/alerts/missing/ack", params=key, json={"action": None}).status_code == 404
    # Empty frame resolves the occurrence, but unacknowledged danger remains visible.
    payload["pair_id"] = 2
    for frame in payload["frames"]:
        frame["frame_id"] = 2
        frame["detections"] = []
    assert client.post("/detections", json=payload).status_code == 201
    ended = client.get("/alerts", params=key).json()[0]
    assert ended["alert_id"] == alert["alert_id"] and not ended["active"]
    assert ended["ended_at_ms"] is not None
    assert client.post(path, params=key, json={"action": "dispatch"}).status_code == 204
    assert client.get("/alerts", params=key).json() == []
    with SessionLocal() as db:
        row = db.get(DashboardAlert, alert["alert_id"])
        acknowledged_at = row.acknowledged_at_ms
        assert acknowledged_at is not None and row.action == "dispatch"
    # A repeated ack from another screen is idempotent; the first action wins.
    assert client.post(path, params=key, json={"action": "radio"}).status_code == 204
    with SessionLocal() as db:
        row = db.get(DashboardAlert, alert["alert_id"])
        assert row.action == "dispatch" and row.acknowledged_at_ms == acknowledged_at
    payload = detection_payload(pair_id=3, session_id=key["session_id"])
    assert client.post("/detections", json=payload).status_code == 201
    new = client.get("/alerts", params=key).json()[0]
    assert new["alert_id"] != alert["alert_id"] and not new["acknowledged"]


def test_alert_warning_escalation_and_stream_reset(configured):
    from backend.alerts import sync_alerts
    from backend.dashboard import DashboardSnapshot
    from backend.dashboard_api import reset_stream, state_query
    from backend.schemas import RiskResult

    key, _ = configured
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    snapshot = DashboardSnapshot.model_validate(client.get("/dashboard/snapshot", params=key).json())
    snapshot.zone_evaluated = False
    snapshot.collision_evaluated = True
    snapshot.risks = [RiskResult(object1_id=20, object2_id=10, distance_m=0.8, ttc_s=None, level="warning")]

    def save(now):
        with SessionLocal() as db:
            db.scalar(state_query(tuple(key.values())).with_for_update())
            result = sync_alerts(db, tuple(key.values()), snapshot, now)
            db.commit()
            return [item.model_dump() for item in result]

    warning = next(item for item in save(100) if item["kind"] == "collision")
    assert warning["object_ids"] == [10, 20]
    path = f'/alerts/{warning["alert_id"]}/ack'
    assert client.post(path, params=key, json={"action": None}).status_code == 204
    acked = next(item for item in client.get("/alerts", params=key).json() if item["kind"] == "collision")
    assert acked["acknowledged"] and acked["action"] is None
    snapshot.risks[0].level = "danger"
    danger = next(item for item in save(200) if item["kind"] == "collision")
    assert danger["alert_id"] == warning["alert_id"]
    assert danger["started_at_ms"] == 100 and danger["last_seen_at_ms"] == 200
    assert danger["reached_danger"] and not danger["acknowledged"]
    snapshot.risks[0].level = "warning"
    assert next(item for item in save(300) if item["kind"] == "collision")["reached_danger"]
    with SessionLocal() as db:
        reset_stream(db, *key.values())
        db.commit()
    retained = next(item for item in client.get("/alerts", params=key).json() if item["kind"] == "collision")
    assert not retained["active"] and retained["ended_at_ms"] is not None
    assert retained["stream_id"] == snapshot.stream_id
    with SessionLocal() as db:
        snapshot.stream_id = db.get(DashboardState, tuple(key.values())).stream_id
    new = next(item for item in save(400) if item["kind"] == "collision" and item["active"])
    assert new["alert_id"] != warning["alert_id"] and new["stream_id"] != warning["stream_id"]
    snapshot.risks = []
    # Ended warning-only occurrences disappear; the previous unacknowledged danger remains.
    remaining = [item for item in save(500) if item["kind"] == "collision"]
    assert [item["alert_id"] for item in remaining] == [warning["alert_id"]]


def test_ack_commit_failure_preserves_unacknowledged_alert(configured, monkeypatch):
    from sqlalchemy.orm import Session

    key, _ = configured
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    alert = client.get("/alerts", params=key).json()[0]
    before = client.get("/dashboard/snapshot", params=key).json()

    def fail_commit(self):
        raise RuntimeError("simulated ack storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            response = failing_client.post(f'/alerts/{alert["alert_id"]}/ack', params=key,
                                           json={"action": "false-positive"})
            assert response.status_code == 500
    assert client.get("/alerts", params=key).json() == [alert]
    assert client.post(f'/alerts/{alert["alert_id"]}/ack', params=key,
                       json={"action": "false-positive"}).status_code == 204
    assert client.get("/alerts", params=key).json()[0]["acknowledged"]
    assert client.get("/dashboard/snapshot", params=key).json() == before


@pytest.mark.parametrize("point,status,distance", [
    ((3.5, 3.5), "intrusion", 0), ((3, 3), "intrusion", 0),
    ((2.5, 3.5), "warning", 0.5), ((2, 3.5), "outside", 1),
    ((2.7, 2.6), "warning", 0.5),
])
def test_polygon_distance(point, status, distance):
    for vertices in ([[3, 3], [4, 3], [4, 4], [3, 4]], [[3, 4], [4, 4], [4, 3], [3, 3]]):
        zone = RiskZone(zone_id="z", name="z", vertices=vertices, warning_distance_m=0.500000001)
        result = evaluate_zone(*point, zone)
        assert result.status == status
        assert result.distance_m == pytest.approx(distance)


def test_concave_and_invalid_position():
    zone = RiskZone(zone_id="z", name="z", vertices=[[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]],
                    warning_distance_m=0)
    assert evaluate_zone(1.75, 1, zone).status == "outside"
    assert evaluate_zone(0.5, 1, zone).status == "intrusion"
    assert evaluate_zone(float("nan"), 1, zone).status == "unknown"


def test_condition_and_configuration(configured, monkeypatch):
    key, config = configured
    for name in ("DASHBOARD_SESSION_ID", "DASHBOARD_CALIBRATION_PROFILE", "DASHBOARD_ALGORITHM"):
        monkeypatch.delenv(name, raising=False)
    assert client.get("/dashboard/snapshot").status_code == 503
    assert client.get("/dashboard/snapshot", params={"session_id": key["session_id"]}).status_code == 422
    assert client.get("/dashboard/snapshot", params={**key, "algorithm": "f-x"}).status_code == 422
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    assert client.put("/dashboard/configuration", params=key, json=config).status_code == 409
    for name, value in zip(("DASHBOARD_SESSION_ID", "DASHBOARD_CALIBRATION_PROFILE", "DASHBOARD_ALGORITHM"), key.values()):
        monkeypatch.setenv(name, value)
    assert client.get("/dashboard/snapshot").status_code == 204


def test_publication_duplicate_isolation_and_empty_frames(configured):
    key, _ = configured
    payload = detection_payload(session_id=key["session_id"])
    assert client.post("/detections", json=payload).status_code == 201
    first = client.get("/dashboard/snapshot", params=key).json()
    assert first["seq"] == 1 and first["zone_evaluated"] and not first["vest_evaluated"]
    assert first["objects"][0]["zone_states"][0]["status"] == "intrusion"
    assert client.get("/dashboard/snapshot", params=key).json() == first
    assert client.post("/detections", json=payload).status_code == 409
    assert client.get("/dashboard/snapshot", params=key).json() == first
    assert client.get("/dashboard/snapshot", params={**key, "algorithm": "improved"}).status_code == 204
    cameras = client.get("/dashboard/cameras", params=key).json()["cameras"]
    assert len(cameras) == 2 and all(c["online"] is None and c["frame_status"] == "recent" for c in cameras)
    assert cameras[0]["world"]["z"] == pytest.approx(0)
    assert cameras[0]["yaw_deg"] == pytest.approx(90)
    for frame in payload["frames"]:
        frame["frame_id"] = 2
        frame["detections"] = []
    payload["pair_id"] = 2
    assert client.post("/detections", json=payload).status_code == 201
    second = client.get("/dashboard/snapshot", params=key).json()
    assert second["seq"] == 2 and second["stream_id"] == first["stream_id"]
    assert second["objects"] == []
    assert client.get("/dashboard/cameras", params=key).json()["cameras"][0]["last_frame"]["detection_count"] == 0
    # A new DB session/connection reads the same stream, no in-process state needed.
    with SessionLocal() as db:
        assert db.scalar(select(DashboardState).where(DashboardState.session_id == key["session_id"])).snapshot == second


def test_zones_revision_and_invalidation(configured):
    key, config = configured
    zones = config["zones"]
    assert client.get("/dashboard/zones", params=key).headers["etag"] == '"1"'
    assert client.put("/dashboard/zones", params=key, json=zones).status_code == 428
    assert client.put("/dashboard/zones", params=key, json=zones, headers={"If-Match": '"0"'}).status_code == 412
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    zones["zones"][0]["enabled"] = False
    response = client.put("/dashboard/zones", params=key, json=zones, headers={"If-Match": '"1"'})
    assert response.status_code == 200 and response.headers["etag"] == '"2"'
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    assert client.put("/dashboard/zones", params=key, json=zones, headers={"If-Match": '"1"'}).status_code == 412
    retained = client.get("/alerts", params=key).json()
    assert len(retained) == 1 and not retained[0]["active"] and retained[0]["reached_danger"]
    zones["coordinate_frame_id"] = "wrong"
    assert client.put("/dashboard/zones", params=key, json=zones, headers={"If-Match": '"2"'}).status_code == 422
    payload = detection_payload(pair_id=2, session_id=key["session_id"])
    assert client.post("/detections", json=payload).status_code == 201
    snapshot = client.get("/dashboard/snapshot", params=key).json()
    assert snapshot["seq"] == 2 and snapshot["objects"][0]["zone_states"] == []


def test_cameras_unknown_and_stale(configured):
    key, _ = configured
    assert all(c["frame_status"] == "unknown" for c in client.get("/dashboard/cameras", params=key).json()["cameras"])
    with SessionLocal() as db:
        row = db.get(DashboardState, tuple(key.values()))
        row.observations = {"cam1": {"server_observed_at_ms": 1, "captured_at_ms": 0, "frame_id": 0, "detection_count": 0}}
        db.commit()
    assert client.get("/dashboard/cameras", params=key).json()["cameras"][0]["frame_status"] == "stale"


def test_failed_commit_does_not_publish(configured, monkeypatch):
    from sqlalchemy.orm import Session
    key, _ = configured
    payload = detection_payload(session_id=key["session_id"])
    original = Session.commit

    def fail_commit(self):
        raise RuntimeError("simulated storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            assert failing_client.post("/detections", json=payload).status_code == 500
    assert Session.commit is original
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    assert client.get("/alerts", params=key).json() == []
    assert client.post("/detections", json=payload).status_code == 201
    assert client.get("/dashboard/snapshot", params=key).json()["seq"] == 1


@pytest.mark.anyio
async def test_sse_current_snapshot(configured):
    key, _ = configured
    assert client.post("/detections", json=detection_payload(session_id=key["session_id"])).status_code == 201
    response = events(tuple(key.values()))
    iterator = response.body_iterator
    message = await anext(iterator)
    assert "event: snapshot" in message and "id: " in message
    data = json.loads(message.split("data: ", 1)[1])
    assert data == client.get("/dashboard/snapshot", params=key).json()
    await iterator.aclose()
    reconnected = events(tuple(key.values())).body_iterator
    assert await anext(reconnected) == message
    await reconnected.aclose()


@pytest.mark.anyio
async def test_sse_wait_cancels_without_new_snapshot(configured):
    key, _ = configured
    iterator = events(tuple(key.values())).body_iterator
    with anyio.move_on_after(0.1) as scope:
        await anext(iterator)
    assert scope.cancel_called
    await iterator.aclose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_heartbeat_clock_timeout_and_isolation(configured, monkeypatch):
    from backend import heartbeat as module
    from backend.models import EdgeHeartbeat

    key, _ = configured
    now = 1_000_000
    monkeypatch.setattr(module.time, "time_ns", lambda: now * 1_000_000)
    body = {"session_id": key["session_id"], "camera_id": "cam1", "edge_run_id": "run-1",
            "source": "rtsp", "last_recv_ms": 8_000, "sent_at_ms": 8_000,
            "dropped_count": 12, "max_queue_age_ms": 600}
    assert client.post("/edge/heartbeat", json=body).status_code == 204
    def cameras():
        return client.get("/dashboard/cameras", params=key).json()["cameras"]
    assert cameras()[0]["online"] is True
    assert cameras()[0]["receive_status"] == "recent"
    assert cameras()[0]["frame_status"] == "unknown"
    assert cameras()[1]["online"] is None
    now += 2000
    assert cameras()[0]["online"] is True
    assert cameras()[0]["receive_status"] == "stale"
    now += 1000
    assert cameras()[0]["online"] is False
    # Delayed/duplicate heartbeats cannot extend the same run's timeout.
    assert client.post("/edge/heartbeat", json=body).status_code == 204
    assert client.post("/edge/heartbeat", json={**body, "sent_at_ms": 7999, "last_recv_ms": 7999}).status_code == 204
    assert cameras()[0]["online"] is False
    assert client.post("/edge/heartbeat", json={**body, "edge_run_id": "run-2", "sent_at_ms": 100,
                                               "last_recv_ms": None, "source": "folder"}).status_code == 204
    assert cameras()[0]["online"] is True
    assert cameras()[0]["receive_status"] == "unknown"
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    with SessionLocal() as db:
        assert db.get(EdgeHeartbeat, (key["session_id"], "cam1")).payload["edge_run_id"] == "run-2"
    assert client.post("/edge/heartbeat", json={**body, "last_recv_ms": 8001}).status_code == 422
    assert client.post("/edge/heartbeat", json={**body, "dropped_count": -1}).status_code == 422
