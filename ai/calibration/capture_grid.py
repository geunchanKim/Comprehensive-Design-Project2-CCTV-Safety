"""Capture fixed-camera frames containing multiple surveyed ArUco grid points."""
import argparse
import time

import cv2

from config import ARUCO_DICTIONARY_ID, CAMERA_HEIGHT, CAMERA_INDEX, CAMERA_WIDTH, CAPTURES_DIR
from capture_source import add_camera_args, next_image, open_camera


def main():
    parser = argparse.ArgumentParser(description="다점 PnP용 ArUco 격자 촬영")
    parser.add_argument("--camera-id", required=True)
    add_camera_args(parser)
    parser.add_argument("--min-markers", type=int, default=6)
    args = parser.parse_args()
    output_dir = CAPTURES_DIR / "grid" / args.camera_id
    output_dir.mkdir(parents=True, exist_ok=True)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY_ID))
    camera = open_camera(args, args.camera_id)
    saved = len(list(output_dir.glob("*.png")))
    while True:
        frame = next_image(camera)
        corners, ids, _ = detector.detectMarkers(frame)
        marker_ids = sorted(ids.reshape(-1).tolist()) if ids is not None else []
        preview = frame.copy()
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(preview, corners, ids)
        enough = len(marker_ids) >= args.min_markers
        cv2.putText(preview, f"IDs: {marker_ids} | saved: {saved}", (25, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0) if enough else (0, 0, 255), 2)
        cv2.putText(preview, "SPACE: save | Q: quit", (25, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
        cv2.imshow(f"ArUco grid - {args.camera_id}", preview)
        key = cv2.waitKey(1) & 0xFF
        if key == 32:
            if not enough:
                print(f"저장 안 함: 마커 {len(marker_ids)}개 검출 (최소 {args.min_markers}개)")
                continue
            path = output_dir / f"grid_{int(time.time() * 1000)}.png"
            cv2.imwrite(str(path), frame)
            saved += 1
            print(f"[{saved}] 저장: {path.name}, IDs={marker_ids}")
        elif key in (ord("q"), 27):
            break
    camera.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
