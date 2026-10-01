import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from config import ARUCO_DICTIONARY_ID, ARUCO_MARKER_LENGTH_M, OUTPUT_DIR


def marker_object_points() -> np.ndarray:
    half = ARUCO_MARKER_LENGTH_M / 2.0
    return np.array(
        [[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]],
        dtype=np.float32,
    )


def estimate_extrinsics(images_dir: Path, K: np.ndarray, dist: np.ndarray, marker_id: int):
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY_ID)
    detector = cv2.aruco.ArucoDetector(dictionary)
    object_points, image_points = [], []
    used = 0

    paths = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        corners, ids, _ = detector.detectMarkers(image)
        if ids is None:
            continue
        matches = np.flatnonzero(ids.reshape(-1) == marker_id)
        if len(matches) == 0:
            continue
        object_points.append(marker_object_points())
        image_points.append(corners[int(matches[0])].reshape(4, 2))
        used += 1

    if used < 3:
        raise ValueError(
            f"ID {marker_id} 마커가 검출된 이미지가 {used}장뿐입니다. 3장 이상 준비하세요."
        )

    object_points_array = np.concatenate(object_points).astype(np.float32)
    image_points_array = np.concatenate(image_points).astype(np.float32)
    success, rvec, tvec = cv2.solvePnP(
        object_points_array, image_points_array, K, dist, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not success:
        raise RuntimeError("ArUco 외부 파라미터 계산에 실패했습니다.")
    projected, _ = cv2.projectPoints(object_points_array, rvec, tvec, K, dist)
    error = np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - image_points_array) ** 2, axis=1)))
    R, _ = cv2.Rodrigues(rvec)
    return R, tvec.reshape(3), float(error), used


def upload(url: str, camera_id: str, payload: dict) -> None:
    endpoint = f"{url.rstrip('/')}/cameras/{camera_id}"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"백엔드 등록 실패: HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"백엔드 등록 실패: HTTP {exc.code} {exc.read().decode()}") from exc
    except URLError as exc:
        raise RuntimeError(f"백엔드 연결 실패: {exc.reason}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="18cm ArUco 기준 외부 캘리브레이션")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--intrinsics", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--marker-id", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend-url", help="예: http://localhost:8000")
    args = parser.parse_args()

    intrinsic = json.loads(args.intrinsics.read_text(encoding="utf-8"))
    K = np.asarray(intrinsic["K"], dtype=np.float64)
    dist = np.asarray(intrinsic["dist"], dtype=np.float64)
    R, t, error, used = estimate_extrinsics(args.images, K, dist, args.marker_id)
    payload = {
        "camera_id": args.camera_id,
        "image_size": intrinsic["image_size"],
        "K": K.tolist(),
        "dist": dist.reshape(-1).tolist(),
        "R": R.tolist(),
        "t": t.tolist(),
    }
    output = args.output or OUTPUT_DIR / f"{args.camera_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"백엔드 호환 캘리브레이션 저장: {output}")
    print(f"외부 파라미터 재투영 오차: {error:.4f}px ({used}장)")
    if args.backend_url:
        upload(args.backend_url, args.camera_id, payload)
        print(f"백엔드 등록 완료: {args.backend_url.rstrip('/')}/cameras/{args.camera_id}")


if __name__ == "__main__":
    main()
