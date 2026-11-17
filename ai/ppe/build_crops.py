"""
Construction-PPE → 사람 영역 보호구 데이터셋 만들기

사람 상자마다 영역을 넓혀 원본 해상도로 자르고, 그 안에 보이는 안전모·조끼 상자를 라벨로 옮긴다.
평가용으로 사람별 정답(안전모·조끼 wearing / not_wearing / unknown)도 함께 저장한다.

사용 예:
    python ppe/build_crops.py ~/datasets/construction-ppe ~/datasets/ppe-crops-v1

결과
    <out>/images/{train,val}/*.jpg   잘라 낸 사람 영역
    <out>/labels/{train,val}/*.txt   보호구 4종 YOLO 라벨 (ppe_common.PPE_NAMES)
    <out>/person_truth.jsonl         사람별 정답 (평가용)
    <out>/data.yaml                  학습 설정 (이 폴더 절대 경로)
    <out>/summary.json               개수 요약
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2

from ppe_common import (PPE_NAMES, SOURCE_PERSON, SOURCE_TO_PPE, crop_labels, expand_box,
                        person_truth, yolo_to_xyxy)

MIN_PERSON_HEIGHT = 48  # 이보다 작은 사람은 보호구가 안 보여서 뺀다 (원본 픽셀)


def read_labels(path, img_w, img_h):
    persons, ppe = [], []
    if not path.exists():
        return persons, ppe
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        cls = int(parts[0])
        box = yolo_to_xyxy(*map(float, parts[1:]), img_w, img_h)
        if cls == SOURCE_PERSON:
            persons.append(box)
        elif cls in SOURCE_TO_PPE:
            ppe.append((SOURCE_TO_PPE[cls], box))
    return persons, ppe


def build(src: Path, out: Path):
    counts = Counter()
    truth_file = (out / "person_truth.jsonl")
    out.mkdir(parents=True, exist_ok=True)
    with truth_file.open("w") as truth_out:
        for split in ("train", "val"):
            (out / "images" / split).mkdir(parents=True, exist_ok=True)
            (out / "labels" / split).mkdir(parents=True, exist_ok=True)
            for image_path in sorted((src / "images" / split).iterdir()):
                image = cv2.imread(str(image_path))
                if image is None:
                    counts["unreadable"] += 1
                    continue
                img_h, img_w = image.shape[:2]
                persons, ppe = read_labels(src / "labels" / split / f"{image_path.stem}.txt", img_w, img_h)
                for index, person in enumerate(persons):
                    if person[3] - person[1] < MIN_PERSON_HEIGHT:
                        counts[f"{split}_small"] += 1
                        continue
                    crop = expand_box(person, img_w, img_h)
                    name = f"{image_path.stem}_p{index:02d}"
                    cv2.imwrite(str(out / "images" / split / f"{name}.jpg"),
                                image[crop[1]:crop[3], crop[0]:crop[2]], [cv2.IMWRITE_JPEG_QUALITY, 95])
                    labels = crop_labels(crop, ppe)
                    (out / "labels" / split / f"{name}.txt").write_text(
                        "".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in labels))
                    truth = person_truth(index, persons, ppe)
                    truth_out.write(json.dumps({"split": split, "crop": name, "source": image_path.name,
                                                "crop_box": crop, **truth}) + "\n")
                    counts[f"{split}_crops"] += 1
                    for c, *_ in labels:
                        counts[f"{split}_{PPE_NAMES[c]}"] += 1
                    for item, state in truth.items():
                        counts[f"{split}_truth_{item}_{state}"] += 1

    (out / "data.yaml").write_text(
        f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n"
        + "".join(f"  {i}: {n}\n" for i, n in enumerate(PPE_NAMES)))
    summary = dict(sorted(counts.items()))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=Path, help="Construction-PPE 폴더 (images/, labels/, data.yaml)")
    parser.add_argument("out", type=Path, help="만들 사람 영역 데이터셋 폴더")
    args = parser.parse_args()
    for key, value in build(args.src.expanduser(), args.out.expanduser()).items():
        print(f"{key}: {value}")
