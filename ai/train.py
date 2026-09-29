"""
병합된 데이터셋으로 YOLO 모델을 학습.
중단된 적이 있으면 이어서, 처음이면 새로 시작.

사용 예:
    python train.py
"""

from pathlib import Path
import torch
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
DATA_YAML = BASE_DIR / "configs" / "data.yaml"
LAST_CHECKPOINT = BASE_DIR / "runs" / "train_v1" / "weights" / "last.pt"


def get_device() -> str:
    if torch.cuda.is_available():
        return "0"  # NVIDIA GPU
    if torch.backends.mps.is_available():
        return "mps"  # Apple Silicon GPU
    return "cpu"


def main() -> None:
    if not DATA_YAML.exists():
        raise FileNotFoundError(
            f"{DATA_YAML} 이(가) 없습니다. 먼저 scripts/merge_datasets.py를 실행하세요."
        )

    device = get_device()
    print(f"학습 장치: {device}")

    if LAST_CHECKPOINT.exists():
        print(f"이전 체크포인트 발견 → 이어서 학습: {LAST_CHECKPOINT}")
        model = YOLO(str(LAST_CHECKPOINT))
        model.train(resume=True)
        return

    model = YOLO("yolo11n.pt")  # nano — 빠른 검증용. 정확도 필요하면 yolo11s.pt로 교체
    model.train(
        data=str(DATA_YAML),
        epochs=100,
        patience=15,
        imgsz=640,
        device=device,
        project=str(BASE_DIR / "runs"),
        name="train_v1",
    )


if __name__ == "__main__":
    main()