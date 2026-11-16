"""
사람 영역 보호구 모델 학습 (안전모·안전조끼 착용/미착용 4종 탐지)

먼저 ppe/build_crops.py 로 사람 영역 데이터셋을 만든다.
중단된 적이 있으면 이어서, 처음이면 COCO 사전학습 yolo11n 에서 시작한다.

사용 예:
    python ppe/train_ppe.py ~/datasets/ppe-crops-v1/data.yaml            # runs/ppe_v1
    python ppe/train_ppe.py ~/datasets/ppe-crops-v1/data.yaml --name ppe_v1_640 --imgsz 640

입력 크기 기본값 320: 잘라 낸 사람 영역은 작고(원본 사람 높이 수백 px), 엣지에서 사람 수만큼
돌려야 하므로 작게 시작한다. 안전모가 작아서 놓치면 --imgsz 를 키워 비교한다.
"""

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO

AI_DIR = Path(__file__).resolve().parents[1]


def get_device() -> str:
    if torch.cuda.is_available():
        return "0"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main(data: Path, name: str, imgsz: int, epochs: int, model: str) -> None:
    if not data.exists():
        raise FileNotFoundError(f"{data} 이(가) 없습니다. 먼저 ppe/build_crops.py 를 실행하세요.")
    last = AI_DIR / "runs" / name / "weights" / "last.pt"
    device = get_device()
    print(f"데이터: {data} | 결과: runs/{name} | 입력 {imgsz} | 장치 {device}")

    if last.exists():
        print(f"이전 체크포인트 발견 → 이어서 학습: {last}")
        YOLO(str(last)).train(resume=True)
        return

    YOLO(model).train(
        data=str(data),
        epochs=epochs,
        patience=20,
        imgsz=imgsz,
        batch=32,
        device=device,
        close_mosaic=15,  # 엣지에서는 사람 영역 하나씩 넣으므로 마지막에는 섞지 않고 학습
        project=str(AI_DIR / "runs"),
        name=name,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path, help="build_crops.py 가 만든 data.yaml")
    parser.add_argument("--name", default="ppe_v1")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--model", default="yolo11n.pt", help="시작 가중치 (yolo11s.pt 로 키워 비교 가능)")
    args = parser.parse_args()
    main(args.data.expanduser(), args.name, args.imgsz, args.epochs, args.model)
