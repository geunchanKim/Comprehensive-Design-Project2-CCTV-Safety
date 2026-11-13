"""Synthetic SQLite query-count benchmark; never connects to the application DB.

python -m backend.tools.benchmark_track_queries --output result.json
"""
from contextlib import ExitStack
import argparse
import json
import os
import platform
import statistics
import tempfile
import time
from math import pi
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--iterations", type=int, default=12)
    args = parser.parse_args()
    if args.iterations < 2:
        parser.error("iterations must be >= 2")
    with tempfile.TemporaryDirectory(prefix="cctv-query-") as folder, ExitStack() as cleanup:
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(folder) / "benchmark.db")
        from fastapi.testclient import TestClient
        from sqlalchemy import event
        from backend.database import Base, engine
        from backend.main import app
        cleanup.callback(engine.dispose)
        Base.metadata.create_all(engine)
        rows = []
        signatures = {}
        with TestClient(app) as client:
            for count in (1, 5, 10, 20):
                session = f"synthetic-{count}"
                for cam, tx in (("cam1", 0), ("cam2", -1)):
                    response = client.put(f"/cameras/{cam}/calibration", json={
                        "session_id": session, "method": "unity-gt", "image_size": [1920, 1080],
                        "K": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
                        "dist": [0] * 5, "rvec": [pi / 2, 0, 0], "tvec": [tx, 0, 0],
                        "reproj_error_px": 0})
                    response.raise_for_status()
                for pair in range(1, args.iterations + 3):
                    sql = []
                    def capture(conn, cursor, statement, params, context, executemany):
                        sql.append(statement)
                    payload = {"session_id": session, "pair_id": pair, "frames": [
                        {"camera_id": cam, "frame_id": pair, "ts": pair * 1000,
                         "image_size": [1920, 1080], "detections": [
                             {"track_id": i + 1, "cls": "chair", "conf": 0.9,
                              "bbox": [950 - i * 25 + dx, 400, 970 - i * 25 + dx, 540]}
                             for i in range(count)]}
                        for cam, dx in (("cam1", 0), ("cam2", -100))]}
                    event.listen(engine, "before_cursor_execute", capture)
                    try:
                        started = time.perf_counter()
                        response = client.post("/detections", json=payload)
                        elapsed = (time.perf_counter() - started) * 1000
                    finally:
                        event.remove(engine, "before_cursor_execute", capture)
                    response.raise_for_status()
                    result = response.json()
                    assert len(result["matches"]) == count, result
                    signature = {k: result[k] for k in ("matches", "unmatched", "risks", "settings")}
                    # Keep every frame for exact cross-version comparison.
                    signatures.setdefault(str(count), []).append(signature)
                    if pair > 2:
                        rows.append({"objects": count, "pair": pair, "sql": len(sql),
                                     "selects": sum(q.lstrip().upper().startswith("SELECT") for q in sql),
                                     "track_link_selects": sum(q.lstrip().upper().startswith("SELECT")
                                                               and "FROM track_links" in q for q in sql),
                                     "request_ms": elapsed})
        summary = []
        for count in (1, 5, 10, 20):
            samples = [r for r in rows if r["objects"] == count]
            times = sorted(r["request_ms"] for r in samples)
            summary.append({"objects": count,
                            "sql_mean": statistics.mean(r["sql"] for r in samples),
                            "selects_mean": statistics.mean(r["selects"] for r in samples),
                            "track_link_selects_mean": statistics.mean(r["track_link_selects"] for r in samples),
                            "request_ms_median": statistics.median(times),
                            "request_ms_p95": times[min(len(times) - 1, int(len(times) * .95))]})
        output = {"environment": {"database": "temporary SQLite", "python": platform.python_version(),
                                  "platform": platform.platform(), "algorithm": "baseline",
                                  "class": "chair", "concurrency": 1, "warmup_pairs": 2},
                  "summary": summary, "samples": rows, "signatures": signatures}
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        engine.dispose()


if __name__ == "__main__":
    main()
