import argparse
import time

import cv2

from config import (
    ARUCO_DICTIONARY_ID,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    CAPTURES_DIR,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="외부 캘리브레이션용 ArUco 촬영")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--marker-id", type=int, default=0)
    args = parser.parse_args()

    captures_dir = CAPTURES_DIR / "aruco" / args.camera_id
    captures_dir.mkdir(parents=True, exist_ok=True)
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY_ID)
    detector = cv2.aruco.ArucoDetector(dictionary)
    camera = cv2.VideoCapture(CAMERA_INDEX)
    if not camera.isOpened():
        raise RuntimeError("카메라를 열 수 없습니다.")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    saved_count = len(list(captures_dir.glob("*.png")))

    while True:
        success, frame = camera.read()
        if not success:
            break
        preview = frame.copy()
        corners, ids, _ = detector.detectMarkers(frame)
        found = ids is not None and args.marker_id in ids.reshape(-1)
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(preview, corners, ids)
        cv2.putText(
            preview,
            f"marker {args.marker_id}: {'OK' if found else 'NOT FOUND'} | saved: {saved_count}",
            (25, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0) if found else (0, 0, 255),
            2,
        )
        cv2.putText(preview, "SPACE: save | Q: quit", (25, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imshow("ArUco capture", preview)
        key = cv2.waitKey(1) & 0xFF
        if key == 32:
            if not found:
                print(f"저장 안 함: ID {args.marker_id} 마커가 보이지 않습니다.")
                continue
            output = captures_dir / f"aruco_{int(time.time() * 1000)}.png"
            cv2.imwrite(str(output), frame)
            saved_count += 1
            print(f"[{saved_count}] 저장: {output}")
        elif key in (ord("q"), 27):
            break

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
