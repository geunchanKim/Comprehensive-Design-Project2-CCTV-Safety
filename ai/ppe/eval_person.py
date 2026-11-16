"""
사람별 보호구 판별 정확도 (사람 영역 하나 = 한 명)

build_crops.py 의 person_truth.jsonl 정답과, 모델 탐지를 decide_state 로 바꾼 결과를 비교한다.
정답이 unknown 인 사람은 채점에서 빼고, 모델이 unknown 이면 "판별 못 함"으로 따로 센다.

사용 예:
    python ppe/eval_person.py runs/ppe_v1/weights/best.pt ~/datasets/ppe-crops-v1
    python ppe/eval_person.py runs/ppe_v1/weights/best.pt ~/datasets/ppe-crops-v1 --conf-min 0.5 --out runs/ppe_v1/person_eval.json
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import torch
from ultralytics import YOLO

from ppe_common import ITEMS, decide_state

STATES = ("wearing", "not_wearing", "unknown")


def device() -> str:
    if torch.cuda.is_available():
        return "0"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def evaluate(weights: Path, dataset: Path, split: str, imgsz: int, conf_min: float):
    model = YOLO(str(weights))
    rows = [json.loads(line) for line in (dataset / "person_truth.jsonl").open()]
    rows = [r for r in rows if r["split"] == split]
    confusion = {item: Counter() for item in ITEMS}
    times = []
    dev = device()
    for row in rows:
        start = time.perf_counter()
        result = model.predict(str(dataset / "images" / split / f"{row['crop']}.jpg"), imgsz=imgsz,
                               conf=0.1, device=dev, verbose=False)[0]
        times.append((time.perf_counter() - start) * 1000)
        detections = [(int(c), float(p), *map(float, b))
                      for c, p, b in zip(result.boxes.cls, result.boxes.conf, result.boxes.xywhn)]
        predicted = decide_state(detections, conf_min)
        for item in ITEMS:
            confusion[item][(row[item], predicted[item]["status"])] += 1

    report = {"weights": str(weights), "split": split, "people": len(rows), "imgsz": imgsz, "conf_min": conf_min,
              "ms_per_person_p50": round(sorted(times)[len(times) // 2], 1) if times else None, "items": {}}
    for item, counts in confusion.items():
        scored = sum(n for (truth, _), n in counts.items() if truth != "unknown")
        decided = sum(n for (truth, pred), n in counts.items() if truth != "unknown" and pred != "unknown")
        correct = sum(n for (truth, pred), n in counts.items() if truth != "unknown" and truth == pred)
        missed_violation = counts[("not_wearing", "wearing")]
        report["items"][item] = {
            "scored_people": scored,
            "accuracy": round(correct / scored, 4) if scored else None,              # unknown 예측은 틀린 것으로
            "accuracy_when_decided": round(correct / decided, 4) if decided else None,
            "unknown_rate": round(1 - decided / scored, 4) if scored else None,
            "missed_violation": missed_violation,  # 안 썼는데 썼다고 함 (가장 위험한 오류)
            "confusion": {f"{t}->{p}": counts[(t, p)] for t in STATES for p in STATES},
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("weights", type=Path)
    parser.add_argument("dataset", type=Path, help="build_crops.py 결과 폴더")
    parser.add_argument("--split", default="val")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf-min", type=float, default=0.4)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = evaluate(args.weights, args.dataset.expanduser(), args.split, args.imgsz, args.conf_min)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
