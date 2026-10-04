"""
여러 개의 YOLO 포맷 데이터셋(단일 클래스씩)을 하나의 다중 클래스 데이터셋으로 병합.

사용 예:
    python merge_datasets.py

전제 조건:
    ai/datasets/raw/ 아래에 각 데이터셋이 Roboflow YOLOv11 포맷으로 압축 해제되어 있어야 함
    (예: ai/datasets/raw/cart/train/images, ai/datasets/raw/cart/train/labels ...)
"""

import os
import shutil
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # ai/
RAW_DIR = BASE_DIR / "datasets" / "raw"
MERGED_DIR = BASE_DIR / "datasets" / "merged"

# (raw 폴더 안 데이터셋 폴더명, 이 데이터셋에 부여할 클래스명)
# 새 데이터셋을 추가하려면 이 리스트에 한 줄만 추가하면 됨
DATASETS = [
    ("cart", "cart"),
    ("desk", "desk"),
]

SPLITS = ["train", "valid", "test"]


def merge_split(split: str, class_names: list[str]) -> None:
    img_out = MERGED_DIR / "images" / split
    label_out = MERGED_DIR / "labels" / split
    img_out.mkdir(parents=True, exist_ok=True)
    label_out.mkdir(parents=True, exist_ok=True)

    for new_class_id, (folder_name, class_name) in enumerate(DATASETS):
        img_src = RAW_DIR / folder_name / split / "images"
        label_src = RAW_DIR / folder_name / split / "labels"

        if not img_src.exists():
            print(f"[스킵] {img_src} 없음 (이 split은 이 데이터셋에 없을 수 있음)")
            continue

        for img_file in img_src.iterdir():
            new_name = f"{class_name}_{img_file.name}"
            shutil.copy(img_file, img_out / new_name)

        for label_file in label_src.iterdir():
            lines = label_file.read_text(encoding="utf-8").strip().splitlines()
            new_lines = []
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split()
                parts[0] = str(new_class_id)  # 원래 class_id(보통 0)를 새 id로 교체
                new_lines.append(" ".join(parts))

            new_name = f"{class_name}_{label_file.name}"
            (label_out / new_name).write_text("\n".join(new_lines), encoding="utf-8")

        print(f"[완료] {split}/{class_name}: {img_src} → {img_out}")


def write_data_yaml(class_names: list[str]) -> None:
    config = {
        "path": str(MERGED_DIR),
        "train": "images/train",
        "val": "images/valid",
        "names": {i: name for i, name in enumerate(class_names)},
    }
    yaml_path = BASE_DIR / "configs" / "data.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)
    print(f"[생성] {yaml_path}")


def main() -> None:
    class_names = [name for _, name in DATASETS]
    print(f"병합할 클래스: {class_names}")

    for split in SPLITS:
        merge_split(split, class_names)

    write_data_yaml(class_names)
    print("데이터셋 병합 완료.")


if __name__ == "__main__":
    main()