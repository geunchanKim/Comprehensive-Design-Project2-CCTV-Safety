"""
가짜 Unity 폴더 생성기 (테스트용)

Unity 데이터가 나오기 전에, 영상(또는 웹캠)으로 Unity와 똑같은 형식의 폴더를 만든다.
이 폴더로 unity_reader.py(폴더 읽기 → 탐지 → 서버 전송)를 미리 시험한다.

만들어지는 폴더 (Unity 요청 이슈와 같은 형식)
  <out>/
  ├── cam1/000001.jpg ...    영상 프레임 (1920×1080)
  ├── cam2/000001.jpg ...    두 번째 영상, 없으면 cam1과 같은 이미지
  ├── frames.jsonl           {"frame", "ts", "objects": [...]}  ts = 시작 시각 + frame × 100ms
  └── cameras.json           가짜 카메라 설정 ("fake": true 표시)

--dummy-gt 를 주면 정답 좌표 테스트용으로 "가짜 사람 1명이 x축으로 초속 1m 걷는" 정답을 넣는다.
(영상 속 실제 사람과는 상관없음. /ground-truth 전송과 좌표 변환 확인용)

실행 (ai/ 폴더에서)
  python tools/make_fake_unity_run.py --cam1 영상.mp4 --frames 50 --dummy-gt
  python tools/make_fake_unity_run.py --cam1 영상1.mp4 --cam2 영상2.mp4 --out runs/unity/fake-classroom-02
"""

import argparse
import json
import time
from pathlib import Path

import cv2

AI_DIR = Path(__file__).resolve().parent.parent
SIZE = (1920, 1080)
FPS = 10                      # Unity 약속: 초당 10프레임 → 프레임 간격 100ms


def open_cap(src: str):
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened():
        raise SystemExit(f"열 수 없어요: {src}")
    return cap


def read_every(cap, step: int):
    """영상에서 step 프레임마다 한 장씩 읽는다 (30fps 영상 → 3장마다 1장 = 10fps)"""
    for _ in range(step - 1):
        cap.grab()
    ok, img = cap.read()
    return img if ok else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam1", required=True, help="영상 파일 또는 웹캠 번호")
    parser.add_argument("--cam2", default=None, help="없으면 cam1 이미지를 cam2로 복사")
    parser.add_argument("--out", default=str(AI_DIR / "runs" / "unity" / "fake-classroom-01"))
    parser.add_argument("--frames", type=int, default=50, help="만들 프레임 수")
    parser.add_argument("--dummy-gt", action="store_true", help="가짜 정답 좌표 넣기")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"이미 있는 폴더예요. 다른 --out 을 주거나 지워 주세요: {out}")
    for cam in ("cam1", "cam2"):
        (out / cam).mkdir(parents=True, exist_ok=True)

    caps = {"cam1": open_cap(args.cam1)}
    if args.cam2:
        caps["cam2"] = open_cap(args.cam2)
    steps = {cam: max(1, round((cap.get(cv2.CAP_PROP_FPS) or 30) / FPS)) for cam, cap in caps.items()}

    start_ts = int(time.time() * 1000)
    written = 0
    with open(out / "frames.jsonl", "w", encoding="utf-8") as f:
        for frame in range(1, args.frames + 1):
            images = {cam: read_every(cap, steps[cam]) for cam, cap in caps.items()}
            if any(img is None for img in images.values()):
                print("영상 끝")
                break
            images.setdefault("cam2", images["cam1"])
            for cam, img in images.items():
                img = cv2.resize(img, SIZE)
                cv2.imwrite(str(out / cam / f"{frame:06d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])

            objects = []
            if args.dummy_gt:
                t = (frame - 1) / FPS
                # Unity 좌표 그대로 (y가 위쪽): x축으로 초속 1m, 바닥(y=0), z=3m
                objects.append({"object_id": "person_1", "cls": "person", "world": [round(1.0 + t, 3), 0.0, 3.0]})
            f.write(json.dumps({"frame": frame, "ts": start_ts + (frame - 1) * 100, "objects": objects}) + "\n")
            written = frame

    cameras = {
        "fake": True,
        "cameras": [
            {"camera_id": "cam1", "image_size": list(SIZE), "vertical_fov_deg": 46.8,
             "position": [0.3, 2.0, 0.3], "rotation_quat": [0, 0, 0, 1], "rotation_euler_deg": [35, 45, 0]},
            {"camera_id": "cam2", "image_size": list(SIZE), "vertical_fov_deg": 46.8,
             "position": [6.5, 2.0, 0.3], "rotation_quat": [0, 0, 0, 1], "rotation_euler_deg": [35, -45, 0]},
        ],
    }
    (out / "cameras.json").write_text(json.dumps(cameras, indent=2), encoding="utf-8")
    print(f"완료: {out} ({written}프레임, 정답 {'있음' if args.dummy_gt else '없음'})")


if __name__ == "__main__":
    main()