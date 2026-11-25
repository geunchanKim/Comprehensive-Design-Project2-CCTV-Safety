from ultralytics import YOLO
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent  # ai/scripts/ -> ai/
MODEL_PATH = BASE_DIR / "runs" / "train_v1" / "weights" / "best.pt"
model = YOLO(str(MODEL_PATH))
metrics = model.val(project=str(BASE_DIR / "runs"), name="val_v1", exist_ok=True)
print(metrics.box.map50)      # 전체 평균
print(metrics.box.maps)       # 클래스별 개별 mAP50-95