"""
포즈(키포인트) 탐지 결과 원본 저장 (발목 방식 검증용)

YOLO 포즈 모델로 Unity 장면 이미지에서 사람 박스와 17개 관절(COCO 키포인트)을 찾아 저장한다.
발목(15: 왼쪽, 16: 오른쪽)이 Unity 정답 발목과 얼마나 맞는지, 발목으로 삼각측량하면
위치 오차가 얼마나 줄어드는지는 저장된 파일로 분석한다.

저장: runs/eval/dumps/pose_<모델>_<입력크기>.jsonl.gz
  한 줄 = 한 이미지 {"scene", "frame", "camera",
                    "people": [[conf, x1, y1, x2, y2, [[kx, ky, kconf] × 17]], ...]}

실행 (ai/ 폴더에서, 약 2~3분. 모델은 처음에 자동 다운로드)
  python eval/dump_pose.py
  python eval/dump_pose.py --models yolo11s-pose --imgsz 640
"""

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR / "edge"))
from detector import get_device  # noqa: E402

SCENES = ["unity-classroom-03-s1", "unity-classroom-03-s2", "unity-classroom-03-s3"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="yolo11n-pose", help="쉼표로 구분 (예: yolo11n-pose,yolo11s-pose)")
    parser.add_argument("--imgsz", default="640,1280", help="쉼표로 구분")
    parser.add_argument("--scenes", default=",".join(SCENES))
    parser.add_argument("--conf", type=float, default=0.1)
    args = parser.parse_args()

    device = get_device()
    out_dir = AI_DIR / "runs" / "eval" / "dumps"
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [AI_DIR / "runs" / "unity" / s for s in args.scenes.split(",")]

    for name in args.models.split(","):
        model = YOLO(f"{name}.pt")
        for imgsz in map(int, args.imgsz.split(",")):
            out = out_dir / f"pose_{name}_{imgsz}.jsonl.gz"
            n, t0 = 0, time.perf_counter()
            with gzip.open(out, "wt", encoding="utf-8") as f:
                for scene in scenes:
                    frames = [json.loads(l)["frame"] for l in (scene / "frames.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
                    for frame in frames:
                        for cam in ("cam1", "cam2"):
                            img = cv2.imread(str(scene / cam / f"{frame:06d}.jpg"))
                            if img is None:
                                continue
                            r = model.predict(img, conf=args.conf, imgsz=imgsz, device=device, verbose=False)[0]
                            people = []
                            if r.keypoints is not None and len(r.boxes):
                                kxy = r.keypoints.xy.tolist()
                                kcf = r.keypoints.conf.tolist() if r.keypoints.conf is not None else [[1.0] * 17] * len(kxy)
                                for p, box, pts, cfs in zip(r.boxes.conf.tolist(), r.boxes.xyxy.tolist(), kxy, kcf):
                                    kps = [[round(x, 1), round(y, 1), round(c, 3)] for (x, y), c in zip(pts, cfs)]
                                    people.append([round(p, 3), *[round(v, 1) for v in box], kps])
                            f.write(json.dumps({"scene": scene.name, "frame": frame, "camera": cam, "people": people}) + "\n")
                            n += 1
            print(f"{name} {imgsz}: 이미지 {n}장, {n / (time.perf_counter() - t0):.1f} 장/초 → {out.name}")
    print(f"\n완료: {out_dir}")


if __name__ == "__main__":
    main()
