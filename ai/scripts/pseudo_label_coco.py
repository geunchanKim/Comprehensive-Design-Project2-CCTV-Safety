"""
v2 데이터셋 생성 스크립트

datasets/raw/ 의 원본 데이터셋(cart, desk — train/valid/test 분할 그대로)을 읽어서
1) cart=0, desk=1 로 클래스 id를 다시 매기고
2) 모든 이미지에 COCO 사전학습 모델(yolo11n.pt)로 person, chair를 자동 라벨링(pseudo-labeling)해서
4클래스 데이터셋(datasets/merged_v2)을 만든다.

클래스 id
  0: cart   (raw 원본 라벨)
  1: desk   (raw 원본 라벨)
  2: person (COCO 모델 자동 라벨)
  3: chair  (COCO 모델 자동 라벨)

실행 (ai/ 폴더에서)
  python scripts/pseudo_label_coco.py
  python scripts/pseudo_label_coco.py --conf 0.5 --preview 12
그다음
  python scripts/add_coco_subset.py
"""

import argparse
import random
import shutil
from collections import Counter
from pathlib import Path

import cv2
import torch
import yaml
from ultralytics import YOLO

AI_DIR = Path(__file__).resolve().parent.parent          # ai/
RAW_DIR = AI_DIR / "datasets" / "raw"                    # 원본 (읽기만 함)
DST_DIR = AI_DIR / "datasets" / "merged_v2"              # v2 결과
PREVIEW_DIR = AI_DIR / "datasets" / "merged_v2_preview"  # 눈으로 확인용 이미지
DATA_YAML = AI_DIR / "configs" / "data_v2.yaml"

# (raw 아래 폴더명, 클래스 이름) — 순서대로 0, 1 번 클래스
RAW_DATASETS = [("cart", "cart"), ("desk", "desk")]
NAMES = ["cart", "desk", "person", "chair"]
# COCO 클래스 id -> 새 클래스 id  (COCO: 0=person, 56=chair)
COCO_TO_NEW = {0: 2, 56: 3}

SPLITS = ["train", "valid", "test"]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COLORS = [(0, 200, 255), (255, 150, 0), (0, 220, 0), (220, 0, 220)]


def get_device():
    if torch.cuda.is_available():
        return 0
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def read_raw_labels(label_path: Path, new_id: int, warn: Counter) -> list[str]:
    """raw 라벨을 읽어서 클래스 id를 new_id로 교체 (파일 끝 개행 없어도 OK)"""
    if not label_path.exists():
        warn["라벨 파일 없는 이미지"] += 1
        return []
    lines = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            warn["bbox 형식이 아닌 줄(무시)"] += 1
            continue
        if parts[0] != "0":
            warn[f"원본 class id {parts[0]} 발견(→ {new_id}로 통일)"] += 1
        lines.append(" ".join([str(new_id)] + parts[1:]))
    return lines


def pseudo_labels(model, img_path: Path, conf: float, device) -> list[str]:
    """COCO 모델로 person, chair만 탐지해서 YOLO 라벨 줄로 변환"""
    result = model.predict(
        str(img_path),
        conf=conf,
        classes=list(COCO_TO_NEW.keys()),
        device=device,
        verbose=False,
    )[0]

    lines = []
    for cls, (x, y, w, h) in zip(result.boxes.cls.tolist(), result.boxes.xywhn.tolist()):
        lines.append(f"{COCO_TO_NEW[int(cls)]} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
    return lines


def draw_preview(img_path: Path, lines: list[str], out_path: Path):
    img = cv2.imread(str(img_path))
    if img is None:
        return
    h, w = img.shape[:2]
    for line in lines:
        cls, xc, yc, bw, bh = line.split()
        cls = int(cls)
        xc, yc, bw, bh = float(xc) * w, float(yc) * h, float(bw) * w, float(bh) * h
        x1, y1 = int(xc - bw / 2), int(yc - bh / 2)
        x2, y2 = int(xc + bw / 2), int(yc + bh / 2)
        cv2.rectangle(img, (x1, y1), (x2, y2), COLORS[cls], 2)
        cv2.putText(img, NAMES[cls], (x1, max(y1 - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS[cls], 2)
    cv2.imwrite(str(out_path), img)


def main(conf: float, preview: int):
    for folder, _ in RAW_DATASETS:
        if not (RAW_DIR / folder).exists():
            raise SystemExit(f"원본 데이터셋이 없어요: {RAW_DIR / folder}")

    for d in (DST_DIR, PREVIEW_DIR):
        if d.exists():
            shutil.rmtree(d)

    device = get_device()
    print(f"자동 라벨링 장치: {device}, conf 임계값: {conf}")
    model = YOLO("yolo11n.pt")  # COCO 80클래스 원본 모델

    counter = Counter()
    warn = Counter()
    preview_pool = []  # (이미지 경로, 라벨 줄)
    used_splits = set()

    for new_id, (folder, class_name) in enumerate(RAW_DATASETS):
        for split in SPLITS:
            src_img_dir = RAW_DIR / folder / split / "images"
            src_lbl_dir = RAW_DIR / folder / split / "labels"
            if not src_img_dir.exists():
                print(f"[스킵] {folder}/{split}: images 폴더 없음")
                continue
            used_splits.add(split)

            dst_img_dir = DST_DIR / "images" / split
            dst_lbl_dir = DST_DIR / "labels" / split
            dst_img_dir.mkdir(parents=True, exist_ok=True)
            dst_lbl_dir.mkdir(parents=True, exist_ok=True)

            img_paths = sorted(p for p in src_img_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
            for img_path in img_paths:
                out_name = f"{class_name}_{img_path.name}"   # 데이터셋 간 파일명 충돌 방지
                dst_img = dst_img_dir / out_name
                shutil.copy2(img_path, dst_img)

                base = read_raw_labels(src_lbl_dir / f"{img_path.stem}.txt", new_id, warn)
                extra = pseudo_labels(model, img_path, conf, device)
                lines = base + extra

                (dst_lbl_dir / f"{dst_img.stem}.txt").write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
                )

                for line in lines:
                    counter[(split, NAMES[int(line.split()[0])])] += 1
                if extra:
                    preview_pool.append((dst_img, lines))

            print(f"[완료] {folder}/{split}: {len(img_paths)}장")

    used_splits = [s for s in SPLITS if s in used_splits]

    # data_v2.yaml 생성
    data = {"path": str(DST_DIR), "names": {i: n for i, n in enumerate(NAMES)}}
    data["train"] = "images/train"
    data["val"] = "images/valid" if "valid" in used_splits else "images/train"
    if "test" in used_splits:
        data["test"] = "images/test"
    DATA_YAML.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    print(f"[생성] {DATA_YAML}")

    # 눈으로 확인할 샘플 (자동 라벨이 붙은 이미지 위주)
    if preview and preview_pool:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        random.seed(42)
        for img_path, lines in random.sample(preview_pool, min(preview, len(preview_pool))):
            draw_preview(img_path, lines, PREVIEW_DIR / f"check_{img_path.name}")
        print(f"[미리보기] {PREVIEW_DIR} 에 {min(preview, len(preview_pool))}장 저장")

    if warn:
        print("\n참고")
        for msg, n in warn.items():
            print(f"  {msg}: {n}")

    # 클래스별 박스 개수 요약
    print("\n클래스별 박스 개수")
    print(f"{'split':<7}" + "".join(f"{n:>8}" for n in NAMES))
    for split in used_splits:
        print(f"{split:<7}" + "".join(f"{counter[(split, n)]:>8}" for n in NAMES))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conf", type=float, default=0.5, help="자동 라벨로 인정할 최소 신뢰도")
    parser.add_argument("--preview", type=int, default=12, help="확인용 미리보기 이미지 수 (0이면 생략)")
    args = parser.parse_args()
    main(args.conf, args.preview)