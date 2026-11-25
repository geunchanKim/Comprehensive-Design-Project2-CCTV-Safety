"""Failure injection must never replace complete results with a partial replay."""
import json
import logging
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cctv.db")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import api, dashboard_api
from backend.database import Base, SessionLocal, engine
from backend.main import app
from backend.models import FrameBundle
from backend.tests.test_api import detection_payload, put_camera

client = TestClient(app, raise_server_exceptions=False)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def capture(session):
    """All persisted columns, including JSON/IDs/ack state, not only row counts."""
    state = {}
    with SessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            if "session_id" in table.c:
                rows = db.execute(select(table).where(table.c.session_id == session)).mappings()
                state[table.name] = sorted(json.dumps(dict(row), sort_keys=True, default=str)
                                           for row in rows)
    return state


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setattr(api, "ENABLE_RISK_ANALYSIS", True)
    session = "atomic-" + uuid4().hex
    key = dict(session_id=session, calibration_profile="basic", algorithm="f-k")
    for camera, translation in (("cam1", [0, 0, 0]), ("cam2", [-1, 0, 0])):
        put_camera(camera, translation, session)
    config = {"map": {"coordinate_frame_id": "test", "bounds": {
        "x_min": -20, "x_max": 20, "y_min": -20, "y_max": 20}},
        "zones": {"coordinate_frame_id": "test", "zones": [
            {"zone_id": "one", "name": "test", "vertices": [[-1, -1], [15, -1], [15, 15], [-1, 15]],
             "warning_distance_m": .5}]}}
    assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201
    for pair in range(1, 6):
        body = detection_payload(pair_id=pair, session_id=session, ts2=pair * 1000 + 20)
        body["frames"][0]["ts"] = pair * 1000
        for frame in body["frames"]:
            frame["detections"][0]["vest"] = dict(
                status="not_wearing", confidence=.9, observed_at_ms=frame["ts"])
        assert client.post("/detections", json=body).status_code == 201
    url = f"/sessions/{session}/recompute?profile=basic&algorithm=f-k"
    assert client.post(url).status_code == 200
    alerts = client.get("/alerts", params=key).json()
    assert alerts
    assert client.post(f"/alerts/{alerts[0]['alert_id']}/ack", params=key,
                       json={"action": "radio"}).status_code == 204
    return session, key, url


@pytest.mark.parametrize("fail_pair", [1, 3, 5])
@pytest.mark.parametrize("failure", ["http", "integrity", "unexpected"])
def test_failed_recompute_preserves_entire_session(replay, monkeypatch, caplog, fail_pair, failure):
    session, key, url = replay
    before = capture(session)
    csv_url = f"/sessions/{session}/results.csv?profile=basic&algorithm=f-k"
    csv_before = client.get(csv_url).content
    original = dashboard_api.publish

    def fail(db, body, algorithm, result):
        original(db, body, algorithm, result)
        if body.pair_id == fail_pair:
            if failure == "http":
                raise HTTPException(503, "injected replay failure")
            if failure == "integrity":
                db.add(FrameBundle(session_id=session, calibration_profile="basic", algorithm="f-k",
                                   pair_id=body.pair_id, sync_delta_ms=0))
                db.flush()  # Real database uniqueness violation, not only an exception mock.
            raise RuntimeError("injected replay failure")

    monkeypatch.setattr(dashboard_api, "publish", fail)
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    response = client.post(url)
    assert response.status_code == {"http": 503, "integrity": 409, "unexpected": 500}[failure]
    assert capture(session) == before
    assert client.get(csv_url).content == csv_before
    assert not any(record.message.startswith(("detection_timing ", "recompute_complete "))
                   for record in caplog.records)


@pytest.mark.parametrize("failure", ["integrity", "unexpected"])
def test_final_commit_failure_restores_prior_results(replay, monkeypatch, failure):
    session, key, url = replay
    before = capture(session)

    def fail(db):
        if failure == "integrity":
            raise IntegrityError("injected commit failure", {}, Exception("conflict"))
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(Session, "commit", fail)
    response = client.post(url)
    assert response.status_code == (409 if failure == "integrity" else 500)
    assert capture(session) == before


def test_successful_recompute_commits_once_and_publishes_complete_result(replay):
    session, key, url = replay
    previous = client.get("/dashboard/snapshot", params=key).json()
    commits = []
    event.listen(Session, "after_commit", after_commit := lambda db: commits.append(True))
    try:
        response = client.post(url)
    finally:
        event.remove(Session, "after_commit", after_commit)
    assert response.status_code == 200, response.text
    assert response.json()["recomputed_bundles"] == 5
    assert len(commits) == 1
    current = client.get("/dashboard/snapshot", params=key).json()
    assert current["stream_id"] != previous["stream_id"]
    assert current["seq"] == 5
    assert current["pair_id"] == 5
    with SessionLocal() as db:
        pairs = db.scalars(select(FrameBundle.pair_id).where(
            FrameBundle.session_id == session, FrameBundle.algorithm == "f-k").order_by(FrameBundle.pair_id)).all()
    assert pairs == [1, 2, 3, 4, 5]
