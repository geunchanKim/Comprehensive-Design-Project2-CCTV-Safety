"""
병합된 데이터셋으로 YOLO 모델을 학습.

사용 예:
    python train.py
"""

from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
DATA_YAML = BASE_DIR / "configs" / "data.yaml"


def main() -> None:
    if not DATA_YAML.exists():
        raise FileNotFoundError(
            f"{DATA_YAML} 이(가) 없습니다. 먼저 scripts/merge_datasets.py를 실행하세요."
        )

    model = YOLO("yolo11n.pt")  # nano — 빠른 검증용. 정확도 필요하면 yolo11s.pt로 교체

    model.train(
        data=str(DATA_YAML),
        epochs=50,
        imgsz=640,
        project=str(BASE_DIR / "runs"),
        name="train_v1",
    )


if __name__ == "__main__":
    main()