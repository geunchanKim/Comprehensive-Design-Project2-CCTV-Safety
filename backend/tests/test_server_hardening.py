import asyncio
import copy
import json
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from backend import dashboard_api
from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import Camera, DashboardState, FrameBundle, RiskPairState
from backend.api import _load_risk_states, _risk_level_with_hysteresis
from backend.tests.test_api import K, detection_payload, put_camera

client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def scene():
    session = "hardening-" + uuid4().hex
    key = dict(session_id=session, calibration_profile="basic", algorithm="baseline")
    put_camera("cam1", [0, 0, 0], session)
    put_camera("cam2", [-1, 0, 0], session)
    config = {"map": {"coordinate_frame_id": "test", "bounds": {
        "x_min": -5, "x_max": 5, "y_min": 0, "y_max": 15}},
        "zones": {"coordinate_frame_id": "test", "zones": [
            {"zone_id": "one", "name": "test", "vertices": [[-1, 9], [1, 9], [1, 11], [-1, 11]],
             "warning_distance_m": 0}]}}
    assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201
    return session, key


def calibration(session):
    return dict(session_id=session, method="unity-gt", image_size=[1920, 1080], K=copy.deepcopy(K),
                dist=[0] * 5, rvec=[1.5707963267948966, 0, 0], tvec=[0, 0, 0], reproj_error_px=0)


@pytest.mark.parametrize("case", ["zero_fx", "zero_fy", "negative_fx", "bad_bottom", "nan_K", "inf_tvec"])
def test_invalid_calibration_cannot_replace_working_camera(scene, case):
    session, _ = scene
    body = calibration(session)
    if case == "zero_fx": body["K"][0][0] = 0
    if case == "zero_fy": body["K"][1][1] = 0
    if case == "negative_fx": body["K"][0][0] = -1
    if case == "bad_bottom": body["K"][2][2] = 0
    if case == "nan_K": body["K"][0][0] = float("nan")
    if case == "inf_tvec": body["tvec"][0] = float("inf")
    response = client.put("/cameras/cam1/calibration", content=json.dumps(body),
                          headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.get(Camera, (session, "cam1", "basic")).intrinsic_matrix == K
    detection = client.post("/detections", json=detection_payload(session_id=session))
    assert detection.status_code == 201
    assert len(detection.json()["matches"]) == 1


def test_pnp_rejects_bad_intrinsics_before_solving(scene):
    session, _ = scene
    points = [{"image": [i * 10, 100], "world": [i, 0, 0]} for i in range(6)]
    body = dict(session_id=session, image_size=[1920, 1080], K=[[0] * 3 for _ in range(3)],
                dist=[0] * 5, grid_points=points,
                validation_points=[{"image": [20, 20], "world": [1, 1, 1]},
                                   {"image": [30, 20], "world": [2, 1, 1]}])
    assert client.post("/cameras/cam1/calibration/solve-pnp", json=body).status_code == 422


def test_late_frame_preserves_map_alerts_and_observation_after_zone_edit(scene):
    session, key = scene
    fresh = detection_payload(pair_id=2, session_id=session, ts2=2020)
    fresh["frames"][0]["ts"] = 2000
    assert client.post("/detections", json=fresh).status_code == 201
    before = client.get("/dashboard/snapshot", params=key).json()
    alert = before["alerts"][0]
    assert alert["active"]
    assert client.post(f"/alerts/{alert['alert_id']}/ack", params=key, json={"action": "radio"}).status_code == 204
    with SessionLocal() as db:
        observed = copy.deepcopy(db.get(DashboardState, tuple(key.values())).observations)
    late = detection_payload(pair_id=1, session_id=session)
    for frame in late["frames"]:
        box = frame["detections"][0]["bbox"]
        frame["detections"][0]["bbox"] = [box[0] + 200, box[1], box[2] + 200, box[3]]
    assert client.post("/detections", json=late).status_code == 201
    assert client.get("/dashboard/snapshot", params=key).json() == before
    current_alert = client.get("/alerts", params=key).json()[0]
    assert current_alert["active"] and current_alert["acknowledged"]
    zones = client.get("/dashboard/zones", params=key)
    assert client.put("/dashboard/zones", params=key, headers={"If-Match": zones.headers["etag"]},
                      json=zones.json()).status_code == 200
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    late["pair_id"] = 0
    for frame in late["frames"]: frame["frame_id"] = 0
    assert client.post("/detections", json=late).status_code == 201
    assert client.get("/dashboard/snapshot", params=key).status_code == 204
    with SessionLocal() as db:
        assert db.get(DashboardState, tuple(key.values())).observations == observed
        assert len(list(db.scalars(select(FrameBundle).where(FrameBundle.session_id == session)))) == 3
    fresh["pair_id"] = 3
    for frame in fresh["frames"]:
        frame["frame_id"] = 3
        frame["ts"] += 1000
    assert client.post("/detections", json=fresh).status_code == 201
    assert client.get("/dashboard/snapshot", params=key).json()["pair_id"] == 3


def test_risk_batch_lookup_chunking_scope_and_release_rules():
    # Query parameter chunking, condition isolation and hysteresis boundaries.
    session = "risk-" + uuid4().hex
    with SessionLocal() as db:
        # Use real foreign-key objects on PostgreSQL as well as SQLite.
        from backend.models import GlobalObject
        people = [GlobalObject(session_id=session, calibration_profile="basic", algorithm="f-f", cls="person")
                  for _ in range(402)]
        db.add_all(people)
        db.flush()
        ids = sorted(obj.id for obj in people)
        row = RiskPairState(session_id=session, calibration_profile="basic", algorithm="f-f",
                           object1_id=ids[0], object2_id=ids[-1], level="warning")
        other = RiskPairState(session_id=session, calibration_profile="precise", algorithm="f-f",
                             object1_id=ids[0], object2_id=ids[-1], level="danger")
        db.add_all([row, other])
        db.flush()
        states = _load_risk_states(db, session, "basic", "f-f", ids)
        assert list(states) == [(ids[0], ids[-1])]
        assert _risk_level_with_hysteresis(db, session, "basic", "f-f", ids[0], ids[-1], 1.05, states=states) == "warning"
        assert _risk_level_with_hysteresis(db, session, "basic", "f-f", ids[0], ids[-1], 1.11, states=states) == "safe"
        assert other.level == "danger"


def test_idle_sse_returns_no_unchanged_payload_and_reconnects(scene, monkeypatch):
    session, key = scene
    assert client.post("/detections", json=detection_payload(session_id=session)).status_code == 201
    snapshots = []
    original = dashboard_api.run_in_threadpool
    async def observe(func, *args):
        result = await original(func, *args)
        snapshots.append(result)
        return result
    monkeypatch.setattr(dashboard_api, "run_in_threadpool", observe)
    async def check():
        iterator = dashboard_api.events(tuple(key.values())).body_iterator
        first = await anext(iterator)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(iterator), timeout=.6)
        await iterator.aclose()
        assert len(snapshots) >= 2
        assert snapshots[0] is not None and all(item is None for item in snapshots[1:])
        reconnected = dashboard_api.events(tuple(key.values())).body_iterator
        assert await anext(reconnected) == first
        await reconnected.aclose()
    asyncio.run(check())


def test_sse_delivers_new_stream_even_when_sequence_repeats(scene):
    session, key = scene
    assert client.post("/detections", json=detection_payload(session_id=session)).status_code == 201
    async def check():
        iterator = dashboard_api.events(tuple(key.values())).body_iterator
        first = json.loads((await anext(iterator)).split("data: ", 1)[1])
        with SessionLocal() as db:
            dashboard_api.reset_stream(db, session, "basic", "baseline")
            db.commit()
        payload = detection_payload(pair_id=2, session_id=session, ts2=2020)
        payload["frames"][0]["ts"] = 2000
        assert client.post("/detections", json=payload).status_code == 201
        second = json.loads((await asyncio.wait_for(anext(iterator), timeout=2)).split("data: ", 1)[1])
        assert first["seq"] == second["seq"] == 1
        assert first["stream_id"] != second["stream_id"]
        await iterator.aclose()
    asyncio.run(check())
