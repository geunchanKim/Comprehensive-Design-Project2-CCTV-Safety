"""
탐지 결과 원본 저장 (원인 분석용)

여러 모델 × 입력 크기 조합으로 Unity 장면 이미지에 탐지를 돌리고,
낮은 conf(기본 0.05)로 나온 박스를 "모든 클래스" 그대로 저장한다.
conf 기준·클래스 조합·잘림 여부별 분석은 저장된 파일로 나중에 한다 (다시 돌릴 필요 없음).

  - 추적 없이 모델 출력만 저장 (추적기는 원인이 아님을 확인함)
  - coco 모델은 80개 클래스 전부 저장 → 책상이 'dining table' 등으로 잡히는지 확인용

저장: runs/eval/dumps/<모델>_<입력크기>.jsonl.gz
  한 줄 = 한 이미지 {"scene", "frame", "camera", "boxes": [[클래스, conf, x1, y1, x2, y2], ...]}

실행 (ai/ 폴더에서, 전체 약 10분)
  python eval/dump_detections.py
  python eval/dump_detections.py --models v2,coco --imgsz 640           # 일부만
  python eval/dump_detections.py --models coco_s --imgsz 640            # COCO 조금 큰 모델(yolo11s, 자동 다운로드)
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
from detector import WEIGHTS, get_device  # noqa: E402

MODELS = {
    "v2": WEIGHTS["v2"],
    "v1": WEIGHTS["v1"],
    "coco": "yolo11n.pt",
    "coco_s": "yolo11s.pt",
}
SCENES = ["unity-classroom-03-s1", "unity-classroom-03-s2", "unity-classroom-03-s3"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="v2,v1,coco", help=f"쉼표로 구분: {','.join(MODELS)}")
    parser.add_argument("--imgsz", default="640,1280", help="쉼표로 구분")
    parser.add_argument("--scenes", default=",".join(SCENES))
    parser.add_argument("--conf", type=float, default=0.05)
    args = parser.parse_args()

    device = get_device()
    out_dir = AI_DIR / "runs" / "eval" / "dumps"
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [AI_DIR / "runs" / "unity" / s for s in args.scenes.split(",")]
    for s in scenes:
        if not (s / "frames.jsonl").exists():
            raise SystemExit(f"장면이 없어요: {s}")

    for name in args.models.split(","):
        model = YOLO(str(MODELS[name]))
        names = model.names
        for imgsz in map(int, args.imgsz.split(",")):
            out = out_dir / f"{name}_{imgsz}.jsonl.gz"
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
                            boxes = [[names[int(c)], round(float(p), 3), *[round(v, 1) for v in xyxy]]
                                     for c, p, xyxy in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]
                            f.write(json.dumps({"scene": scene.name, "frame": frame, "camera": cam, "boxes": boxes}) + "\n")
                            n += 1
            print(f"{name} {imgsz}: 이미지 {n}장, {n / (time.perf_counter() - t0):.1f} 장/초 → {out.name}")
    print(f"\n완료: {out_dir}")


if __name__ == "__main__":
    main()
