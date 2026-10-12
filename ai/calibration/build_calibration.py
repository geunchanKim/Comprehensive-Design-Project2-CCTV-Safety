"""Build one site calibration file from a realtime.py marker recording."""
import argparse
import json
from pathlib import Path

import numpy as np

from calibrate_grid import detect_centers, load_points, solve
from detect_aruco import estimate_extrinsics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True, help="cam1/ and cam2/ parent folder")
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--cam1-intrinsics", type=Path, required=True)
    parser.add_argument("--cam2-intrinsics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--best", type=int, default=10)
    args = parser.parse_args()
    points = load_points(args.points)
    combined, reports = {}, {}
    for camera_id, intrinsic_path in (("cam1", args.cam1_intrinsics), ("cam2", args.cam2_intrinsics)):
        intrinsic = json.loads(intrinsic_path.read_text(encoding="utf-8"))
        K = np.asarray(intrinsic["K"], dtype=float)
        dist = np.asarray(intrinsic["dist"], dtype=float)
        images = args.run / camera_id
        basic_rvec, basic_tvec, basic_error, _ = estimate_extrinsics(images, K, dist, 0, args.best)
        centers, counts, image_size = detect_centers(images, args.best)
        if tuple(intrinsic["image_size"]) != image_size:
            raise ValueError(f"{camera_id}: image size {image_size} differs from intrinsics {intrinsic['image_size']}")
        precise_rvec, precise_tvec, precise_error, validation, errors = solve(
            points, centers, image_size, K, dist)
        common = {"method": "charuco-aruco", "image_size": list(image_size), "K": K.tolist(),
                  "dist": dist.reshape(-1).tolist()}
        combined[camera_id] = {
            "basic": {**common, "calibration_profile": "basic",
                      "rvec": basic_rvec.tolist(), "tvec": basic_tvec.tolist(),
                      "reproj_error_px": basic_error},
            "precise": {**common, "calibration_profile": "precise",
                        "rvec": precise_rvec.tolist(), "tvec": precise_tvec.tolist(),
                        "reproj_error_px": precise_error,
                        "validation_rmse_cm": float(np.sqrt(np.mean(errors ** 2))),
                        "validation_max_error_cm": float(np.max(errors)),
                        "validation_point_count": len(validation)},
        }
        reports[camera_id] = {"detected_marker_counts": counts, "validation": validation,
                              "validation_rmse_cm": combined[camera_id]["precise"]["validation_rmse_cm"],
                              "validation_max_error_cm": combined[camera_id]["precise"]["validation_max_error_cm"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    args.output.with_suffix(".report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(f"saved: {args.output}")
    print(f"report: {args.output.with_suffix('.report.json')}")


if __name__ == "__main__":
    main()
