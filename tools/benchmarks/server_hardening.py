"""Compare original/current APIs in isolated SQLite databases, never operational DBs.

python tools/benchmarks/server_hardening.py
"""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "957d47f"


def worker(source, output_path):
    sys.path.insert(0, str(source))
    with tempfile.TemporaryDirectory() as temp:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(temp) / 'cases.db'}"
        from fastapi.testclient import TestClient
        from sqlalchemy import event
        from backend.main import app
        from backend.database import Base, engine, SessionLocal
        from backend.models import Camera
        from backend.schemas import DetectionBundleIn
        from backend.api import _create_detections
        from backend import dashboard_api

        Base.metadata.create_all(engine)
        client = TestClient(app, raise_server_exceptions=False)
        data = {"database": "isolated temporary SQLite", "risk_queries": [], "calibration": []}

        def camera(session, camera_id):
            return dict(session_id=session, method="unity-gt", image_size=[1920, 1080],
                        K=[[1000, 0, 960], [0, 1000, 540], [0, 0, 1]], dist=[0] * 5,
                        rvec=[1.5707963267948966, 0, 0],
                        tvec=[0 if camera_id == "cam1" else -1, 2, 0], reproj_error_px=0)

        def prepare(session):
            for camera_id in ("cam1", "cam2"):
                assert client.put(f"/cameras/{camera_id}/calibration", json=camera(session, camera_id)).status_code == 200

        def bundle(session, count, pair, shift=0):
            frames = []
            for camera_id in ("cam1", "cam2"):
                detections = []
                for i in range(count):
                    u = 960 + 100 * (i * .3 + shift + (0 if camera_id == "cam1" else -1))
                    detections.append(dict(track_id=i + 1, cls="person", conf=.9,
                                           bbox=[u - 8, 600, u + 8, 740]))
                frames.append(dict(camera_id=camera_id, frame_id=pair, ts=pair * 1000,
                                   image_size=[1920, 1080], detections=detections))
            return dict(session_id=session, pair_id=pair, frames=frames)

        for count in (5, 10, 20):
            session = f"risk-{count}"
            prepare(session)
            for pair in (1, 2):
                sql = []
                def observe(conn, cursor, statement, parameters, context, executemany):
                    if statement.lstrip().upper().startswith("SELECT"):
                        sql.append(statement)
                event.listen(engine, "before_cursor_execute", observe)
                try:
                    with SessionLocal() as db:
                        result = _create_detections(DetectionBundleIn.model_validate(bundle(session, count, pair)),
                                                    db, algorithm="f-cdfg")
                finally:
                    event.remove(engine, "before_cursor_execute", observe)
                canonical = json.dumps({name: result[name] for name in ("matches", "risks")}, sort_keys=True)
                data["risk_queries"].append(dict(people=count, pair=pair, matches=len(result["matches"]),
                    risk_pairs=len(result["risks"]), state_selects=sum("FROM risk_pair_states" in s for s in sql),
                    result_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                    risk_ms=result["timings_ms"]["risk_ms"]))

        for case in ("zero_fx", "zero_fy"):
            session = "calibration-" + case
            prepare(session)
            before = client.post("/detections", json=bundle(session, 1, 1))
            body = camera(session, "cam1")
            body["K"][0 if case == "zero_fx" else 1][0 if case == "zero_fx" else 1] = 0
            response = client.put("/cameras/cam1/calibration", json=body)
            after = client.post("/detections", json=bundle(session, 1, 2))
            with SessionLocal() as db:
                preserved = db.get(Camera, (session, "cam1", "basic")).intrinsic_matrix == camera(session, "cam1")["K"]
            data["calibration"].append(dict(case=case, update_status=response.status_code,
                camera_preserved=preserved, matches_before=len(before.json()["matches"]),
                matches_after=len(after.json()["matches"])))

        session = "late"
        prepare(session)
        key = dict(session_id=session, calibration_profile="basic", algorithm="baseline")
        config = {"map": {"coordinate_frame_id": "test", "bounds": {
            "x_min": -5, "x_max": 5, "y_min": 0, "y_max": 15}},
            "zones": {"coordinate_frame_id": "test", "zones": [
                {"zone_id": "one", "name": "test", "vertices": [[-1, 9], [1, 9], [1, 11], [-1, 11]],
                 "warning_distance_m": 0}]}}
        assert client.put("/dashboard/configuration", params=key, json=config).status_code == 201
        assert client.post("/detections", json=bundle(session, 1, 2)).status_code == 201
        before = client.get("/dashboard/snapshot", params=key).json()
        assert client.post("/detections", json=bundle(session, 1, 1, shift=2)).status_code == 201
        after = client.get("/dashboard/snapshot", params=key).json()
        alerts = client.get("/alerts", params=key).json()
        data["late_input"] = dict(capture_before=before["captured_at_ms"], capture_after=after["captured_at_ms"],
                                  seq_before=before["seq"], seq_after=after["seq"],
                                  alert_active_before=before["alerts"][0]["active"], alert_active_after=alerts[0]["active"])

        polls = []
        original = dashboard_api.run_in_threadpool
        async def observe_poll(func, *args):
            result = await original(func, *args)
            polls.append(result)
            return result
        dashboard_api.run_in_threadpool = observe_poll
        async def idle():
            iterator = dashboard_api.events(tuple(key.values())).body_iterator
            await anext(iterator)
            try:
                await asyncio.wait_for(anext(iterator), timeout=1.1)
            except asyncio.TimeoutError:
                pass
            finally:
                await iterator.aclose()
        asyncio.run(idle())
        dashboard_api.run_in_threadpool = original
        data["idle_sse"] = dict(observation_seconds=1.1, polls=len(polls),
                                full_payloads_returned=sum(item is not None for item in polls))
        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        engine.dispose()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        archive = subprocess.check_output(["git", "archive", BASELINE, "backend"], cwd=ROOT)
        baseline = directory / "baseline"
        baseline.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            files.extractall(baseline, filter="data")
        results = {"baseline": BASELINE, "timing_note": "single local samples, not a speed benchmark"}
        for name, source in (("before", baseline), ("after", ROOT)):
            path = directory / f"{name}.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(source), str(path)], check=True)
            results[name] = json.loads(path.read_text())
        for before, after in zip(results["before"]["risk_queries"], results["after"]["risk_queries"]):
            assert before["result_sha256"] == after["result_sha256"]
        path = ROOT / "output/benchmarks/server-hardening.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
