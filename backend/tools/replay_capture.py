"""Validate or replay a stored /detections capture without inventing heartbeats.

Default: offline validation. --send requires a dashboard-capable, risk-enabled
demo server. Use a fresh session for each replay; no automatic retries or resets.
"""
import argparse
import copy
import gzip
import hashlib
import json
import time
import zipfile
from collections import Counter
from pathlib import Path

import requests

from backend.schemas import CameraCalibrationIn, DetectionBundleIn


def load_capture(path):
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if Path(n).name == "sent_detections.jsonl"]
            if len(names) != 1:
                raise ValueError("ZIP must contain exactly one sent_detections.jsonl")
            data = archive.read(names[0]).decode("utf-8-sig")
    elif path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig") as source:
            data = source.read()
    else:
        data = path.read_text(encoding="utf-8-sig")
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if not rows:
        raise ValueError("capture is empty")
    pairs, timestamps, sessions = set(), [], set()
    for row in rows:
        DetectionBundleIn.model_validate(row)
        if row["pair_id"] in pairs:
            raise ValueError("duplicate pair_id in capture")
        pairs.add(row["pair_id"])
        sessions.add(row["session_id"])
        if row.get("calibration_profile", "basic") != "basic":
            raise ValueError("this demo requires a basic capture")
        if {f["camera_id"] for f in row["frames"]} != {"cam1", "cam2"}:
            raise ValueError("capture must contain cam1 and cam2")
        timestamps.append(next(f["ts"] for f in row["frames"] if f["camera_id"] == "cam1"))
    if len(sessions) != 1 or timestamps != sorted(timestamps):
        raise ValueError("capture must have one session and nondecreasing cam1 timestamps")
    return rows, timestamps


def shifted(row, session_id, offset_ms):
    result = copy.deepcopy(row)
    result["session_id"] = session_id
    for frame in result["frames"]:
        frame["ts"] += offset_ms
        if frame.get("recv_ms") is not None:
            frame["recv_ms"] += offset_ms
    return result


def require_ready(health, paths):
    required = {"/dashboard/configuration", "/dashboard/snapshot", "/dashboard/cameras",
                "/edge/heartbeat", "/alerts", "/alerts/{alert_id}/ack"}
    missing = sorted(required - set(paths))
    if missing:
        raise ValueError("server lacks demo APIs: " + ", ".join(missing))
    settings = health.get("algorithms", {}).get("baseline", {})
    if settings.get("risk_analysis") is not True:
        raise ValueError("baseline risk analysis is disabled; use a dedicated demo process")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8001")
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, help="explicit map/zones JSON, never inferred from capture")
    parser.add_argument("--out", type=Path, required=True, help="new report file; responses stored alongside")
    parser.add_argument("--send", action="store_true", help="register then replay in real time")
    parser.add_argument("--provenance", choices=["stored-edge-capture", "gt-derived"], default="stored-edge-capture")
    args = parser.parse_args()
    rows, timestamps = load_capture(args.capture)
    DetectionBundleIn.model_validate(shifted(rows[0], args.session, 0))
    calibration = json.loads(args.calibration.read_text(encoding="utf-8-sig"))
    registrations = {}
    for camera_id in ("cam1", "cam2"):
        body = calibration[camera_id].get("basic", calibration[camera_id])
        registrations[camera_id] = CameraCalibrationIn.model_validate({
            **body, "session_id": args.session, "calibration_profile": "basic",
        }).model_dump(mode="json")
        expected = registrations[camera_id]["image_size"]
        if any(frame["image_size"] != expected for row in rows for frame in row["frames"]
               if frame["camera_id"] == camera_id):
            raise ValueError("capture resolution differs from calibration")
    configuration = None
    if args.configuration:
        from backend.dashboard import DashboardMap, ZoneSet
        supplied = json.loads(args.configuration.read_text(encoding="utf-8-sig"))
        configuration = {"map": DashboardMap.model_validate(supplied["map"]).model_dump(mode="json"),
                         "zones": ZoneSet.model_validate(supplied["zones"]).model_dump(mode="json")}
        if configuration["map"]["coordinate_frame_id"] != configuration["zones"]["coordinate_frame_id"]:
            raise ValueError("map and zone coordinate frames differ")
    if args.send and configuration is None:
        raise ValueError("--send requires --configuration for a fresh session")
    report = {"condition": {"session_id": args.session, "calibration_profile": "basic", "algorithm": "baseline"},
              "capture_sha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
              "bundles": len(rows), "duration_s": (timestamps[-1]-timestamps[0])/1000,
              "input_classes": dict(Counter(d["cls"] for row in rows for f in row["frames"] for d in f["detections"])),
              "heartbeat_sent": False, "provenance": args.provenance,
              "sent": 0, "complete": False, "mode": "send" if args.send else "offline"}
    # Reserve before any mutations, never replace previous evidence.
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
    if not args.send:
        print(json.dumps(report))
        return
    http = requests.Session()

    def call(method, path, **kwargs):
        response = http.request(method, args.server.rstrip("/")+path, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
        return response

    try:
        health = call("GET", "/health").json()
        require_ready(health, call("GET", "/openapi.json").json()["paths"])
        call("GET", "/health/db")
        report["server_commit"] = health.get("commit")
        key = report["condition"]
        if call("GET", "/dashboard/snapshot", params=key).status_code != 204:
            raise ValueError("session already has a snapshot; choose a fresh session")
        response_path = args.out.with_suffix(".responses.jsonl")
        with response_path.open("x", encoding="utf-8") as output:
            call("PUT", "/dashboard/configuration", params=key, json=configuration)
            for camera_id, body in registrations.items():
                call("PUT", f"/cameras/{camera_id}/calibration", json=body)
            counts = Counter()
            minimum = None
            start = time.monotonic()
            offset = time.time_ns()//1_000_000 - timestamps[0]
            report["timestamp_offset_ms"] = offset
            report["max_lateness_ms"] = 0
            for row, timestamp in zip(rows, timestamps):
                due = start + (timestamp-timestamps[0])/1000
                time.sleep(max(0, due-time.monotonic()))
                report["max_lateness_ms"] = max(report["max_lateness_ms"], round((time.monotonic()-due)*1000, 2))
                result = call("POST", "/detections", json=shifted(row, args.session, offset)).json()
                report["sent"] += 1
                output.write(json.dumps(result)+"\n")
                output.flush()
                for risk in result["risks"]:
                    counts[risk["level"]] += 1
                    minimum = risk["distance_m"] if minimum is None else min(minimum, risk["distance_m"])
                report.update(risk_pair_samples=dict(counts), minimum_distance_m=minimum)
                if report["sent"] % 100 == 0:
                    print(f'{report["sent"]}/{len(rows)}', flush=True)
            snapshot = call("GET", "/dashboard/snapshot", params=key).json()
            if snapshot["pair_id"] != rows[-1]["pair_id"]:
                raise ValueError("final snapshot pair_id mismatch")
            report.update(complete=True, elapsed_s=round(time.monotonic()-start, 2),
                          final_pair_id=snapshot["pair_id"], cameras=call("GET", "/dashboard/cameras", params=key).json())
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
