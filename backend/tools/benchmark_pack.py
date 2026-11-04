"""Replay a checked-in detection pack into an isolated temporary SQLite DB."""
import argparse
import gzip
import json
import logging
import os
import platform
import tempfile
from itertools import islice
from pathlib import Path

from .server_log_summary import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    if args.pairs < 1 or args.warmup < 0:
        parser.error("pairs must be positive and warmup nonnegative")
    with gzip.open(args.pack / "detections.jsonl.gz", "rt", encoding="utf-8") as stream:
        payloads = [json.loads(line) for line in islice(stream, args.pairs + args.warmup)]
    if len(payloads) < args.pairs + args.warmup:
        parser.error("pack has fewer bundles than pairs + warmup")
    calibration = json.loads((args.pack / "calibration.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="cctv-profile-") as temporary:
        # Set before importing database/api. Never use a caller's production DB.
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(temporary) / "benchmark.db").as_posix()
        from backend import api
        from backend.database import Base, SessionLocal, engine
        from backend.schemas import CameraCalibrationIn, DetectionBundleIn

        Base.metadata.create_all(engine)
        logger = logging.getLogger("uvicorn.error")
        logger.setLevel(logging.INFO)
        log_path = args.out / "server-timing.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        try:
            for algorithm in ("baseline", "f-cdfg"):
                session_id = f"local-{args.pack.name}-{algorithm}"
                with SessionLocal() as db:
                    for camera_id, data in calibration.items():
                        api.upsert_camera_calibration(camera_id, CameraCalibrationIn.model_validate({
                            **data, "session_id": session_id, "calibration_profile": "basic",
                        }), db)
                    for index, payload in enumerate(payloads):
                        if index == args.warmup:
                            logger.addHandler(handler)
                        body = DetectionBundleIn.model_validate({
                            **payload, "session_id": session_id, "calibration_profile": "basic",
                        })
                        api._create_detections(body, db, algorithm=algorithm)
                logger.removeHandler(handler)
        finally:
            logger.removeHandler(handler)
            handler.close()
            engine.dispose()
        settings = {a: api._experiment_settings(a) for a in ("baseline", "f-cdfg")}
    report = summarize(log_path.read_text(encoding="utf-8").splitlines())
    context = (f"\n## Measurement environment\n\n"
               f"Local replay, temporary SQLite; excludes HTTP/network/camera/display.\n\n"
               f"- Platform: {platform.platform()}\n- Python: {platform.python_version()}\n"
               f"- Pack: {args.pack.as_posix()}\n- Measured pairs per condition: {args.pairs}\n"
               f"- Warmup pairs per condition: {args.warmup}\n"
               f"- Source: working tree based on APP_COMMIT_SHA; uncommitted changes included.\n\n"
               f"```json\n{json.dumps(settings, indent=2)}\n```\n")
    (args.out / "server-speed.md").write_text(report + context, encoding="utf-8")
    print(args.out / "server-speed.md")


if __name__ == "__main__":
    main()
