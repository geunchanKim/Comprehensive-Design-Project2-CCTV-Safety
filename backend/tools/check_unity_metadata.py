"""Check one Unity scene ZIP's metadata against existing server/edge contracts."""
import argparse
import json
import math
import zipfile
from pathlib import Path

import cv2
import numpy as np

from ai.edge.unity_calibration import camera_calibration, project, projection, unity_to_world
from backend.schemas import CameraCalibrationIn, GroundTruthIn


def check(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = [n for n in names if n.endswith("/cameras.json") or n == "cameras.json"]
        if len(metadata) != 1:
            raise ValueError("ZIP must contain exactly one scene")
        root = metadata[0][:-len("cameras.json")]
        cameras = json.loads(archive.read(root + "cameras.json"))
        frames = [json.loads(line) for line in archive.read(root + "frames.jsonl").decode("utf-8-sig").splitlines()
                  if line.strip()]
        events = json.loads(archive.read(root + "events.json"))
        camera_ids = [camera["camera_id"] for camera in cameras["cameras"]]
        if set(camera_ids) != {"cam1", "cam2"} or len(camera_ids) != 2:
            raise ValueError("scene must have cam1 and cam2")
        if not frames or len(frames) != events["frame_count"]:
            raise ValueError("frame count disagrees with events.json")
        fps = float(events["fps"])
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be positive")
        matrices = {}
        for camera in cameras["cameras"]:
            payload = camera_calibration(camera, "unity-metadata-check")
            CameraCalibrationIn.model_validate(payload)
            matrices[camera["camera_id"]] = projection(payload)
        max_roundtrip_m, max_rel_error_m = 0.0, 0.0
        object_ids, object_frames, above_015, ankle_samples, behind = set(), 0, 0, 0, 0
        origin = cameras.get("rel_frame", {}).get("origin_world")
        # This check only supports the unrotated frame reported in #72.
        if origin is not None:
            axes = cameras["rel_frame"]
            if any(axes.get(key) != value for key, value in {
                "x_world": [1, 0, 0], "y_world": [0, 0, 1], "z_world": [0, 1, 0],
            }.items()):
                raise ValueError("rel frame is rotated; cannot assume translation-only mapping")
        for number, row in enumerate(frames, 1):
            if row["frame"] != number:
                raise ValueError("frame numbers must start at 1 and be consecutive")
            expected_ts = frames[0]["ts"] + round((number - 1) * 1000 / fps)
            if abs(row["ts"] - expected_ts) > 1:
                raise ValueError(f"timestamp mismatch at frame {number}")
            for camera_id in camera_ids:
                if root + f"{camera_id}/{number:06d}.jpg" not in names:
                    raise ValueError(f"missing camera image at frame {number}")
            converted = []
            per_frame_ids = set()
            for item in row["objects"]:
                if item["object_id"] in per_frame_ids:
                    raise ValueError(f"duplicate object ID at frame {number}")
                per_frame_ids.add(item["object_id"])
                object_ids.add(item["object_id"])
                object_frames += 1
                world = np.asarray(unity_to_world(item["world"]), dtype=float)
                if not np.isfinite(world).all():
                    raise ValueError("world coordinates must be finite")
                converted.append({"object_id": item["object_id"], "cls": item["cls"],
                                  "world": world.tolist(), "bbox": item.get("bbox", {})})
                if origin is not None and "rel" in item:
                    error = np.linalg.norm(world - np.asarray(unity_to_world(origin)) - np.asarray(item["rel"]))
                    if not np.isfinite(error) or error > 1e-3:
                        raise ValueError(f"world/rel translation mismatch at frame {number}")
                    max_rel_error_m = max(max_rel_error_m, float(error))
                mid = item.get("ankles", {}).get("world", {}).get("mid")
                if mid is not None:
                    ankle_samples += 1
                    above_015 += mid[1] > 0.15
                points = [project(matrices[camera_id], world) for camera_id in camera_ids]
                if any(depth <= 0 for _, depth in points):
                    behind += 1
                    continue
                homogeneous = cv2.triangulatePoints(
                    matrices[camera_ids[0]], matrices[camera_ids[1]],
                    points[0][0].reshape(2, 1), points[1][0].reshape(2, 1))
                reconstructed = (homogeneous[:3] / homogeneous[3]).ravel()
                error = float(np.linalg.norm(reconstructed - world))
                if not math.isfinite(error) or error > 1e-4:
                    raise ValueError("calibration/GT roundtrip failed")
                max_roundtrip_m = max(max_roundtrip_m, error)
            GroundTruthIn.model_validate({"session_id": "unity-metadata-check", "frame": number,
                                          "ts": row["ts"], "objects": converted})
        event_names = {}
        for event in events["events"]:
            if event["name"] in event_names or not 1 <= event["frame"] <= len(frames):
                raise ValueError("invalid or duplicate event")
            event_names[event["name"]] = event["frame"]
        for alert in events.get("expected_alerts", []):
            if event_names[alert["from"]] > event_names[alert["to"]]:
                raise ValueError("alert interval is reversed")
        return {"scene": root.rstrip("/"), "frames": len(frames), "fps": fps,
                "objects": sorted(object_ids), "object_frames": object_frames,
                "coordinate_frame_id": "unity-world-xzy", "origin_world": origin,
                "max_rel_translation_error_m": max_rel_error_m,
                "max_calibration_roundtrip_error_m": max_roundtrip_m,
                "objects_behind_camera": behind, "events": len(event_names),
                "expected_alerts": len(events.get("expected_alerts", [])),
                "ankle_mid_samples": ankle_samples, "ankle_mid_above_015m": int(above_015),
                "note": "GT height diagnostic only; not measured detector/server rejection rate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.zip)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
