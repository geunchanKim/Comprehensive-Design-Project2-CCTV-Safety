import argparse
import time

import cv2

from config import (
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    CAPTURES_DIR,
    CHARUCO_DICTIONARY_ID,
    CHARUCO_MARKER_LENGTH_M,
    CHARUCO_SQUARE_LENGTH_M,
    CHARUCO_SQUARES_X,
    CHARUCO_SQUARES_Y,
)
from capture_source import add_camera_args, next_image, open_camera


def create_detector():
    dictionary = cv2.aruco.getPredefinedDictionary(
        CHARUCO_DICTIONARY_ID
    )

    board = cv2.aruco.CharucoBoard(
        (CHARUCO_SQUARES_X, CHARUCO_SQUARES_Y),
        CHARUCO_SQUARE_LENGTH_M,
        CHARUCO_MARKER_LENGTH_M,
        dictionary,
    )

    detector = cv2.aruco.CharucoDetector(board)

    return detector


def main() -> None:
    parser = argparse.ArgumentParser(description="ChArUco 이미지 촬영")
    parser.add_argument("--camera-id", required=True)
    add_camera_args(parser)
    args = parser.parse_args()
    captures_dir = CAPTURES_DIR / args.camera_id
    captures_dir.mkdir(parents=True, exist_ok=True)

    detector = create_detector()

    camera = open_camera(args, args.camera_id)
    actual_width, actual_height = camera.size

    print(f"실제 해상도: {actual_width} × {actual_height}")
    print("SPACE: 저장")
    print("Q 또는 ESC: 종료")

    saved_count = len(list(captures_dir.glob("*.png")))

    while True:
        frame = next_image(camera)

        preview = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        try:
            (
                charuco_corners,
                charuco_ids,
                marker_corners,
                marker_ids,
            ) = detector.detectBoard(gray)
        except cv2.error:
            charuco_corners = None
            charuco_ids = None
            marker_corners = None
            marker_ids = None

        valid_charuco = (
            charuco_corners is not None
            and charuco_ids is not None
            and len(charuco_corners) == len(charuco_ids)
            and len(charuco_ids) > 0
        )
        corner_count = len(charuco_ids) if valid_charuco else 0

        valid_markers = (
            marker_corners is not None
            and marker_ids is not None
            and len(marker_corners) == len(marker_ids)
            and len(marker_ids) > 0
        )

        if valid_markers:
            try:
                cv2.aruco.drawDetectedMarkers(
                    preview,
                    marker_corners,
                    marker_ids,
                )
            except cv2.error:
                pass

        if valid_charuco:
            try:
                cv2.aruco.drawDetectedCornersCharuco(
                    preview,
                    charuco_corners,
                    charuco_ids,
                )
            except cv2.error:
                valid_charuco = False
                corner_count = 0

        cv2.putText(
            preview,
            (
                f"corners: {corner_count} | "
                f"saved: {saved_count}"
            ),
            (25, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2,
        )

        cv2.putText(
            preview,
            "SPACE: save | Q: quit",
            (25, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
        )

        cv2.imshow("ChArUco capture", preview)

        key = cv2.waitKey(1) & 0xFF

        if key == 32:
            if corner_count < 6:
                print(
                    "저장 안 함: 검출된 코너가 너무 적습니다."
                )
                continue

            timestamp = int(time.time() * 1000)
            output_path = (
                captures_dir
                / f"charuco_{timestamp}.png"
            )

            cv2.imwrite(str(output_path), frame)
            saved_count += 1

            print(
                f"[{saved_count}] 저장: "
                f"{output_path.name}, "
                f"코너 {corner_count}개"
            )

        elif key == ord("q") or key == 27:
            break

    camera.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
