"""
병합된 데이터셋으로 YOLO 모델을 학습.
중단된 적이 있으면 이어서, 처음이면 새로 시작.

버전
    v1: cart, desk               (configs/data.yaml    -> runs/train_v1)
    v2: cart, desk, person, chair (configs/data_v2.yaml -> runs/train_v2)

사용 예:
    python train.py              # 기본값 v2
    python train.py --version v1
"""

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent

# 버전별 데이터 설정 파일과, 그 데이터를 만드는 스크립트 안내
VERSIONS = {
    "v1": {"data": "data.yaml", "prepare": "scripts/merge_datasets.py"},
    "v2": {"data": "data_v2.yaml", "prepare": "scripts/pseudo_label_coco.py → scripts/add_coco_subset.py"},
}


def get_device() -> str:
    if torch.cuda.is_available():
        return "0"  # NVIDIA GPU
    if torch.backends.mps.is_available():
        return "mps"  # Apple Silicon GPU
    return "cpu"


def main(version: str) -> None:
    cfg = VERSIONS[version]
    data_yaml = BASE_DIR / "configs" / cfg["data"]
    run_name = f"train_{version}"
    last_checkpoint = BASE_DIR / "runs" / run_name / "weights" / "last.pt"

    if not data_yaml.exists():
        raise FileNotFoundError(f"{data_yaml} 이(가) 없습니다. 먼저 {cfg['prepare']} 를 실행하세요.")

    device = get_device()
    print(f"학습 버전: {version} | 데이터: {data_yaml.name} | 결과: runs/{run_name}")
    print(f"학습 장치: {device}")

    if last_checkpoint.exists():
        print(f"이전 체크포인트 발견 → 이어서 학습: {last_checkpoint}")
        model = YOLO(str(last_checkpoint))
        model.train(resume=True)
        return

    # 항상 COCO 사전학습 가중치에서 시작 (v2는 COCO의 person/chair 인식력을 이어받기 위해 필수)
    model = YOLO("yolo11n.pt")  # nano — 빠른 검증용. 정확도 필요하면 yolo11s.pt로 교체
    model.train(
        data=str(data_yaml),
        epochs=100,
        patience=15,
        imgsz=640,
        device=device,
        project=str(BASE_DIR / "runs"),
        name=run_name,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=VERSIONS.keys(), default="v2")
    args = parser.parse_args()
    main(args.version)