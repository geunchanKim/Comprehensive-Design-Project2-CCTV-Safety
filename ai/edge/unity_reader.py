"""
Unity 폴더 읽기 → 탐지 → 서버 전송

Unity가 저장한 폴더(cam1/, cam2/, frames.jsonl)를 읽어서
  1) 두 카메라 이미지를 카메라별로 탐지·추적 → POST /detections (묶음)
  2) frames.jsonl의 정답 좌표 → POST /ground-truth
로 보낸다. BE 공지(10/2)의 규칙을 따른다.

규칙
  - session_id = 폴더 이름 + "-runN" (실행마다 N 자동 증가, --run 으로 직접 지정 가능)
  - pair_id = frame_id = Unity frame, ts = frames.jsonl 의 ts
  - 추론 실패(이미지 없음·손상, 모델 오류) 묶음은 보내지 않는다
  - 탐지 0개면 detections: [] 로 보낸다
  - track_id가 아직 없는 탐지는 뺀다 (서버는 0 이상 정수만 받음)
  - bbox는 이미지 안으로 자르고, 폭·높이가 0인 박스는 뺀다
  - 정답 좌표는 Unity (x, y, z) → 월드 (x, z, y) 로 바꿔서 보낸다

결과 저장: runs/edge/<session_id>/
  sent_detections.jsonl, sent_ground-truth.jsonl, failed.jsonl(상태 코드 + 응답), vis/

실행 (ai/ 폴더에서)
  python edge/unity_reader.py runs/unity_runs/fake-classroom-01 --dry-run
  python edge/unity_reader.py runs/unity_runs/fake-classroom-01 --server http://121.182.60.2:32130
  python edge/unity_reader.py runs/unity_runs/fake-classroom-01 --server http://121.182.60.2:32130 --only gt
"""

import argparse
import json
import re
import time
from pathlib import Path

import cv2

from detector import AI_DIR, Detector, draw
from server_client import ServerClient

CAMERAS = ("cam1", "cam2")
OUT_ROOT = AI_DIR / "runs" / "edge"


def unity_to_world(p):
    """Unity (x, y=위, z) → 월드 (X=x, Y=z, Z=위)"""
    x, y, z = p
    return [float(x), float(z), float(y)]


def next_session_id(base: str, run: int | None) -> str:
    """실행마다 -run1, -run2 ... (이 노트북의 runs/edge 기록 기준)"""
    if run is None:
        used = [int(m.group(1)) for d in OUT_ROOT.glob(f"{base}-run*")
                if (m := re.fullmatch(re.escape(base) + r"-run(\d+)", d.name))]
        run = max(used, default=0) + 1
    return f"{base}-run{run}"


def clean_detections(dets: list[dict], width: int, height: int) -> tuple[list[dict], int]:
    """서버 검증에 걸리는 탐지를 정리한다. (정리된 목록, 뺀 개수)"""
    kept, removed = [], 0
    for d in dets:
        if d["track_id"] is None or d["track_id"] < 0:
            removed += 1
            continue
        x1, y1, x2, y2 = d["bbox"]
        x1, x2 = max(0.0, min(x1, float(width))), max(0.0, min(x2, float(width)))
        y1, y2 = max(0.0, min(y1, float(height))), max(0.0, min(y2, float(height)))
        if x2 - x1 < 1 or y2 - y1 < 1:
            removed += 1
            continue
        kept.append({**d, "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]})
    return kept, removed


def build_ground_truth(session_id: str, row: dict) -> dict:
    objects = []
    for o in row.get("objects", []):
        item = {"object_id": o["object_id"], "cls": o["cls"], "world": unity_to_world(o["world"])}
        if o.get("bbox"):
            item["bbox"] = o["bbox"]
        objects.append(item)
    return {"session_id": session_id, "frame": row["frame"], "ts": row["ts"], "objects": objects}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Unity 출력 폴더 (cam1/, cam2/, frames.jsonl)")
    parser.add_argument("--server", default=None, help="예: http://121.182.60.2:32130")
    parser.add_argument("--dry-run", action="store_true", help="서버로 보내지 않고 파일로만 저장")
    parser.add_argument("--only", choices=["all", "detections", "gt"], default="all", help="보낼 종류")
    parser.add_argument("--run", type=int, default=None, help="run 번호 직접 지정 (기본: 자동 증가)")
    parser.add_argument("--model", choices=["v2", "ensemble"], default="v2")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--max-frames", type=int, default=0, help="0 = 전부")
    parser.add_argument("--save-every", type=int, default=0, help="N프레임마다 박스 그린 이미지 저장 (0 = 안 함)")
    args = parser.parse_args()

    folder = Path(args.folder)
    frames_path = folder / "frames.jsonl"
    if not frames_path.exists():
        raise SystemExit(f"frames.jsonl 이 없어요: {frames_path}")
    rows = [json.loads(line) for line in frames_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.max_frames:
        rows = rows[:args.max_frames]

    session_id = next_session_id(folder.name, args.run)
    out_dir = OUT_ROOT / session_id
    vis_dir = out_dir / "vis" if args.save_every else None
    if vis_dir:
        vis_dir.mkdir(parents=True, exist_ok=True)

    client = ServerClient(args.server, out_dir, dry_run=args.dry_run)
    if not client.check_server():
        raise SystemExit(f"서버 {args.server}/health 응답 없음")

    send_det = args.only in ("all", "detections")
    send_gt = args.only in ("all", "gt")
    detectors = {cam: Detector(model=args.model, conf=args.conf) for cam in CAMERAS} if send_det else {}
    mode = "dry-run" if args.dry_run else args.server
    print(f"session_id: {session_id} | 프레임 {len(rows)}개 | 보낼 것: {args.only} | {mode}")

    stats = {"pairs": 0, "skipped": 0, "removed": 0, "empty": 0, "gt": 0}
    t0 = time.perf_counter()
    for row in rows:
        frame, ts = int(row["frame"]), int(row["ts"])

        if send_gt:
            client.send(build_ground_truth(session_id, row), path="/ground-truth")
            stats["gt"] += 1

        if not send_det:
            continue
        # 두 카메라 이미지 읽기: 하나라도 없거나 깨지면 이 묶음은 추론 실패 → 보내지 않음
        images = {cam: cv2.imread(str(folder / cam / f"{frame:06d}.jpg")) for cam in CAMERAS}
        if any(img is None for img in images.values()):
            stats["skipped"] += 1
            print(f"  [건너뜀] frame {frame}: 이미지 없음 또는 손상")
            continue
        try:
            frames = []
            for cam in CAMERAS:
                img = images[cam]
                h, w = img.shape[:2]
                dets, removed = clean_detections(detectors[cam](img), w, h)
                stats["removed"] += removed
                frames.append({"camera_id": cam, "frame_id": frame, "ts": ts,
                               "image_size": [w, h], "detections": dets})
                if vis_dir and frame % args.save_every == 0:
                    cv2.imwrite(str(vis_dir / f"{frame:06d}_{cam}.jpg"), draw(img.copy(), dets))
        except Exception as e:  # 모델 오류도 추론 실패로 보고 보내지 않음
            stats["skipped"] += 1
            print(f"  [건너뜀] frame {frame}: 추론 오류 {e}")
            continue

        if not any(f["detections"] for f in frames):
            stats["empty"] += 1
        client.send({"session_id": session_id, "pair_id": frame, "frames": frames}, path="/detections")
        stats["pairs"] += 1
        if stats["pairs"] % 50 == 0:
            print(f"  {stats['pairs']}묶음 처리 ({stats['pairs'] / (time.perf_counter() - t0):.1f} 묶음/초)")

    client.close()
    print(f"\n완료 | 탐지 묶음 {stats['pairs']} (탐지 0개 {stats['empty']}) | 건너뜀 {stats['skipped']} | "
          f"뺀 탐지 {stats['removed']} | 정답 {stats['gt']}")
    print(client.summary())
    print(f"결과: {out_dir}")


if __name__ == "__main__":
    main()