import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from config import (
    CAPTURES_DIR,
    CHARUCO_DICTIONARY_ID,
    CHARUCO_MARKER_LENGTH_M,
    CHARUCO_SQUARE_LENGTH_M,
    CHARUCO_SQUARES_X,
    CHARUCO_SQUARES_Y,
    OUTPUT_DIR,
)


def create_board():
    dictionary = cv2.aruco.getPredefinedDictionary(CHARUCO_DICTIONARY_ID)
    return cv2.aruco.CharucoBoard(
        (CHARUCO_SQUARES_X, CHARUCO_SQUARES_Y),
        CHARUCO_SQUARE_LENGTH_M,
        CHARUCO_MARKER_LENGTH_M,
        dictionary,
    )


def calibrate(images_dir: Path) -> dict:
    board = create_board()
    detector = cv2.aruco.CharucoDetector(board)
    all_corners, all_ids = [], []
    image_size = None

    paths = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        size = (image.shape[1], image.shape[0])
        if image_size is not None and size != image_size:
            raise ValueError(f"이미지 해상도가 다릅니다: {path} ({size} != {image_size})")
        image_size = size
        corners, ids, _, _ = detector.detectBoard(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        )
        if ids is not None and len(ids) >= 6:
            all_corners.append(corners)
            all_ids.append(ids)

    if image_size is None:
        raise ValueError(f"캘리브레이션 이미지를 찾지 못했습니다: {images_dir}")
    if len(all_corners) < 10:
        raise ValueError(
            f"유효 이미지가 {len(all_corners)}장뿐입니다. 서로 다른 각도의 사진을 10장 이상 준비하세요."
        )

    error, K, dist, _, _ = cv2.aruco.calibrateCameraCharuco(
        all_corners, all_ids, board, image_size, None, None
    )
    return {
        "image_size": list(image_size),
        "K": K.tolist(),
        "dist": dist.reshape(-1).tolist(),
        "reprojection_error": float(error),
        "valid_images": len(all_corners),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ChArUco 카메라 내부 캘리브레이션")
    parser.add_argument("--images", type=Path, default=CAPTURES_DIR)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = calibrate(args.images)
    result["camera_id"] = args.camera_id
    output = args.output or OUTPUT_DIR / f"{args.camera_id}_intrinsics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"내부 캘리브레이션 저장: {output}")
    print(f"재투영 오차: {result['reprojection_error']:.4f}px")


if __name__ == "__main__":
    main()
