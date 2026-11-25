"""Local synthetic CSV benchmark. Never connects to an operational database.

python tools/benchmarks/results_export.py --pairs 10000 50000 --repeats 3
"""
import argparse
import ast
import csv
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.responses import Response
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models import Detection, FrameBundle, RiskEvent, SessionSettings
from backend.results_export import file_chunks, write_results, SPOOL_BYTES
from tempfile import SpooledTemporaryFile

BASELINE = "c51d7a2"


def old_export():
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:backend/api.py"], cwd=ROOT).decode("utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "download_session_results")
    node.decorator_list = []
    for arg in node.args.args:
        arg.annotation = None
    node.args.defaults = []
    namespace = dict(csv=csv, io=io, json=json, select=select, Response=Response,
                     SessionSettings=SessionSettings, Detection=Detection,
                     FrameBundle=FrameBundle, RiskEvent=RiskEvent,
                     _checked_algorithm=lambda value: value)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "baseline", "exec"), namespace)
    return namespace["download_session_results"]


def seed(engine, count):
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(SessionSettings), dict(session_id="bench", calibration_profile="basic",
                     algorithm="baseline", settings={"risk_analysis": True, "features": []}))
        for start in range(1, count + 1, 500):
            ids = range(start, min(count + 1, start + 500))
            conn.execute(insert(FrameBundle), [dict(id=i, session_id="bench", pair_id=i,
                         calibration_profile="basic", algorithm="baseline", sync_delta_ms=20) for i in ids])
            conn.execute(insert(Detection), [dict(
                bundle_id=i, session_id="bench", camera_id=cam, calibration_profile="basic",
                algorithm="baseline", frame_id=i, captured_at_ms=i * 50 + offset,
                track_id=7, object_id=1, cls="person", confidence=.9,
                bbox=[950, 400, 970, 540], foot_pixel=[960, 540],
                world_x=1.25, world_y=2.5, world_z=.08,
            ) for i in ids for cam, offset in (("cam1", 0), ("cam2", 20))])
            conn.execute(insert(RiskEvent), [dict(bundle_id=i, session_id="bench",
                         captured_at_ms=i * 50, object1_id=1, object2_id=2,
                         distance_m=.75, ttc_s=None, level="warning") for i in ids])


def measure(engine, old, mode):
    gc.collect()
    digest = hashlib.sha256()
    size = 0
    tracemalloc.start()
    started = time.perf_counter()
    with Session(engine) as db:
        if mode == "before":
            response = old("bench", "basic", "baseline", db)
            digest.update(response.body)
            size = len(response.body)
        else:
            settings = db.get(SessionSettings, ("bench", "basic", "baseline")).settings
            with SpooledTemporaryFile(max_size=SPOOL_BYTES, mode="w+", encoding="utf-8", newline="") as output:
                write_results(db, output, "bench", "basic", "baseline", settings)
                output.seek(0)
                for chunk in file_chunks(output):
                    encoded = chunk.encode("utf-8")
                    digest.update(encoded)
                    size += len(encoded)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(seconds=elapsed, peak_python_mib=peak / 1024**2, bytes=size, sha256=digest.hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, nargs="+", default=[10000, 50000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    old = old_export()
    results = dict(baseline=BASELINE, python=sys.version, database="SQLite, local temporary file",
                   metric="tracemalloc Python allocations; excludes DB/native memory; no HTTP/network",
                   scenarios=[])
    with tempfile.TemporaryDirectory() as temp:
        for count in args.pairs:
            engine = create_engine(f"sqlite:///{Path(temp) / str(count)}.db")
            seed(engine, count)
            # Warm both paths; alternate order to reduce one-sided cache effects.
            for mode in ("before", "after"):
                measure(engine, old, mode)
            runs = {mode: [] for mode in ("before", "after")}
            for repeat in range(args.repeats):
                for mode in (("before", "after") if repeat % 2 == 0 else ("after", "before")):
                    runs[mode].append(measure(engine, old, mode))
            assert len({r["sha256"] for rows in runs.values() for r in rows}) == 1
            summary = {mode: {key: statistics.median(row[key] for row in rows)
                              for key in ("seconds", "peak_python_mib")}
                       for mode, rows in runs.items()}
            scenario = dict(pairs=count, input_detections=2 * count, input_risks=count,
                            output_rows=2 * count, runs=runs, median=summary)
            results["scenarios"].append(scenario)
            print(json.dumps(scenario), flush=True)
            engine.dispose()
    path = ROOT / "output/benchmarks/results-export.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
