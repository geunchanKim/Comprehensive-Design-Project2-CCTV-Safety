"""
엣지 탐지기: 영상 프레임에서 물체를 탐지·추적하고, 좌표 계산에 쓸 발 위치(foot)를 붙인다.

모델 선택 (--model)
  coco     (기본) COCO 원본(yolo11n.pt). person, chair, suitcase, backpack 탐지 가능
           Unity S1~S3 측정: 사람 97%(v2 66%), 의자 84%(v2 46%), 오탐도 적음
  v2       우리가 학습한 4클래스 모델(person, chair, cart, desk): runs/train_v2/weights/best.pt
  ensemble COCO 원본 → person, chair / v1 → cart, desk

보낼 클래스 (--classes person,chair)
  모델이 찾을 수 있는 클래스 중 실제로 내보낼 것만 고른다.
  coco 기본값은 person, chair (suitcase, backpack은 서버가 지원한 뒤 켠다)

클래스별 conf (--class-conf person=0.5,chair=0.4)
  클래스마다 다른 기준을 쓴다. 없는 클래스는 --conf 를 쓴다.
  coco 기본값: person 0.5, chair 0.4 (Unity 측정에서 탐지율·오탐 균형이 가장 좋았던 값)

발 위치 (--foot box|ankle)
  box   (기본) 박스 아래 가운데 ((x1+x2)/2, y2)
  ankle 사람은 포즈 모델(yolo11n-pose)로 찾은 두 발목의 가운데. 발목이 안 보이면 box로 대신함
        사람이 아닌 물체는 항상 box
        Unity S1~S3 측정: 위치 오차 15.8cm(box) → 5.8cm(ankle)

탐지 결과 형식 {track_id, cls, conf, bbox:[x1,y1,x2,y2], foot:[x,y], foot_src:"box"|"ankle"} (픽셀)

실행 (ai/ 폴더에서)
  python edge/detector.py --source 0 --show                     # 웹캠
  python edge/detector.py --source video.mp4 --save              # 영상 → 결과 영상 + JSONL
  python edge/detector.py --source 0 --show --model ensemble     # 두 모델 조합으로
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

AI_DIR = Path(__file__).resolve().parent.parent           # ai/
WEIGHTS = {
    "v2": AI_DIR / "runs" / "train_v2" / "weights" / "best.pt",
    "v1": AI_DIR / "runs" / "train_v1" / "weights" / "best.pt",
    "coco": "yolo11n.pt",                                # 없으면 자동 다운로드
}
OUT_DIR = AI_DIR / "runs" / "edge"

CLASSES = ("person", "chair", "cart", "desk")          # v2 모델 클래스
COCO_CLASSES = ("person", "chair", "suitcase", "backpack")  # coco 모델에서 쓸 수 있는 클래스
DEFAULT_CLASSES = {"coco": ("person", "chair"), "v2": CLASSES, "ensemble": CLASSES}
DEFAULT_CLASS_CONF = {"coco": {"person": 0.5, "chair": 0.4, "suitcase": 0.4, "backpack": 0.4}}
POSE_WEIGHTS = "yolo11n-pose.pt"                       # 없으면 자동 다운로드
LEFT_ANKLE, RIGHT_ANKLE = 15, 16                       # COCO 키포인트 번호


def parse_class_conf(text: str | None) -> dict:
    """'person=0.5,chair=0.4' → {'person': 0.5, 'chair': 0.4}"""
    if not text:
        return {}
    return {k.strip(): float(v) for k, v in (item.split("=") for item in text.split(","))}


def parse_classes(text: str | None) -> tuple | None:
    """'person,chair' → ('person', 'chair'), 없으면 None (모델 기본값)"""
    return tuple(c.strip() for c in text.split(",") if c.strip()) if text else None


def box_foot(bbox) -> list:
    """박스 아래 가운데"""
    x1, _, x2, y2 = bbox
    return [round((x1 + x2) / 2, 1), round(y2, 1)]


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def attach_feet(detections: list[dict], people: list[tuple], ankle_conf: float = 0.5, min_iou: float = 0.5):
    """탐지마다 foot, foot_src를 붙인다.
    people: 포즈 모델 결과 [(박스, [(x, y, conf) × 17]), ...]
    사람 탐지는 박스가 가장 많이 겹치는 포즈 결과(IoU ≥ min_iou)를 찾아,
    두 발목 신뢰도가 모두 ankle_conf 이상이면 두 발목 가운데, 아니면 박스 아래 가운데."""
    for d in detections:
        d["foot"], d["foot_src"] = box_foot(d["bbox"]), "box"
        if d["cls"] != "person" or not people:
            continue
        score, best = max(((iou(d["bbox"], box), kps) for box, kps in people), key=lambda t: t[0])
        if score < min_iou:
            continue
        left, right = best[LEFT_ANKLE], best[RIGHT_ANKLE]
        if left[2] >= ankle_conf and right[2] >= ankle_conf:
            d["foot"] = [round((left[0] + right[0]) / 2, 1), round((left[1] + right[1]) / 2, 1)]
            d["foot_src"] = "ankle"
    return detections
# ensemble 모드에서 두 모델이 각자 추적기를 가지므로 track_id가 겹치지 않게 v1 쪽에 더해주는 값
TRACK_ID_OFFSET = 10000
COLORS = {"person": (0, 200, 0), "chair": (220, 0, 220), "cart": (0, 165, 255), "desk": (255, 120, 0),
          "suitcase": (0, 200, 255), "backpack": (255, 200, 0)}


def get_device() -> str:
    if torch.cuda.is_available():
        return "0"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_model(weights, wanted: set, offset: int):
    """모델을 불러오고, 우리가 쓸 클래스만 골라 {모델 class id: 공통 이름} 표를 만든다"""
    if isinstance(weights, Path) and not weights.exists():
        raise FileNotFoundError(f"가중치 파일이 없어요: {weights}")
    model = YOLO(str(weights))
    class_map = {i: n for i, n in model.names.items() if n in wanted}
    missing = wanted - set(class_map.values())
    if missing:
        raise ValueError(f"{weights}에 {missing} 클래스가 없어요. 모델 클래스: {list(model.names.values())}")
    return model, class_map, offset


class Detector:
    """frame(BGR 이미지) → [{track_id, cls, conf, bbox, foot, foot_src}] 리스트"""

    def __init__(self, model: str = "coco", conf: float = 0.4, device: str | None = None,
                 tracker: str = "bytetrack.yaml", imgsz: int = 640, class_conf: dict | None = None,
                 classes: tuple | None = None, foot: str = "box", ankle_conf: float = 0.5):
        if foot not in ("box", "ankle"):
            raise ValueError(f"foot은 box 또는 ankle 이어야 해요: {foot}")
        self.conf = conf
        self.classes = tuple(classes or DEFAULT_CLASSES.get(model, CLASSES))
        self.foot = foot
        self.ankle_conf = ankle_conf
        # 클래스별 기준: 직접 준 값 > 모델 기본값 > conf
        self.class_conf = {**DEFAULT_CLASS_CONF.get(model, {}), **(class_conf or {})}
        self.imgsz = imgsz          # 모델 입력 크기. 1920 이미지를 이 크기로 줄여서 본다 (크면 작은 물체에 유리, 느림)
        self.device = device or get_device()
        self.tracker = tracker
        wanted = set(self.classes)
        if model == "v2":
            self._check_classes(wanted, CLASSES, model)
            self.models = [load_model(WEIGHTS["v2"], wanted, 0)]
        elif model == "coco":
            self._check_classes(wanted, COCO_CLASSES, model)
            self.models = [load_model(WEIGHTS["coco"], wanted, 0)]
        elif model == "ensemble":
            self._check_classes(wanted, CLASSES, model)
            self.models = [m for m in (
                load_model(WEIGHTS["coco"], wanted & {"person", "chair"}, 0) if wanted & {"person", "chair"} else None,
                load_model(WEIGHTS["v1"], wanted & {"cart", "desk"}, TRACK_ID_OFFSET) if wanted & {"cart", "desk"} else None,
            ) if m]
        else:
            raise ValueError(f"model은 coco, v2, ensemble 중 하나여야 해요: {model}")
        self.model_name = model
        # 발목 방식이면 포즈 모델을 하나 더 쓴다 (사람 박스와 짝지어 발목만 가져옴)
        self.pose = YOLO(POSE_WEIGHTS) if foot == "ankle" else None

    @staticmethod
    def _check_classes(wanted: set, available: tuple, model: str):
        extra = wanted - set(available)
        if extra:
            raise ValueError(f"{model} 모델은 {extra} 클래스를 찾을 수 없어요. 가능: {', '.join(available)}")

    def _pose_people(self, frame) -> list[tuple]:
        """포즈 모델 → [(박스, [(x, y, conf) × 17]), ...]"""
        r = self.pose.predict(frame, conf=0.25, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        if r.keypoints is None or r.boxes is None or len(r.boxes) == 0:
            return []
        xy = r.keypoints.xy.tolist()
        cf = r.keypoints.conf.tolist() if r.keypoints.conf is not None else [[1.0] * len(p) for p in xy]
        return [(box, [(x, y, c) for (x, y), c in zip(pts, cs)])
                for box, pts, cs in zip(r.boxes.xyxy.tolist(), xy, cf)]

    def __call__(self, frame, track: bool = True) -> list[dict]:
        detections = []
        for model, class_map, offset in self.models:
            min_conf = min([self.conf, *self.class_conf.values()])      # 모델에는 가장 낮은 기준으로 묻고, 아래에서 클래스별로 거른다
            kwargs = dict(conf=min_conf, classes=list(class_map), device=self.device, imgsz=self.imgsz, verbose=False)
            if track:
                result = model.track(frame, persist=True, tracker=self.tracker, **kwargs)[0]
            else:
                result = model.predict(frame, **kwargs)[0]

            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
            for cls_idx, conf, xyxy, tid in zip(boxes.cls.int().tolist(), boxes.conf.tolist(),
                                                boxes.xyxy.tolist(), ids):
                if conf < self.class_conf.get(class_map[cls_idx], self.conf):
                    continue
                detections.append({
                    "track_id": None if tid is None else tid + offset,
                    "cls": class_map[cls_idx],
                    "conf": round(conf, 3),
                    "bbox": [round(v, 1) for v in xyxy],
                })
        people = self._pose_people(frame) if self.pose and any(d["cls"] == "person" for d in detections) else []
        return attach_feet(detections, people, self.ankle_conf)


def build_message(session_id: str, camera_id: str, frame_id: int, ts: int, frame, detections: list[dict]) -> dict:
    """카메라 한 대의 한 프레임 결과 (묶음 메시지의 frames 안에 들어가는 단위)"""
    h, w = frame.shape[:2]
    return {
        "session_id": session_id,
        "camera_id": camera_id,
        "frame_id": frame_id,
        "ts": ts,
        "image_size": [w, h],
        "detections": detections,
    }


def draw(frame, detections: list[dict]):
    for d in detections:
        x1, y1, x2, y2 = map(int, d["bbox"])
        color = COLORS[d["cls"]]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{d['cls']} #{d['track_id']} {d['conf']:.2f}" if d["track_id"] is not None else f"{d['cls']} {d['conf']:.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        # 좌표 계산에 쓸 발 위치 (발목이면 흰 테두리)
        fx, fy = map(int, d.get("foot") or box_foot(d["bbox"]))
        cv2.circle(frame, (fx, fy), 5, color, -1)
        if d.get("foot_src") == "ankle":
            cv2.circle(frame, (fx, fy), 8, (255, 255, 255), 2)
    return frame


def open_source(source: str):
    src = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없어요: {source}")
    is_file = isinstance(src, str) and Path(src).exists()
    return cap, is_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="웹캠 번호, 영상 파일, RTSP 주소")
    parser.add_argument("--model", choices=["coco", "v2", "ensemble"], default="coco")
    parser.add_argument("--classes", default=None, help="보낼 클래스. 예: person,chair (기본: 모델별 기본값)")
    parser.add_argument("--class-conf", default=None, help="클래스별 conf. 예: person=0.5,chair=0.4")
    parser.add_argument("--foot", choices=["box", "ankle"], default="box", help="발 위치: 박스 아래 / 두 발목 가운데")
    parser.add_argument("--session", default="local-test", help="session_id")
    parser.add_argument("--camera", default="cam1", help="camera_id")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--fps", type=float, default=10, help="초당 처리할 프레임 수 (나머지는 건너뜀)")
    parser.add_argument("--max-frames", type=int, default=0, help="처리할 최대 프레임 수 (0 = 끝까지)")
    parser.add_argument("--save", action="store_true", help="결과 영상(mp4) + 메시지(jsonl) 저장")
    parser.add_argument("--show", action="store_true", help="화면에 결과 표시 (q로 종료)")
    parser.add_argument("--no-track", action="store_true", help="추적 없이 탐지만")
    args = parser.parse_args()

    detector = Detector(model=args.model, conf=args.conf, class_conf=parse_class_conf(args.class_conf),
                        classes=parse_classes(args.classes), foot=args.foot)
    print(f"모델: {detector.model_name} | 장치: {detector.device} | 클래스: {', '.join(detector.classes)} | 발 위치: {detector.foot}")

    cap, is_file = open_source(args.source)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(src_fps / args.fps))  # 30fps 영상, 10fps 처리 → 3프레임마다 1번

    out = OUT_DIR / f"{args.session}_{args.camera}"
    writer = jsonl = None
    if args.save:
        out.mkdir(parents=True, exist_ok=True)
        jsonl = open(out / "detections.jsonl", "w", encoding="utf-8")
        print(f"저장 위치: {out}")

    frame_idx = processed = 0
    counts = {c: 0 for c in detector.classes}
    t0 = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            if (frame_idx - 1) % step:
                continue

            # 파일은 영상 안의 시각, 카메라는 실제 수신 시각 (epoch ms)
            ts = int(cap.get(cv2.CAP_PROP_POS_MSEC)) if is_file else int(time.time() * 1000)
            dets = detector(frame, track=not args.no_track)
            msg = build_message(args.session, args.camera, frame_idx, ts, frame, dets)
            processed += 1
            for d in dets:
                counts[d["cls"]] += 1

            if jsonl:
                jsonl.write(json.dumps(msg, ensure_ascii=False) + "\n")
            if args.save or args.show:
                vis = draw(frame.copy(), dets)
                if args.save:
                    if writer is None:
                        h, w = vis.shape[:2]
                        writer = cv2.VideoWriter(str(out / "annotated.mp4"),
                                                 cv2.VideoWriter_fourcc(*"mp4v"), src_fps / step, (w, h))
                    writer.write(vis)
                if args.show:
                    cv2.imshow("detector", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

            if processed % 50 == 0:
                print(f"  {processed}프레임 처리, 평균 {processed / (time.perf_counter() - t0):.1f} fps")
            if args.max_frames and processed >= args.max_frames:
                break
    finally:
        cap.release()
        if writer:
            writer.release()
        if jsonl:
            jsonl.close()
        cv2.destroyAllWindows()

    elapsed = time.perf_counter() - t0
    print(f"\n처리 {processed}프레임, {elapsed:.1f}초 ({processed / max(elapsed, 1e-9):.1f} fps)")
    print("클래스별 탐지 수 (프레임 합계): " + ", ".join(f"{c} {n}" for c, n in counts.items()))


if __name__ == "__main__":
    main()