"""
Unity 대신 프레임을 보내는 테스트용 송신기

Unity 씬이 준비되기 전에 unity_receiver.py 를 시험하려고 만든다.
영상 파일(또는 웹캠)에서 프레임을 읽어 Unity와 같은 형식으로 POST /frames 에 보낸다.

실행 (ai/ 폴더에서, unity_receiver.py 를 먼저 켜 두고)
  python edge/fake_unity.py --cam1 영상1.mp4 --cam2 영상2.mp4
  python edge/fake_unity.py --cam1 영상.mp4                  # 한 영상을 cam1, cam2 둘 다로 보냄
  python edge/fake_unity.py --cam1 0 --frames 100            # 웹캠
"""

import argparse
import json
import time

import cv2
import requests


def open_cap(src: str):
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened():
        raise SystemExit(f"열 수 없어요: {src}")
    return cap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8100/frames")
    parser.add_argument("--cam1", required=True, help="영상 파일 또는 웹캠 번호")
    parser.add_argument("--cam2", default=None, help="없으면 cam1 프레임을 cam2로도 보냄")
    parser.add_argument("--session", default="fake-unity-01")
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--frames", type=int, default=0, help="보낼 묶음 수 (0 = 영상 끝까지)")
    args = parser.parse_args()

    caps = {"cam1": open_cap(args.cam1)}
    if args.cam2:
        caps["cam2"] = open_cap(args.cam2)

    session = requests.Session()
    frame_no = 0
    interval = 1 / args.fps
    while not args.frames or frame_no < args.frames:
        t0 = time.perf_counter()
        images = {}
        for cam_id, cap in caps.items():
            ok, img = cap.read()
            if not ok:
                print("영상 끝")
                return
            images[cam_id] = img
        if "cam2" not in images:
            images["cam2"] = images["cam1"]

        frame_no += 1
        meta = {"session_id": args.session, "frame": frame_no, "ts": int(time.time() * 1000)}
        files = {cam_id: (f"{cam_id}.jpg", cv2.imencode(".jpg", img)[1].tobytes(), "image/jpeg")
                 for cam_id, img in images.items()}
        r = session.post(args.url, data={"meta": json.dumps(meta)}, files=files, timeout=10)
        if r.ok:
            body = r.json()
            print(f"묶음 {frame_no}: 탐지 {body['counts']} ({body['ms']}ms)")
        else:
            print(f"묶음 {frame_no}: 에러 {r.status_code} {r.text}")

        time.sleep(max(0.0, interval - (time.perf_counter() - t0)))


if __name__ == "__main__":
    main()