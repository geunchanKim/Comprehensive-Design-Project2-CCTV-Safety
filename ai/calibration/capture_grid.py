"""Capture fixed-camera frames containing multiple surveyed ArUco grid points."""
import argparse
import getpass
import os
import time
from urllib.parse import quote

import cv2

from config import ARUCO_DICTIONARY_ID, CAMERA_HEIGHT, CAMERA_INDEX, CAMERA_WIDTH, CAPTURES_DIR


def open_camera(camera_ip: str | None):
    if not camera_ip:
        return cv2.VideoCapture(CAMERA_INDEX), None
    username = input("카메라 계정 사용자 이름: ").strip()
    password = getpass.getpass("카메라 계정 비밀번호: ")
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    source = (f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}@"
              f"{camera_ip}:554/stream1")
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG), source


def main():
    parser = argparse.ArgumentParser(description="다점 PnP용 ArUco 격자 촬영")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--camera-ip", help="RTSP 카메라 IP")
    parser.add_argument("--min-markers", type=int, default=6)
    parser.add_argument("--max-reconnects", type=int, default=5)
    args = parser.parse_args()
    output_dir = CAPTURES_DIR / "grid" / args.camera_id
    output_dir.mkdir(parents=True, exist_ok=True)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY_ID))
    camera, source = open_camera(args.camera_ip)
    if not camera.isOpened():
        raise RuntimeError("카메라를 열 수 없습니다. IP와 RTSP 카메라 계정을 확인하세요.")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    saved = len(list(output_dir.glob("*.png")))
    reconnects = 0
    while True:
        ok, frame = camera.read()
        if not ok:
            if source is None or reconnects >= args.max_reconnects:
                raise RuntimeError(f"프레임 수신 실패 (재연결 {reconnects}회)")
            reconnects += 1
            camera.release()
            time.sleep(1)
            camera = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            continue
        reconnects = 0
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
    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
