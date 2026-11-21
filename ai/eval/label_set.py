"""
실제 영상 탐지 오탐률 측정용 라벨 세트 (사람·의자)

실제 강의실 녹화에는 사람·의자 상자 정답이 없어서 객체 탐지 오탐률을 잴 수 없다.
녹화에서 프레임을 골라 사람이 상자를 직접 확인(라벨링)하고, 그 정답으로 탐지기를 채점한다.
라벨링 규칙·도구: docs/specs/detection-label-set.md

1) make  — 프레임 고르기 + 초안 라벨
   - 녹화 폴더(runs/real/classroom/s*/t*)의 cam1·cam2 프레임을 일정 간격으로 후보로 만들고, 고정 seed로 섞는다
   - 모델 결과로 고르지 않는다 (모델이 잘 되는 장면만 뽑히면 오탐률이 낮게 나온다)
   - 후보를 차례로 넣으며 초안 상자가 사람·의자 각각 --target 개를 넘으면 멈춘다
   - 초안은 COCO yolo11n, conf 0.25 (지우는 게 새로 그리는 것보다 쉬워서 기준을 낮게)
   결과 (<out>/)
     images/*.jpg        고른 프레임 (이름: s10-t1_cam2_000401.jpg)
     labels/*.txt        라벨링할 파일. 처음에는 초안과 같다 → 사람이 고친다 (YOLO 형식)
     labels_pre/*.txt    초안 원본 (고친 양 비교용, 고치지 않는다)
     classes.txt         0 person, 1 chair
     manifest.csv        파일마다 녹화·프레임·카메라·초안 개수

2) score — 고친 라벨로 탐지기 채점
   - 탐지기는 엣지와 같은 모델·입력 크기·클래스별 conf (사람 0.5, 의자 0.4)로 프레임마다 따로 탐지한다
     (골라 낸 프레임은 연속이 아니라 추적을 쓰지 않는다. 엣지가 track_id 없는 상자를 버리는 효과는 빠진다)
   - 같은 클래스끼리 IoU 큰 순서로 1:1 짝짓기, IoU >= 0.5 면 맞음
   - 높이 --min-height(기본 20px) 미만 상자는 정답·탐지 모두 채점에서 뺀다 (너무 작아 라벨 기준이 흔들림)
   - 오탐률 = 정답과 안 맞는 탐지 / 전체 탐지, 검출률 = 맞은 정답 / 전체 정답
   결과: 화면 표 + <out>/score.json, <out>/score_boxes.csv, --vis 면 <out>/vis/ (빨강 오탐, 파랑 놓침, 초록 맞음)

실행 (ai/ 폴더에서)
  python eval/label_set.py make --out ~/datasets/classroom-det-v1
  python eval/label_set.py score ~/datasets/classroom-det-v1 --vis
  python eval/label_set.py sweep ~/datasets/classroom-det-v1 --cls chair --confs 0.4,0.3,0.25
  라벨 고치기: python eval/label_tool.py ~/datasets/classroom-det-v1  (로컬 화면, 확인한 사진을 reviewed.json 에 기록)
"""

import argparse
import csv
import json
import random
import shutil
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR / "edge"))

CLASSES = ("person", "chair")
DEFAULT_ROOT = AI_DIR / "runs" / "real" / "classroom"


# ── 계산 (YOLO 없이, 테스트 대상) ──

def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def to_yolo(box, w, h) -> str:
    x1, y1, x2, y2 = box
    return f"{(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"


def read_yolo(path: Path, w: int, h: int) -> list[tuple]:
    """YOLO 라벨 → [(클래스 이름, (x1, y1, x2, y2) 픽셀)]. 없거나 빈 파일이면 빈 목록 (물체 없는 프레임)"""
    boxes = []
    if not path.exists():
        return boxes
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        c, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:])
        if 0 <= c < len(CLASSES):
            boxes.append((CLASSES[c], ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)))
    return boxes


def match(truth: list[tuple], preds: list[tuple], iou_min: float = 0.5, min_height: float = 20):
    """
    한 프레임 채점. truth: [(클래스, 상자)], preds: [(클래스, conf, 상자)]
    → [(결과 tp|fp|fn, 클래스, 상자, conf, iou, 다른 클래스 정답과 겹침 여부)]
    """
    tall = lambda box: box[3] - box[1] >= min_height
    truth = [t for t in truth if tall(t[1])]
    preds = [p for p in preds if tall(p[2])]
    rows = []
    for cls in CLASSES:
        ts = [t[1] for t in truth if t[0] == cls]
        ps = [p for p in preds if p[0] == cls]
        pairs = sorted(((iou(t, p[2]), i, j) for i, t in enumerate(ts) for j, p in enumerate(ps)), reverse=True)
        used_t, used_p = set(), set()
        for v, i, j in pairs:
            if v < iou_min:
                break
            if i in used_t or j in used_p:
                continue
            used_t.add(i)
            used_p.add(j)
            rows.append(("tp", cls, ps[j][2], ps[j][1], round(v, 3), False))
        others = [t[1] for t in truth if t[0] != cls]
        for j, p in enumerate(ps):
            if j not in used_p:
                confused = any(iou(o, p[2]) >= iou_min for o in others)   # 다른 클래스를 이 클래스로 잘못 봄
                rows.append(("fp", cls, p[2], p[1], None, confused))
        for i, t in enumerate(ts):
            if i not in used_t:
                rows.append(("fn", cls, t, None, None, False))
    return rows


def summarize(rows) -> dict:
    out = {}
    for cls in CLASSES:
        tp = sum(1 for r in rows if r[0] == "tp" and r[1] == cls)
        fp = sum(1 for r in rows if r[0] == "fp" and r[1] == cls)
        fn = sum(1 for r in rows if r[0] == "fn" and r[1] == cls)
        out[cls] = {"truth": tp + fn, "detections": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                    "fp_from_other_class": sum(1 for r in rows if r[0] == "fp" and r[1] == cls and r[5]),
                    "false_positive_rate": round(fp / (tp + fp), 4) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 4) if tp + fn else None}
    return out


# ── make ──

def candidates(root: Path, stride: int, seed: int) -> list[tuple]:
    """(녹화 폴더, 프레임 번호, 카메라) 후보. 녹화마다 stride 간격, 카메라는 번갈아"""
    out = []
    for folder in sorted(p for p in root.glob("s*/t*") if (p / "cam1").is_dir()):
        frames = sorted(int(f.stem) for f in (folder / "cam1").glob("*.jpg"))
        for k, n in enumerate(frames[stride // 2::stride]):
            out.append((folder, n, ("cam1", "cam2")[k % 2]))
    random.Random(seed).shuffle(out)
    return out


def make(root: Path, out: Path, target: int, stride: int, seed: int, max_images: int):
    import cv2
    from ultralytics import YOLO
    from detector import get_device

    if (out / "labels").exists() and any((out / "labels").iterdir()):
        raise SystemExit(f"이미 라벨 폴더가 있어요: {out / 'labels'}\n  고친 라벨을 덮어쓰지 않으려고 멈춰요")
    for sub in ("images", "labels", "labels_pre"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("".join(f"{c}\n" for c in CLASSES))
    model, device = YOLO("yolo11n.pt"), get_device()
    coco = {i: n for i, n in model.names.items() if n in CLASSES}
    counts = {c: 0 for c in CLASSES}
    rows = []
    for folder, n, cam in candidates(root, stride, seed):
        if all(v >= target for v in counts.values()) or len(rows) >= max_images:
            break
        src = folder / cam / f"{n:06d}.jpg"
        image = cv2.imread(str(src))
        if image is None:
            continue
        h, w = image.shape[:2]
        r = model.predict(image, conf=0.25, imgsz=1280, classes=list(coco), device=device, verbose=False)[0]
        boxes = [(CLASSES.index(coco[int(c)]), b) for c, b in zip(r.boxes.cls.tolist(), r.boxes.xyxy.tolist())]
        name = f"{folder.parent.name}-{folder.name}_{cam}_{n:06d}"
        shutil.copy2(src, out / "images" / f"{name}.jpg")
        text = "".join(f"{c} {to_yolo(b, w, h)}\n" for c, b in boxes)
        (out / "labels" / f"{name}.txt").write_text(text)
        (out / "labels_pre" / f"{name}.txt").write_text(text)
        per = {c: sum(1 for k, _ in boxes if CLASSES[k] == c) for c in CLASSES}
        for c in CLASSES:
            counts[c] += per[c]
        rows.append({"file": name, "recording": f"{folder.parent.name}/{folder.name}", "frame": n, "camera": cam,
                     **{f"pre_{c}": per[c] for c in CLASSES}})
    with (out / "manifest.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"images": len(rows), "prelabel_boxes": counts,
            "recordings": len({r["recording"] for r in rows}), "out": str(out)}


# ── score ──

def label_status(dataset: Path, images: list[Path]) -> tuple[bool, list[str]]:
    """라벨이 초안 그대로인지, 확인 안 한 사진이 있는지 보고 경고한다"""
    unchanged = all((dataset / "labels" / f"{p.stem}.txt").read_text() ==
                    (dataset / "labels_pre" / f"{p.stem}.txt").read_text() for p in images
                    if (dataset / "labels_pre" / f"{p.stem}.txt").exists())
    reviewed_path = dataset / "reviewed.json"
    reviewed = set(json.loads(reviewed_path.read_text())) if reviewed_path.exists() else set()
    not_reviewed = [p.stem for p in images if p.stem not in reviewed]
    if unchanged:
        print("[주의] labels/ 가 초안(labels_pre/)과 전부 같아요. 라벨을 확인·수정하기 전이면 결과가 부풀려집니다",
              file=sys.stderr)
    if not_reviewed:
        print(f"[주의] 확인 안 한 사진 {len(not_reviewed)}장 (label_tool.py 로 저장한 사진만 확인함으로 셈). "
              f"이 사진들은 초안이 정답으로 들어갑니다", file=sys.stderr)
    return unchanged, not_reviewed


def score(dataset: Path, iou_min: float, min_height: float, vis: bool):
    import cv2
    from detector import Detector

    images = sorted((dataset / "images").glob("*.jpg"))
    if not images:
        raise SystemExit(f"이미지가 없어요: {dataset / 'images'}")
    unchanged, not_reviewed = label_status(dataset, images)
    detector = Detector(model="coco", classes=CLASSES, foot="box")
    all_rows, box_rows = [], []
    if vis:
        (dataset / "vis").mkdir(exist_ok=True)
    for path in images:
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        truth = read_yolo(dataset / "labels" / f"{path.stem}.txt", w, h)
        preds = [(d["cls"], d["conf"], tuple(d["bbox"])) for d in detector(image, track=False)]
        rows = match(truth, preds, iou_min, min_height)
        all_rows += rows
        for kind, cls, box, conf, v, confused in rows:
            box_rows.append({"file": path.stem, "result": kind, "cls": cls, "conf": conf, "iou": v,
                             "other_class": confused, "bbox": [round(x, 1) for x in box]})
        if vis and any(r[0] != "tp" for r in rows):
            colors = {"tp": (0, 200, 0), "fp": (0, 0, 255), "fn": (255, 120, 0)}
            for kind, cls, box, conf, *_ in rows:
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(image, (x1, y1), (x2, y2), colors[kind], 2)
                cv2.putText(image, f"{kind} {cls}" + (f" {conf:.2f}" if conf else ""), (x1, max(14, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[kind], 2)
            cv2.imwrite(str(dataset / "vis" / path.name), image)
    report = {"dataset": str(dataset), "images": len(images), "labels_unchanged_from_prelabel": unchanged,
              "reviewed_images": len(images) - len(not_reviewed),
              "detector": {"model": detector.model_name, "imgsz": detector.imgsz, "class_conf": detector.class_conf,
                           "track": False},
              "iou_min": iou_min, "min_height_px": min_height, "classes": summarize(all_rows)}
    (dataset / "score.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    with (dataset / "score_boxes.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(box_rows[0]) if box_rows else ["file"])
        writer.writeheader()
        writer.writerows(box_rows)
    return report


def sweep_rows(paths, load, detector, cls: str, confs: list[float], iou_min: float = 0.5,
               min_height: float = 20) -> list[dict]:
    """
    cls의 conf 기준마다 탐지기를 직접 다시 돌려 채점한다.
    탐지기는 반올림 전 신뢰도로 거르고 반올림한 값을 돌려주므로, 돌려받은 conf로 다시 거르면 경계에서 결과가 달라진다.
    load(path) → (이미지, 정답)
    """
    base = dict(detector.class_conf)
    out = []
    try:
        for conf in confs:
            detector.class_conf = {**base, cls: conf}
            rows = []
            for path in paths:
                image, truth = load(path)
                preds = [(d["cls"], d["conf"], tuple(d["bbox"])) for d in detector(image, track=False)]
                rows += match(truth, preds, iou_min, min_height)
            out.append({"conf": conf, "class_conf": dict(detector.class_conf), **summarize(rows)[cls]})
    finally:
        detector.class_conf = base
    return out


def sweep(dataset: Path, cls: str, confs: list[float], iou_min: float, min_height: float):
    """기준마다 프레임별로 직접 탐지한다 (추적 없음)"""
    import cv2
    from detector import Detector

    images = sorted((dataset / "images").glob("*.jpg"))
    if not images:
        raise SystemExit(f"이미지가 없어요: {dataset / 'images'}")
    unchanged, not_reviewed = label_status(dataset, images)

    def load(path):
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        return image, read_yolo(dataset / "labels" / f"{path.stem}.txt", w, h)

    detector = Detector(model="coco", classes=CLASSES, foot="box")
    return {"dataset": str(dataset), "images": len(images), "labels_unchanged_from_prelabel": unchanged,
            "reviewed_images": len(images) - len(not_reviewed), "cls": cls,
            "detector": {"model": detector.model_name, "imgsz": detector.imgsz, "class_conf": detector.class_conf,
                         "track": False},
            "iou_min": iou_min, "min_height_px": min_height,
            "rows": sweep_rows(images, load, detector, cls, confs, iou_min, min_height)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실제 영상 사람·의자 라벨 세트 만들기·채점")
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="프레임 고르기 + 초안 라벨")
    m.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="녹화 폴더 (s*/t*/cam1, cam2)")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--target", type=int, default=120, help="초안 기준 사람·의자 각각 이만큼 모일 때까지 (고치면 조금 줄어듦)")
    m.add_argument("--stride", type=int, default=30, help="같은 녹화에서 후보 프레임 간격 (짝 번호)")
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--max-images", type=int, default=200)
    s = sub.add_parser("score", help="고친 라벨로 탐지기 채점")
    s.add_argument("dataset", type=Path)
    s.add_argument("--iou", type=float, default=0.5)
    s.add_argument("--min-height", type=float, default=20)
    s.add_argument("--vis", action="store_true", help="틀린 프레임을 그려 vis/ 에 저장")
    w = sub.add_parser("sweep", help="한 클래스의 conf 기준별 오탐률·검출률")
    w.add_argument("dataset", type=Path)
    w.add_argument("--cls", choices=CLASSES, default="chair")
    w.add_argument("--confs", default="0.4,0.35,0.3,0.25,0.2")
    w.add_argument("--iou", type=float, default=0.5)
    w.add_argument("--min-height", type=float, default=20)
    args = parser.parse_args()
    if args.cmd == "sweep":
        confs = [float(x) for x in args.confs.split(",")]
        result = sweep(args.dataset.expanduser(), args.cls, confs, args.iou, args.min_height)
    elif args.cmd == "make":
        result = make(args.root.expanduser(), args.out.expanduser(), args.target, args.stride, args.seed, args.max_images)
    else:
        result = score(args.dataset.expanduser(), args.iou, args.min_height, args.vis)
    print(json.dumps(result, indent=2, ensure_ascii=False))
