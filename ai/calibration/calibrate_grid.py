"""Solve camera extrinsics from surveyed multi-ArUco centers and validate in centimetres."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from config import ARUCO_DICTIONARY_ID, OUTPUT_DIR


def load_points(path: Path) -> dict[int, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("unit") != "meter":
        raise ValueError("grid point unit must be 'meter'")
    points = {}
    for item in data["points"]:
        if len(item.get("world", [])) != 3 or any(value is None for value in item["world"]):
            raise ValueError(f"marker {item.get('marker_id')} world coordinate is incomplete")
        if item["role"] not in {"pnp", "validation"}:
            raise ValueError("point role must be pnp or validation")
        points[int(item["marker_id"])] = item
    return points


def detect_centers(images_dir: Path) -> tuple[dict[int, np.ndarray], dict[int, int], tuple[int, int]]:
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY_ID))
    observations: dict[int, list[np.ndarray]] = {}
    image_size = None
    paths = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        size = (image.shape[1], image.shape[0])
        if image_size is not None and size != image_size:
            raise ValueError(f"image sizes differ: {path} ({size} != {image_size})")
        image_size = size
        corners, ids, _ = detector.detectMarkers(image)
        if ids is None:
            continue
        for corner, marker_id in zip(corners, ids.reshape(-1)):
            observations.setdefault(int(marker_id), []).append(corner.reshape(4, 2).mean(axis=0))
    if image_size is None:
        raise ValueError(f"no calibration images found: {images_dir}")
    centers = {marker_id: np.median(values, axis=0) for marker_id, values in observations.items()}
    counts = {marker_id: len(values) for marker_id, values in observations.items()}
    return centers, counts, image_size


def plane_intersection(pixel, world_z, K, dist, R, t):
    normalized = cv2.undistortPoints(np.asarray(pixel, dtype=np.float64).reshape(1, 1, 2), K, dist).reshape(2)
    center = -R.T @ t.reshape(3)
    direction = R.T @ np.array([normalized[0], normalized[1], 1.0])
    if abs(direction[2]) < 1e-12:
        raise ValueError("validation ray is parallel to reference plane")
    scale = (world_z - center[2]) / direction[2]
    if scale <= 0:
        raise ValueError("validation point is behind camera")
    return center + scale * direction


def solve(points, centers, image_size, K, dist):
    pnp = [item for marker_id, item in points.items() if item["role"] == "pnp" and marker_id in centers]
    validation = [item for marker_id, item in points.items()
                  if item["role"] == "validation" and marker_id in centers]
    if len(pnp) < 6:
        raise ValueError(f"PnP markers detected: {len(pnp)} (at least 6 required)")
    if len(validation) < 2:
        raise ValueError(f"validation markers detected: {len(validation)} (at least 2 required)")
    world = np.asarray([item["world"] for item in pnp], dtype=np.float64)
    pixels = np.asarray([centers[int(item["marker_id"])] for item in pnp], dtype=np.float64)
    if np.linalg.matrix_rank(world[:, :2] - world[:, :2].mean(axis=0)) < 2:
        raise ValueError("PnP world points are collinear")
    span = np.ptp(pixels, axis=0)
    if span[0] < image_size[0] * 0.25 or span[1] < image_size[1] * 0.25:
        raise ValueError("PnP markers must span at least 25% of image width and height")
    grid_heights = {float(item["world"][2]) for item in pnp}
    if all(float(item["world"][2]) in grid_heights for item in validation):
        raise ValueError("at least one validation marker must have a different height")
    ok, rvec, tvec = cv2.solvePnP(world, pixels, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise RuntimeError("multi-point PnP failed")
    projected, _ = cv2.projectPoints(world, rvec, tvec, K, dist)
    reprojection = np.linalg.norm(projected.reshape(-1, 2) - pixels, axis=1)
    R, _ = cv2.Rodrigues(rvec)
    camera_center = -R.T @ tvec.reshape(3)
    pnp_distances = np.linalg.norm(world - camera_center, axis=1)
    validation_rows = []
    for item in validation:
        marker_id = int(item["marker_id"])
        actual = np.asarray(item["world"], dtype=float)
        estimated = plane_intersection(centers[marker_id], actual[2], K, dist, R, tvec)
        error_cm = float(np.linalg.norm(estimated - actual) * 100.0)
        distance_m = float(np.linalg.norm(actual - camera_center))
        validation_rows.append({"marker_id": marker_id, "actual_world": actual.tolist(),
                                "estimated_world": estimated.tolist(), "error_cm": error_cm,
                                "camera_distance_m": distance_m})
    if not any(row["camera_distance_m"] > float(np.max(pnp_distances)) for row in validation_rows):
        raise ValueError("at least one validation marker must be farther than every PnP marker")
    errors = np.asarray([row["error_cm"] for row in validation_rows])
    return rvec.reshape(3), tvec.reshape(3), float(np.sqrt(np.mean(reprojection ** 2))), validation_rows, errors


def upload(url, camera_id, payload):
    request = Request(f"{url.rstrip('/')}/cameras/{camera_id}/calibration",
                      data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"backend returned HTTP {response.status}")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"backend upload failed: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description="다점 ArUco 격자 PnP 및 cm 검증")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--intrinsics", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend-url")
    args = parser.parse_args()
    intrinsic = json.loads(args.intrinsics.read_text(encoding="utf-8"))
    K, dist = np.asarray(intrinsic["K"], dtype=float), np.asarray(intrinsic["dist"], dtype=float)
    points = load_points(args.points)
    centers, counts, image_size = detect_centers(args.images)
    if tuple(intrinsic["image_size"]) != image_size:
        raise ValueError(f"image size {image_size} differs from intrinsics {intrinsic['image_size']}")
    rvec, tvec, reproj, validation, errors = solve(points, centers, image_size, K, dist)
    payload = {"session_id": args.session_id, "calibration_profile": "precise",
               "method": "charuco-aruco", "image_size": list(image_size), "K": K.tolist(),
               "dist": dist.reshape(-1).tolist(), "rvec": rvec.tolist(), "tvec": tvec.tolist(),
               "reproj_error_px": reproj,
               "validation_rmse_cm": float(np.sqrt(np.mean(errors ** 2))),
               "validation_max_error_cm": float(np.max(errors)),
               "validation_point_count": len(validation)}
    output = args.output or OUTPUT_DIR / f"{args.camera_id}_precise.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report = {"camera_id": args.camera_id, "detected_marker_counts": counts,
              "centers_px": {str(key): value.tolist() for key, value in centers.items()},
              "pnp_reprojection_rmse_px": reproj, "validation": validation,
              "validation_rmse_cm": payload["validation_rmse_cm"],
              "validation_max_error_cm": payload["validation_max_error_cm"]}
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"저장: {output}")
    print(f"PnP {reproj:.3f}px | 검증 RMSE {payload['validation_rmse_cm']:.2f}cm | 최대 {payload['validation_max_error_cm']:.2f}cm")
    if args.backend_url:
        upload(args.backend_url, args.camera_id, payload)
        print("백엔드 precise 프로필 등록 완료")


if __name__ == "__main__":
    main()
