import asyncio
import csv
import io
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models import Detection, FrameBundle, RiskEvent
from backend import results_export as export


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'export.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_csv_keeps_earliest_observation_order_scope_and_risks(db, monkeypatch):
    # Deliberately cross fetch boundaries and allow camera timestamps to interleave.
    monkeypatch.setattr(export, "BATCH_ROWS", 2)
    for i, profile in ((1, "basic"), (2, "basic"), (3, "precise")):
        db.execute(insert(FrameBundle), dict(id=i, session_id="s", pair_id=10 * i,
                   calibration_profile=profile, algorithm="baseline", sync_delta_ms=20))
        for camera, ts, x in (("a", 200, 9.), ("b", 100, 1.)):
            db.execute(insert(Detection), dict(bundle_id=i, session_id="s", camera_id=camera,
                       calibration_profile=profile, algorithm="baseline", frame_id=i,
                       captured_at_ms=ts + i, track_id=1, object_id=7, cls="person",
                       confidence=.9, bbox=[], foot_pixel=[], world_x=x, world_y=2., world_z=.08))
        db.execute(insert(RiskEvent), dict(bundle_id=i, session_id="s", captured_at_ms=i,
                   object1_id=7, object2_id=8, distance_m=.5, ttc_s=None, level="warning"))
    db.commit()
    # An unmatched detection must never become an exported position.
    db.execute(insert(Detection), dict(bundle_id=1, session_id="s", camera_id="c",
               calibration_profile="basic", algorithm="baseline", frame_id=1,
               captured_at_ms=1, track_id=9, object_id=None, cls="person",
               confidence=.9, bbox=[], foot_pixel=[]))
    output = io.StringIO(newline="")
    export.write_results(db, output, "s", "basic", "baseline", {"note": "한글,\"줄\n바꿈"})
    rows = list(csv.DictReader(io.StringIO(output.getvalue())))
    assert [r["record_type"] for r in rows] == ["position", "position", "risk", "risk"]
    assert [r["pair_id"] for r in rows] == ["10", "20", "10", "20"]
    assert [r["timestamp_ms"] for r in rows[:2]] == ["101", "102"]
    assert all(r["x"] == "1.0" for r in rows[:2])
    assert all(r["ttc_s"] == "" for r in rows[2:])
    assert all(json.loads(r["settings"]) == {"note": "한글,\"줄\n바꿈"} for r in rows)


def test_response_rolls_to_disk_and_closes_after_consumption(db, monkeypatch):
    monkeypatch.setattr(export, "SPOOL_BYTES", 1)
    opened = []
    original = export.SpooledTemporaryFile

    def track(**kwargs):
        file = original(**kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(export, "SpooledTemporaryFile", track)
    response = export.export_response(db, "한글", "basic", "baseline", {})
    assert opened[0]._rolled

    async def consume():
        return "".join([chunk async for chunk in response.body_iterator])

    assert asyncio.run(consume()) == ",".join(export.FIELDS) + "\r\n"
    assert opened[0].closed
    assert "filename*=UTF-8''" in response.headers["content-disposition"]


def test_query_failure_closes_temporary_file(db, monkeypatch):
    opened = []
    original = export.SpooledTemporaryFile

    def track(**kwargs):
        file = original(**kwargs)
        opened.append(file)
        return file

    def fail(*args):
        raise RuntimeError("database failure")

    monkeypatch.setattr(export, "SpooledTemporaryFile", track)
    monkeypatch.setattr(export, "write_results", fail)
    with pytest.raises(RuntimeError, match="database failure"):
        export.export_response(db, "s", "basic", "baseline", {})
    assert opened[0].closed


def test_disconnect_closes_spool():
    output = io.StringIO("a" * (export.CHUNK_CHARS + 1))
    chunks = export.file_chunks(output)
    next(chunks)
    chunks.close()
    assert output.closed


def test_background_cleanup_before_first_chunk(db):
    response = export.export_response(db, "s", "basic", "baseline", {})
    # ASGI can finish without ever starting the iterator (e.g. immediate disconnect).
    output = response.background.func.__self__
    asyncio.run(response.background())
    assert output.closed
