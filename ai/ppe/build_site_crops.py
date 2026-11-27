"""
11/25 실제 촬영 녹화 → 사람 영역 보호구 데이터셋 (자전거 헬멧 추가 학습용)

Construction-PPE 크롭(ppe-crops-v1)과 같은 형식으로 만든다: 사람 상자를 넓혀 자르고,
머리에 helmet/no_helmet 상자, 몸통에 vest/no_vest 상자를 하나씩 단다.

정답(누가 무엇을 썼나)은 녹화마다 정한 규칙으로 붙인다
  vest   조끼 입은 사람 = 자전거 헬멧 쓴 사람 (s24·s25·s26·s28). 조끼 상태는 기존 모델(v1)로 판별,
         모르면 그 사람은 뺀다
  color  옷 색으로 사람을 찾고 녹화별 착용표로 정한다 (s30, 아무도 조끼 안 입음)
  none   모두 맨머리·조끼 없음 (s23)
상자 위치는 기존 모델(v1)이 찾은 머리·몸통 상자를 쓰고(클래스는 무시), 없으면 포즈 관절로 만든다.
옆 사람과 겹친 사람은 라벨이 섞이니 뺀다.

평가용 s20~s22는 여기에 넣지 않는다 (ppe/eval_site.py 로 따로 채점).

사용 예:
    python ppe/build_site_crops.py runs/real/classroom-1125 ~/datasets/ppe-crops-site1125
결과: <out>/images/{train,val}, <out>/labels/{train,val}, <out>/manifest.jsonl, <out>/summary.json,
      <out>/preview_{train,val}.jpg (확인용 사진, 얼굴 포함이라 git에 올리지 않음)
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

AI = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(AI / "ppe"), str(AI / "edge")]
from ppe_common import expand_box, intersection, area  # noqa: E402

V1_WEIGHTS = AI / "runs" / "ppe_v1" / "weights" / "best.pt"
EVERY = 15                 # 15fps 녹화에서 약 1초에 1장 (비슷한 사진이 너무 많아지지 않게)
MIN_PERSON_H = 80          # 이보다 작으면 머리 모양이 안 보여서 뺀다
HEAD, TORSO = (0, 1), (2, 3)

# 녹화 → (규칙, 학습/검증, 착용표). 검증은 녹화 단위로 떼어 둔다
S30 = {  # 옷 → 머리 (helmet = 자전거 헬멧, cap·bare = 미착용)
    "t1": {"white": "helmet", "green": "cap", "gray": "bare"},
    "t2": {"gray": "helmet", "white": "cap", "green": "bare"},
    "t3": {"green": "helmet", "gray": "cap", "white": "bare"},
}
RECORDINGS = [
    ("s24/t1", "vest", "train", None),
    ("s25/t1", "vest", "train", None),
    ("s25/t2", "vest", "train", None),
    ("s25/t3", "vest", "train", None),
    ("s28/t1", "vest", "train", None),
    ("s23/t2", "none", "train", None),
    ("s30/t1", "color", "train", S30["t1"]),
    ("s30/t2", "color", "train", S30["t2"]),
    ("s26/t1", "vest", "val", None),
    ("s30/t3", "color", "val", S30["t3"]),
]


def torso_color(img, kp):
    """어깨~엉덩이 가운데 영역의 중앙값 HSV로 옷 구분 (11/25 세 사람: 흰 니트, 초록 티, 회색 패딩)"""
    sh, hp = kp[[5, 6]], kp[[11, 12]]
    if (sh == 0).any() or (hp == 0).any():
        return None
    x1, x2 = int(min(sh[:, 0].min(), hp[:, 0].min())), int(max(sh[:, 0].max(), hp[:, 0].max()))
    y1, y2 = int(sh[:, 1].mean()), int(hp[:, 1].mean())
    pad = int((x2 - x1) * 0.15)
    y1 += int((y2 - y1) * 0.1)
    roi = img[max(0, y1):max(0, y2), max(0, x1 + pad):max(0, x2 - pad)]
    if roi.size < 200:
        return None
    _h, s, v = np.median(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3), 0)
    # 그늘진 흰 니트가 회색처럼 보일 수 있어서 밝기 90~115는 애매하다고 보고 뺀다
    if s >= 80 and v < 80:
        return "green"
    if s < 60 and v >= 115:
        return "white"
    if s < 70 and v <= 90:
        return "gray"
    return None


def head_ok(head, torso, person):
    """머리 상자 가운데가 사람 상자 맨 위 13% 안, 몸통 위에 있어야 한다.
    뒷모습에서 조끼 깃(목)을 머리로 잡는 경우를 뺀다 (서 있는 사람 머리 가운데는 키의 약 7% 높이)"""
    if head is None or torso is None:
        return False
    cy = (head[1] + head[3]) / 2
    return cy < person[1] + 0.13 * (person[3] - person[1]) and cy < torso[1]


def pose_head(kp, crop):
    """포즈 관절로 머리 상자 (원본 좌표). 얼굴 관절이 없으면 어깨 위로 만든다"""
    face = kp[:5][(kp[:5] > 0).all(1)]
    sh = kp[[5, 6]]
    sw = abs(sh[0, 0] - sh[1, 0]) if (sh > 0).all() else 0
    if len(face) >= 2:
        cx, ey = face[:, 0].mean(), face[:, 1].mean()
        w = max(np.ptp(face[:, 0]) * 1.5, sw * 0.5, 12)
        box = (cx - w / 2, ey - 0.8 * w, cx + w / 2, ey + 0.6 * w)
    elif (sh > 0).all():
        cx, top = sh[:, 0].mean(), sh[:, 1].min()
        w = max(sw * 0.55, 12)
        box = (cx - w / 2, top - 1.4 * w, cx + w / 2, top - 0.1 * w)
    else:
        return None
    return clip(box, crop)


def pose_torso(kp, crop):
    sh, hp = kp[[5, 6]], kp[[11, 12]]
    if (sh == 0).any() or (hp == 0).any():
        return None
    xs, ys = np.r_[sh[:, 0], hp[:, 0]], np.r_[sh[:, 1], hp[:, 1]]
    pad = (xs.max() - xs.min()) * 0.15
    return clip((xs.min() - pad, ys.min(), xs.max() + pad, ys.max()), crop)


def clip(box, crop):
    x1, y1, x2, y2 = (max(box[0], crop[0]), max(box[1], crop[1]), min(box[2], crop[2]), min(box[3], crop[3]))
    return (x1, y1, x2, y2) if x2 - x1 > 4 and y2 - y1 > 4 else None


def model_box(boxes, classes, crop, head=False):
    """v1 탐지 중 해당 부위 상자(클래스 무시) 하나를 원본 좌표로. decide_state와 같은 위치 규칙"""
    cx1, cy1, cx2, cy2 = crop
    cw, ch = cx2 - cx1, cy2 - cy1
    best = None
    for cls, conf, bx, by, bw, bh in boxes:
        if cls not in classes or not 0.1 <= bx <= 0.9 or (head and by > 0.5):
            continue
        if best is None or conf > best[1]:
            best = ((cx1 + (bx - bw / 2) * cw, cy1 + (by - bh / 2) * ch,
                     cx1 + (bx + bw / 2) * cw, cy1 + (by + bh / 2) * ch), conf)
    return best[0] if best else None


def vest_state(boxes):
    best = None
    for cls, conf, bx, _by, _bw, _bh in boxes:
        if cls in TORSO and conf >= 0.4 and 0.1 <= bx <= 0.9 and (best is None or conf > best[1]):
            best = (cls, conf)
    return None if best is None else ("wearing" if best[0] == 2 else "not_wearing")


def to_yolo(cls, box, crop):
    cx1, cy1, cx2, cy2 = crop
    cw, ch = cx2 - cx1, cy2 - cy1
    x1, y1, x2, y2 = box
    return f"{cls} {(x1 + x2) / 2 / cw - cx1 / cw:.6f} {(y1 + y2) / 2 / ch - cy1 / ch:.6f} {(x2 - x1) / cw:.6f} {(y2 - y1) / ch:.6f}"


def build(runs: Path, out: Path, every: int):
    from ultralytics import YOLO
    det, pose, ppe = YOLO("yolo11n.pt"), YOLO("yolo11n-pose.pt"), YOLO(str(V1_WEIGHTS))
    counts, previews = Counter(), {"train": [], "val": []}
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    manifest = (out / "manifest.jsonl").open("w", encoding="utf-8")
    for rec, rule, split, table in RECORDINGS:
        for cam in ("cam1", "cam2"):
            files = sorted((runs / rec / cam).glob("*.jpg"))[::every]
            for f in files:
                img = cv2.imread(str(f))
                if img is None:
                    continue
                h, w = img.shape[:2]
                people = det.predict(img, imgsz=1280, conf=0.5, classes=[0], verbose=False)[0].boxes.xyxy.tolist()
                if not people:
                    continue
                pr = pose.predict(img, imgsz=1280, conf=0.25, verbose=False)[0]
                pboxes = pr.boxes.xyxy.tolist() if pr.boxes is not None else []
                pkps = pr.keypoints.xy.cpu().numpy() if pr.keypoints is not None else []
                crops = [expand_box(b, w, h) for b in people]
                ppe_res = ppe.predict([img[c[1]:c[3], c[0]:c[2]] for c in crops], imgsz=320, conf=0.1, verbose=False)
                for i, (pbox, crop, r) in enumerate(zip(people, crops, ppe_res)):
                    counts["people"] += 1
                    if pbox[3] - pbox[1] < MIN_PERSON_H:
                        counts["skip_small"] += 1
                        continue
                    if any(intersection(crop, o) / max(area(o), 1) > 0.15 for j, o in enumerate(people) if j != i):
                        counts["skip_overlap"] += 1
                        continue
                    boxes = [(int(c), float(p), *map(float, b)) for c, p, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn)]
                    ious = [intersection(pbox, b) / max(area(pbox) + area(b) - intersection(pbox, b), 1) for b in pboxes]
                    kp = pkps[int(np.argmax(ious))] if ious and max(ious) > 0.5 else None
                    if rule == "vest":
                        vest = vest_state(boxes)
                        head_truth = {"wearing": "helmet", "not_wearing": "bare"}.get(vest)
                    elif rule == "color":
                        vest = "not_wearing"
                        who = torso_color(img, kp) if kp is not None else None
                        head_truth = table.get(who) if who else None
                    else:
                        vest, head_truth = "not_wearing", "bare"
                    if head_truth is None:
                        counts["skip_no_truth"] += 1
                        continue
                    torso = model_box(boxes, TORSO, crop) or (pose_torso(kp, crop) if kp is not None else None)
                    head = model_box(boxes, HEAD, crop, head=True)
                    if not head_ok(head, torso, pbox):
                        head = pose_head(kp, crop) if kp is not None else None
                    if not head_ok(head, torso, pbox):
                        counts["skip_no_box"] += 1
                        continue
                    head_cls = 0 if head_truth == "helmet" else 1
                    vest_cls = 2 if vest == "wearing" else 3
                    name = f"{rec.replace('/', '-')}-{cam}-{f.stem}-{i}"
                    cv2.imwrite(str(out / "images" / split / f"{name}.jpg"), img[crop[1]:crop[3], crop[0]:crop[2]])
                    (out / "labels" / split / f"{name}.txt").write_text(
                        to_yolo(head_cls, head, crop) + "\n" + to_yolo(vest_cls, torso, crop) + "\n")
                    manifest.write(json.dumps({"name": name, "split": split, "recording": rec, "camera": cam,
                                               "frame": f.stem, "head": head_truth, "vest": vest, "rule": rule},
                                              ensure_ascii=False) + "\n")
                    counts[f"{split}_{head_truth}"] += 1
                    counts[f"{split}_vest_{vest}"] += 1
                    if len(previews[split]) < 48 and counts[f"{split}_{head_truth}"] % 7 == 1:
                        tile = img[crop[1]:crop[3], crop[0]:crop[2]].copy()
                        for cls, box, color in ((head_cls, head, (0, 200, 0) if head_cls == 0 else (0, 0, 255)),
                                                (vest_cls, torso, (0, 200, 200) if vest_cls == 2 else (200, 0, 200))):
                            p1 = (int(box[0] - crop[0]), int(box[1] - crop[1]))
                            p2 = (int(box[2] - crop[0]), int(box[3] - crop[1]))
                            cv2.rectangle(tile, p1, p2, color, 2)
                        tile = cv2.resize(tile, (120, 240))
                        cv2.putText(tile, head_truth, (3, 14), 0, 0.45, (0, 0, 255), 1)
                        previews[split].append(tile)
    manifest.close()
    for split, tiles in previews.items():
        if tiles:
            tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 12)
            cv2.imwrite(str(out / f"preview_{split}.jpg"), np.vstack([np.hstack(tiles[i:i + 12]) for i in range(0, len(tiles), 12)]))
    (out / "summary.json").write_text(json.dumps(dict(sorted(counts.items())), indent=2, ensure_ascii=False))
    (out / "data.yaml").write_text(f"path: {out}\ntrain: images/train\nval: images/val\n"
                                   "names:\n  0: helmet\n  1: no_helmet\n  2: vest\n  3: no_vest\n")
    print(json.dumps(dict(sorted(counts.items())), ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("runs", type=Path, help="classroom-1125 녹화 폴더")
    p.add_argument("out", type=Path)
    p.add_argument("--every", type=int, default=EVERY)
    a = p.parse_args()
    build(a.runs, a.out.expanduser(), a.every)


if __name__ == "__main__":
    main()
