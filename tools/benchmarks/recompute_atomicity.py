"""Reproduce old/new replay failures only in an isolated temporary SQLite DB."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASELINE = "957d47f"


def main():
    # Override even an inherited operational DATABASE_URL before importing backend.
    with tempfile.TemporaryDirectory() as temp:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(temp) / 'replay.db'}"
        from fastapi import HTTPException
        from sqlalchemy import event, select
        from sqlalchemy.orm import Session
        from pytest import MonkeyPatch
        from backend import api, dashboard_api
        from backend.database import Base, SessionLocal, engine
        from backend.models import FrameBundle
        from backend.tests.test_recompute_atomicity import capture, client, replay

        source = subprocess.check_output(["git", "show", f"{BASELINE}:backend/api.py"], cwd=ROOT).decode()
        namespace = {"__name__": "backend._baseline_replay", "__package__": "backend"}
        exec(compile(source, "baseline_api.py", "exec"), namespace)
        # Match the fixture's synthetic risk-enabled settings in both modules.
        namespace["ENABLE_RISK_ANALYSIS"] = True
        Base.metadata.create_all(engine)
        results = {"baseline": BASELINE, "database": "isolated temporary SQLite",
                   "method": "5 source/target pairs, publish then inject failure; all session columns compared",
                   "runs": []}
        original = dashboard_api.publish
        for mode, recompute in (("before", namespace["recompute_session"]), ("after", api.recompute_session)):
            for failure in ("http", "integrity", "unexpected", "none"):
                for fail_pair in ((1, 3, 5) if failure != "none" else (None,)):
                    with MonkeyPatch.context() as patch:
                        session, key, _ = replay.__wrapped__(patch)
                        before = capture(session)
                        csv_url = f"/sessions/{session}/results.csv?profile=basic&algorithm=f-k"
                        csv_before = client.get(csv_url).content

                        def fail(db, body, algorithm, result):
                            original(db, body, algorithm, result)
                            if body.pair_id == fail_pair:
                                if failure == "http":
                                    raise HTTPException(503, "injected replay failure")
                                if failure == "integrity":
                                    db.add(FrameBundle(session_id=session, calibration_profile="basic",
                                                       algorithm="f-k", pair_id=body.pair_id, sync_delta_ms=0))
                                    db.flush()
                                raise RuntimeError("injected replay failure")

                        patch.setattr(dashboard_api, "publish", fail)
                        commits = []
                        def committed(db):
                            commits.append(True)
                        event.listen(Session, "after_commit", committed)
                        status = 200
                        try:
                            with SessionLocal() as db:
                                recompute(session, "basic", "f-k", db)
                        except HTTPException as exc:
                            status = exc.status_code
                        except RuntimeError:
                            status = 500
                        finally:
                            event.remove(Session, "after_commit", committed)
                        after = capture(session)
                        csv_after = client.get(csv_url).content
                        with SessionLocal() as db:
                            pairs = list(db.scalars(select(FrameBundle.pair_id).where(
                                FrameBundle.session_id == session,
                                FrameBundle.algorithm == "f-k").order_by(FrameBundle.pair_id)))
                        row = dict(mode=mode, failure=failure, fail_pair=fail_pair, http_status=status,
                                   complete_session_preserved=before == after,
                                   changed_tables=[name for name in before if before[name] != after[name]],
                                   csv_before_sha256=hashlib.sha256(csv_before).hexdigest(),
                                   csv_after_sha256=hashlib.sha256(csv_after).hexdigest(),
                                   target_pairs_after=pairs, successful_commits=len(commits))
                        results["runs"].append(row)
                        expected = {"http": 503, "integrity": 409, "unexpected": 500, "none": 200}[failure]
                        assert status == expected, row
                        if mode == "after" and failure != "none":
                            assert row["complete_session_preserved"], row
                        print(json.dumps(row), flush=True)
        engine.dispose()
    path = ROOT / "output/benchmarks/recompute-atomicity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
