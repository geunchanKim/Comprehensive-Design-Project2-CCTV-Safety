"""
엣지 탐지기: 영상 프레임에서 4클래스(person, chair, cart, desk)를 탐지·추적한다.

모델 선택 (--model)
  v2       (기본) 4클래스 단일 모델: runs/train_v2/weights/best.pt
  ensemble 두 모델 조합: COCO 원본(yolo11n.pt) → person, chair / v1 → cart, desk
           v2에서 의자 탐지가 약할 때 쓰는 대안

탐지 결과는 서버와 약속한 형식 {track_id, cls, conf, bbox:[x1,y1,x2,y2](픽셀)} 로 만든다.

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

CLASSES = ("person", "chair", "cart", "desk")
# ensemble 모드에서 두 모델이 각자 추적기를 가지므로 track_id가 겹치지 않게 v1 쪽에 더해주는 값
TRACK_ID_OFFSET = 10000
COLORS = {"person": (0, 200, 0), "chair": (220, 0, 220), "cart": (0, 165, 255), "desk": (255, 120, 0)}


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
    """frame(BGR 이미지) → [{track_id, cls, conf, bbox}] 리스트"""

    def __init__(self, model: str = "v2", conf: float = 0.4, device: str | None = None,
                 tracker: str = "bytetrack.yaml"):
        self.conf = conf
        self.device = device or get_device()
        self.tracker = tracker
        if model == "v2":
            self.models = [load_model(WEIGHTS["v2"], set(CLASSES), 0)]
        elif model == "ensemble":
            self.models = [load_model(WEIGHTS["coco"], {"person", "chair"}, 0),
                           load_model(WEIGHTS["v1"], {"cart", "desk"}, TRACK_ID_OFFSET)]
        else:
            raise ValueError(f"model은 v2 또는 ensemble 이어야 해요: {model}")
        self.model_name = model

    def __call__(self, frame, track: bool = True) -> list[dict]:
        detections = []
        for model, class_map, offset in self.models:
            kwargs = dict(conf=self.conf, classes=list(class_map), device=self.device, verbose=False)
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
                detections.append({
                    "track_id": None if tid is None else tid + offset,
                    "cls": class_map[cls_idx],
                    "conf": round(conf, 3),
                    "bbox": [round(v, 1) for v in xyxy],
                })
        return detections


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
        # 좌표 계산에 쓸 발 위치(bbox 하단 중심)
        cv2.circle(frame, ((x1 + x2) // 2, y2), 4, color, -1)
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
    parser.add_argument("--model", choices=["v2", "ensemble"], default="v2")
    parser.add_argument("--session", default="local-test", help="session_id")
    parser.add_argument("--camera", default="cam1", help="camera_id")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--fps", type=float, default=10, help="초당 처리할 프레임 수 (나머지는 건너뜀)")
    parser.add_argument("--max-frames", type=int, default=0, help="처리할 최대 프레임 수 (0 = 끝까지)")
    parser.add_argument("--save", action="store_true", help="결과 영상(mp4) + 메시지(jsonl) 저장")
    parser.add_argument("--show", action="store_true", help="화면에 결과 표시 (q로 종료)")
    parser.add_argument("--no-track", action="store_true", help="추적 없이 탐지만")
    args = parser.parse_args()

    detector = Detector(model=args.model, conf=args.conf)
    print(f"모델: {detector.model_name} | 장치: {detector.device} | 클래스: {', '.join(CLASSES)}")

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
    counts = {c: 0 for c in CLASSES}
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