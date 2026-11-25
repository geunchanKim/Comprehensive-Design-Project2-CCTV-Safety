import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import ppe
from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import GlobalObject
from backend.schemas import DetectionBundleIn, PPEObservation
from backend.tests.test_api import detection_payload, put_camera

client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def defaults(monkeypatch):
    monkeypatch.setattr(ppe, "PPE_CONFIRM_SAMPLES", 3)
    monkeypatch.setattr(ppe, "PPE_MAX_AGE_MS", 3000)
    monkeypatch.setattr(ppe, "PPE_MIN_CONFIDENCE", 0.4)


def sample(ts, status="wearing", confidence=0.9):
    return PPEObservation(status=status, confidence=confidence, observed_at_ms=ts)


def confirmed():
    state = None
    for ts in (1000, 1100, 1200):
        state, out = ppe.advance(state, [sample(ts)], ts)
    assert out.status == "wearing"
    return state


def test_streak_does_not_count_two_cameras_or_repeated_cached_samples():
    state, out = ppe.advance(None, [sample(1000), sample(1020)], 1020)
    assert out.status == "unknown" and state["count"] == 1
    for ts in (1100, 1200, 1300):
        state, out = ppe.advance(state, [sample(1000), sample(1020)], ts)
    assert state["count"] == 1 and out.status == "unknown"


@pytest.mark.parametrize("observations", [
    [sample(1300, "not_wearing")],
    [sample(1300, "unknown", None)],
    [sample(1300, confidence=0.39)],
    [sample(1300), sample(1320, "not_wearing")],
])
def test_ambiguous_or_changed_observation_is_unknown(observations):
    state, out = ppe.advance(confirmed(), observations, 1320)
    assert out.status == "unknown" and out.confidence is None
    for ts in (1400, 1500):
        state, out = ppe.advance(state, [sample(ts, "not_wearing")], ts)
    # Only the contradictory known sample started a new streak above.
    if len(observations) == 1 and observations[0].status == "not_wearing":
        assert out.status == "not_wearing"
    else:
        assert out.status == "unknown"


def test_one_second_edge_cadence_and_exact_expiry_boundary():
    state = None
    for ts in (1000, 2000, 3000):
        state, out = ppe.advance(state, [sample(ts)], ts)
        assert out.status == ("wearing" if ts == 3000 else "unknown")
    # Reusing the original inference timestamp must not extend its lifetime.
    state, out = ppe.advance(state, [sample(3000)], 6000)
    assert out.status == "wearing" and out.observed_at_ms == 3000
    state, out = ppe.advance(state, [], 6001)
    assert out.status == "unknown"
    state, out = ppe.advance(state, [sample(7000)], 7000)
    assert out.status == "unknown" and state["count"] == 1


def test_skips_expiry_gap_and_old_samples():
    state = confirmed()
    kept, out = ppe.advance(state, [], 2000)
    assert out.status == "wearing"
    expired, out = ppe.advance(kept, [], 4201)
    assert out.status == "unknown"
    late, out = ppe.advance(expired, [sample(1300)], 1300)
    assert late == expired and out.status == "unknown"
    fresh, out = ppe.advance(expired, [sample(4300)], 4300)
    assert out.status == "unknown" and fresh["count"] == 1
    old, out = ppe.advance(state, [sample(900, "not_wearing")], 1100)
    assert old == state and out.status == "unknown"


@pytest.mark.parametrize("change", ["future", "nonperson", "nan", "no_confidence", "no_time"])
def test_invalid_ppe_payload_is_rejected(change):
    payload = detection_payload()
    detection = payload["frames"][0]["detections"][0]
    detection["vest"] = sample(1000).model_dump()
    if change == "future":
        detection["vest"]["observed_at_ms"] = 1001
    elif change == "nonperson":
        detection["cls"] = "chair"
    elif change == "nan":
        detection["vest"]["confidence"] = float("nan")
    elif change == "no_confidence":
        detection["vest"]["confidence"] = None
    else:
        del detection["vest"]["observed_at_ms"]
    with pytest.raises(ValidationError):
        DetectionBundleIn.model_validate(payload)


def test_ingest_persistence_snapshot_duplicate_rollback_and_expiry(monkeypatch):
    session = "ppe-" + uuid4().hex
    key = {"session_id": session, "calibration_profile": "basic", "algorithm": "baseline"}
    put_camera("cam1", [0, 0, 0], session)
    put_camera("cam2", [-1, 0, 0], session)
    configuration = {"map": {"coordinate_frame_id": "ppe", "bounds": {
        "x_min": -5, "x_max": 5, "y_min": -5, "y_max": 15}},
        "zones": {"coordinate_frame_id": "ppe", "zones": []}}
    assert client.put("/dashboard/configuration", params=key, json=configuration).status_code == 201

    def send(pair, ts, *, include=True):
        payload = detection_payload(pair_id=pair, session_id=session, ts2=ts)
        for frame in payload["frames"]:
            frame["ts"] = ts
            if include:
                frame["detections"][0].update(vest=sample(ts).model_dump(),
                                              helmet=sample(ts, "not_wearing").model_dump())
        return client.post("/detections", json=payload)

    assert send(1, 1000).status_code == 201
    assert send(2, 1100).status_code == 201
    assert send(2, 1100).status_code == 409
    snap = client.get("/dashboard/snapshot", params=key).json()
    assert snap["objects"][0]["vest"]["status"] == "unknown"
    # Snapshot failure must roll back the vote along with the detection.
    from backend import dashboard_api
    def fail(*args):
        raise RuntimeError("publication failed")
    with monkeypatch.context() as patch:
        patch.setattr(dashboard_api, "publish", fail)
        with pytest.raises(RuntimeError, match="publication failed"):
            send(3, 1200)
    result = send(3, 1200)
    assert result.status_code == 201, result.text
    obj = result.json()["matches"][0]
    assert obj["vest"]["status"] == "wearing" and obj["helmet"]["status"] == "not_wearing"
    with SessionLocal() as db:
        stored = db.get(GlobalObject, obj["object_id"])
        assert stored.ppe_state["vest"]["count"] == 3
    snap = client.get("/dashboard/snapshot", params=key).json()
    assert snap["vest_evaluated"] and snap["helmet_evaluated"]
    assert snap["objects"][0]["helmet"] == obj["helmet"]
    # Raw samples survive storage and recompute; target state is rebuilt, not inherited.
    from sqlalchemy import select
    for _ in range(2):
        response = client.post(f"/sessions/{session}/recompute", params={"profile": "basic", "algorithm": "f-k"})
        assert response.status_code == 200, response.text
        with SessionLocal() as db:
            rows = db.scalars(select(GlobalObject).where(GlobalObject.session_id == session,
                                                        GlobalObject.algorithm == "f-k")).all()
            assert len(rows) == 1 and rows[0].id != obj["object_id"]
            assert rows[0].ppe_state["vest"]["status"] == "wearing"
            assert rows[0].ppe_state["vest"]["count"] == 3
    alerts = client.get("/alerts", params=key).json()
    assert len(alerts) == 1 and alerts[0]["kind"] == "helmet"
    assert alerts[0]["object_ids"] == [obj["object_id"]]
    assert alerts[0]["level"] == "warning"
    assert send(4, 1300, include=False).json()["matches"][0]["vest"]["status"] == "wearing"
    assert send(5, 4301, include=False).json()["matches"][0]["vest"]["status"] == "unknown"
    assert client.get("/alerts", params=key).json() == []
    assert client.get("/health").json()["ppe"] == ppe.settings()


@pytest.mark.parametrize("item", ["vest", "helmet"])
def test_ppe_alert_lifecycle_rollback_and_condition_isolation(item):
    from sqlalchemy import select
    from backend.alerts import sync_alerts
    from backend.dashboard import DashboardSnapshot
    from backend.dashboard_api import state_query
    from backend.models import DashboardAlert
    from backend.schemas import PPEState

    session = "ppe-alert-" + uuid4().hex
    key = {"session_id": session, "calibration_profile": "basic", "algorithm": "baseline"}
    config = {"map": {"coordinate_frame_id": "ppe", "bounds": {
        "x_min": -5, "x_max": 5, "y_min": -5, "y_max": 15}},
        "zones": {"coordinate_frame_id": "ppe", "zones": []}}
    assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201
    put_camera("cam1", [0, 0, 0], session)
    put_camera("cam2", [-1, 0, 0], session)
    assert client.post("/detections", json=detection_payload(session_id=session)).status_code == 201
    snapshot = DashboardSnapshot.model_validate(client.get("/dashboard/snapshot", params=key).json())
    snapshot.collision_evaluated = False
    snapshot.zone_evaluated = False
    person = snapshot.objects[0]

    def save(status, now, commit=True):
        setattr(person, item, PPEState(status=status, confidence=0.9 if status != "unknown" else None,
                                      observed_at_ms=now))
        with SessionLocal() as db:
            db.scalar(state_query(tuple(key.values())).with_for_update())
            rows = sync_alerts(db, tuple(key.values()), snapshot, now)
            if commit:
                db.commit()
            else:
                db.rollback()
            return [row.model_dump() for row in rows]

    assert save("unknown", 1000) == []
    assert save("wearing", 1100) == []
    save("not_wearing", 1200, commit=False)
    assert client.get("/alerts", params=key).json() == []
    first, = save("not_wearing", 1300)
    assert first["kind"] == item and first["object_ids"] == [person.object_id]
    assert first["level"] == "warning" and not first["reached_danger"]
    assert first["distance_m"] is None and first["zone_id"] is None
    assert client.get("/alerts", params={**key, "algorithm": "improved"}).json() == []
    path = f'/alerts/{first["alert_id"]}/ack'
    assert client.post(path, params=key, json={"action": "radio"}).status_code == 204
    same, = save("not_wearing", 1400)
    assert same["alert_id"] == first["alert_id"] and same["acknowledged"]
    assert same["action"] == "radio" and same["last_seen_at_ms"] == 1400
    assert save("unknown", 1500) == []  # No longer confirmed; not a safe judgment.
    with SessionLocal() as db:
        ended = db.scalar(select(DashboardAlert).where(DashboardAlert.alert_id == first["alert_id"]))
        assert ended.active_key is None and ended.ended_at_ms == 1500
    again, = save("not_wearing", 1600)
    assert again["alert_id"] != first["alert_id"] and not again["acknowledged"]
    other = "helmet" if item == "vest" else "vest"
    setattr(person, other, PPEState(status="not_wearing", confidence=0.9, observed_at_ms=1650))
    both = save("not_wearing", 1650)
    assert {row["kind"] for row in both} == {"vest", "helmet"}
    assert len({row["alert_id"] for row in both}) == 2
    snapshot.objects = []
    assert len(save("not_wearing", 1700)) == 2  # Brief disappearance preserves IDs.
    assert save("not_wearing", 2651) == []  # Grace expires without another observation.
