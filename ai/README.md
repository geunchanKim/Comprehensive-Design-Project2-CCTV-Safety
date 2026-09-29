# AI 탐지 모델 트랙

YOLO 기반 객체 탐지 모델 학습 관련 코드.

## 폴더 구조

```
ai/
├── datasets/
│   ├── raw/       # Roboflow 원본 데이터셋 (직접 다운로드 필요, git 미추적)
│   └── merged/    # 병합된 최종 데이터셋 (스크립트로 자동 생성, git 미추적)
├── scripts/
│   └── merge_datasets.py
├── configs/
│   └── data.yaml  # 병합 시 자동 생성됨
├── train.py
└── requirements.txt
```

## 데이터셋 준비

아래 Roboflow 데이터셋을 각각 YOLOv11 포맷으로 다운로드해서, `datasets/raw/` 아래 폴더명에 맞게 압축 해제하세요.

| 클래스 | 출처 | 저장 경로 |
|---|---|---|
| cart | https://universe.roboflow.com/furkan-bakkal/shopping-cart-1r48s | `datasets/raw/cart/` |
| desk | https://universe.roboflow.com/talovpracticas/desk-r0my2 | `datasets/raw/desk/` |

각 폴더 안에는 Roboflow가 압축 해제 시 만들어주는 `train/`, `valid/`, `test/` 구조가 그대로 있어야 합니다.

## 실행 순서

```bash
pip install -r requirements.txt

# 1. 데이터셋 병합
python scripts/merge_datasets.py

# 2. 학습 실행
python train.py
```

학습 결과는 `runs/train_v1/` 아래에 저장됩니다 (git 미추적).

## 새 클래스 추가하는 법

`scripts/merge_datasets.py`의 `DATASETS` 리스트에 `(폴더명, 클래스명)` 한 줄만 추가하면 됩니다.