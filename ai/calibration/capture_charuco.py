import argparse
import getpass
import os
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
    parser.add_argument(
        "--camera-ip",
        help="Tapo 등 RTSP 카메라 IP 주소 (예: 192.168.0.25)",
    )
    args = parser.parse_args()
    captures_dir = CAPTURES_DIR / args.camera_id
    captures_dir.mkdir(parents=True, exist_ok=True)

    detector = create_detector()

    camera_source = None
    if args.camera_ip:
        username = input("카메라 계정 사용자 이름: ").strip()
        password = getpass.getpass("카메라 계정 비밀번호: ")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        camera_source = (
            f"rtsp://{username}:{password}@"
            f"{args.camera_ip}:554/stream1"
        )
        camera = cv2.VideoCapture(camera_source, cv2.CAP_FFMPEG)
    else:
        camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        raise RuntimeError("카메라를 열 수 없습니다.")

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    actual_width = int(
        camera.get(cv2.CAP_PROP_FRAME_WIDTH)
    )
    actual_height = int(
        camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    print(f"실제 해상도: {actual_width} × {actual_height}")
    print("SPACE: 저장")
    print("Q 또는 ESC: 종료")

    saved_count = len(list(captures_dir.glob("*.png")))

    while True:
        success, frame = camera.read()

        if not success:
            if camera_source is None:
                print("카메라 프레임을 읽지 못했습니다.")
                break

            print("RTSP 프레임이 끊겼습니다. 다시 연결합니다...")
            camera.release()
            time.sleep(1)
            camera = cv2.VideoCapture(camera_source, cv2.CAP_FFMPEG)
            continue

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

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
