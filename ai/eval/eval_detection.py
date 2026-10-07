"""
탐지 성능 측정 (서버 없이, Unity 정답 bbox와 비교)

Unity 폴더의 이미지에 탐지기를 직접 돌리고, frames.jsonl의 정답 bbox와 IoU로 비교한다.
설정(추적 켜기/끄기, conf, 입력 크기)을 바꿔 가며 같은 장면의 탐지율을 비교하는 용도.

  - 정답: 그 카메라에 bbox가 있고, visible_ratio >= --min-visible (기본 0.5)인 물체만 센다 (많이 가려진 건 제외)
  - 맞춤: 같은 클래스끼리 IoU가 큰 순서로 1:1 짝짓기, IoU >= --iou (기본 0.5)면 탐지 성공
  - 추적 켜기(기본)는 엣지 전송과 똑같이 track_id 없는 탐지를 뺀다 → 실제로 서버에 가는 것 기준
  - 추적 끄기(--no-track)는 모델이 낸 박스 전부 → 모델 자체 성능

출력
  화면: 클래스·카메라별 탐지율(recall), 오탐(정답과 안 맞는 박스) 수, 평균 IoU
       추적 켜기면 "track_id 없어 버려진 박스" 수도 표시
  파일: runs/eval/<장면>_<설정>.csv (프레임·카메라·정답 물체별 결과)

실행 (ai/ 폴더에서)
  python eval/eval_detection.py runs/unity/unity-classroom-03-s3                 # 지금 설정 (추적, conf 0.4, 1280)
  python eval/eval_detection.py runs/unity/unity-classroom-03-s3 --no-track      # 모델만
  python eval/eval_detection.py runs/unity/unity-classroom-03-s3 --imgsz 640 --conf 0.25
  python eval/eval_detection.py runs/unity/unity-classroom-03-s1 --max-frames 100  # 빠르게 일부만
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR / "edge"))
from detector import Detector, parse_class_conf  # noqa: E402

CAMERAS = ("cam1", "cam2")


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(gts, dets, thr):
    """같은 클래스끼리 IoU 큰 순서로 1:1 짝짓기 → ({정답 index: (det index, iou)}, 짝 없는 det index 목록)"""
    pairs = sorted(((iou(g["bbox"], d["bbox"]), gi, di)
                    for gi, g in enumerate(gts) for di, d in enumerate(dets) if g["cls"] == d["cls"]),
                   reverse=True)
    used_g, used_d, result = set(), set(), {}
    for v, gi, di in pairs:
        if v < thr or gi in used_g or di in used_d:
            continue
        used_g.add(gi); used_d.add(di); result[gi] = (di, v)
    return result, [i for i in range(len(dets)) if i not in used_d]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Unity 폴더 (cam1/, cam2/, frames.jsonl)")
    parser.add_argument("--model", choices=["coco", "v2", "ensemble"], default="coco")
    parser.add_argument("--class-conf", default=None, help="클래스별 conf. 예: person=0.5,chair=0.4 (coco 기본값 있음)")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--no-track", action="store_true", help="추적 끄고 모델 박스 전부 평가")
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--min-visible", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    folder = Path(args.folder)
    rows = [json.loads(l) for l in (folder / "frames.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.max_frames:
        rows = rows[:args.max_frames]
    track = not args.no_track
    detectors = {c: Detector(model=args.model, conf=args.conf, imgsz=args.imgsz, class_conf=parse_class_conf(args.class_conf)) for c in CAMERAS}
    tag = f"{'track' if track else 'notrack'}_conf{args.conf}_img{args.imgsz}_{args.model}"
    print(f"{folder.name} | {len(rows)}프레임 | {tag}")

    gt_n, hit_n, iou_sum = defaultdict(int), defaultdict(int), defaultdict(float)
    fp_n, no_id_n = defaultdict(int), defaultdict(int)
    part_n, part_hit = defaultdict(int), defaultdict(int)     # (클래스, 잘림/전신, 높이 구간) 별 탐지율
    out_rows = []
    t0 = time.perf_counter()
    for row in rows:
        frame = row["frame"]
        for cam in CAMERAS:
            img = cv2.imread(str(folder / cam / f"{frame:06d}.jpg"))
            if img is None:
                continue
            dets = detectors[cam](img, track=track)
            if track:
                no_id = [d for d in dets if d["track_id"] is None]
                for d in no_id:
                    no_id_n[(d["cls"], cam)] += 1
                dets = [d for d in dets if d["track_id"] is not None]
            gts = []
            for o in row["objects"]:
                bb = (o.get("bbox") or {}).get(cam)
                vr = o.get("visible_ratio")                  # 필드가 없는 예전 데이터는 전부 센다
                vis_ok = vr is None or (vr.get(cam) is not None and vr[cam] >= args.min_visible)
                if bb and vis_ok:
                    cut = bb[0] <= 3 or bb[1] <= 3 or bb[2] >= img.shape[1] - 3 or bb[3] >= img.shape[0] - 3
                    gts.append({"cls": o["cls"], "bbox": bb, "object_id": o["object_id"], "cut": cut})
            matched, unmatched = match(gts, dets, args.iou)
            for gi, g in enumerate(gts):
                key = (g["cls"], cam)
                gt_n[key] += 1
                hit = gi in matched
                if hit:
                    hit_n[key] += 1
                    iou_sum[key] += matched[gi][1]
                h = g["bbox"][3] - g["bbox"][1]
                sub = ("잘림" if g["cut"] else "전신", "<300" if h < 300 else ("300~450" if h < 450 else "450+"))
                part_n[(g["cls"],) + sub] += 1
                part_hit[(g["cls"],) + sub] += hit
                out_rows.append({"frame": frame, "camera": cam, "object_id": g["object_id"], "cls": g["cls"],
                                 "cut": int(g["cut"]), "box_h": round(h),
                                 "detected": int(hit), "iou": round(matched[gi][1], 3) if hit else "",
                                 "conf": dets[matched[gi][0]]["conf"] if hit else ""})
            for di in unmatched:
                fp_n[(dets[di]["cls"], cam)] += 1
        if frame % 50 == 0:
            print(f"  {frame}프레임 ({frame / (time.perf_counter() - t0):.1f} fps)")

    out_dir = AI_DIR / "runs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{folder.name}_{tag}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["frame", "camera", "object_id", "cls", "cut", "box_h", "detected", "iou", "conf"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n{'클래스':<8}{'카메라':<7}{'탐지율':>16}{'평균IoU':>9}{'오탐':>6}" + (f"{'id없음':>8}" if track else ""))
    for key in sorted(set(gt_n) | set(fp_n)):
        cls, cam = key
        n, h = gt_n[key], hit_n[key]
        rate = f"{h}/{n} ({100 * h / n:.0f}%)" if n else "정답 없음"
        mi = f"{iou_sum[key] / h:.2f}" if h else "-"
        line = f"{cls:<8}{cam:<7}{rate:>16}{mi:>9}{fp_n[key]:>6}"
        if track:
            line += f"{no_id_n[key]:>8}"
        print(line)
    print("\n사람: 화면 가장자리에 잘렸는지 · 박스 높이(px)별 탐지율")
    for key in sorted(k for k in part_n if k[0] == "person"):
        n, h = part_n[key], part_hit[key]
        print(f"  {key[1]:<4}{key[2]:>8}  {h}/{n} ({100 * h / n:.0f}%)")
    print(f"\n탐지율 = IoU {args.iou} 이상으로 맞춘 정답 / 가려짐 {args.min_visible} 미만 정답 수")
    print(f"오탐 = 정답과 안 맞는 박스" + (", id없음 = 추적 번호가 없어 엣지가 버리는 박스" if track else ""))
    print(f"결과: {out}")


if __name__ == "__main__":
    main()
