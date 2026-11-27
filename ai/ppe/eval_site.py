"""
11/25 실제 촬영 보호구 정지 장면(s20~s22)으로 보호구 모델 채점 (학습에 쓰지 않은 녹화)

서버 응답(runs/edge/<session>/responses_detections.jsonl)의 사람 위치로 A(왼쪽 줄, x < 1.5)와
B(오른쪽 줄)를 나누고, 그 사람의 카메라별 상자를 녹화 사진에서 엣지와 같은 방식으로 잘라 판별한다.
정답은 촬영 계획서 착용표다 (자전거 헬멧 = helmet wearing, 야구모자 = not_wearing).

사용 예:
    python ppe/eval_site.py runs/ppe_v1/weights/best.pt runs/ppe_v2/weights/best.pt
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2

AI = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(AI / "ppe"), str(AI / "edge")]
from ppe_common import decide_state, expand_box  # noqa: E402

W, N = "wearing", "not_wearing"
SCENES = {  # 장면: (녹화 폴더, 세션, {사람: (helmet, vest)})
    "s20": ("s20/t2", "classroom-1125-s20-t2", {"A": (W, W), "B": (N, N)}),   # B 야구모자
    "s21": ("s21/t1", "classroom-1125-s21-t1", {"A": (W, N), "B": (N, W)}),
    "s22": ("s22/t1", "classroom-1125-s22-t1", {"A": (N, N), "B": (W, W)}),
}


def samples(every):
    for scene, (rec, session, truth) in SCENES.items():
        rows = [json.loads(line) for line in open(AI / "runs" / "edge" / session / "responses_detections.jsonl")]
        rows = sorted((r for r in rows if r.get("status") == "processed"), key=lambda r: r["pair_id"])
        for r in rows[::every]:
            for m in r["matches"]:
                if m["cls"] != "person":
                    continue
                who = "A" if m["world"]["x"] < 1.5 else "B"
                for o in m["observations"]:
                    path = AI / "runs" / "real" / "classroom-1125" / rec / o["camera_id"] / f"{o['frame_id']:06d}.jpg"
                    if path.exists():
                        yield scene, who, truth[who], path, o["bbox"]


def score(weights, items, conf_min):
    from ultralytics import YOLO
    model = YOLO(str(weights))
    table = defaultdict(Counter)            # (항목, 정답) → 판별 결과 개수
    per = defaultdict(Counter)              # (장면, 사람, 항목) → 판별 결과
    for scene, who, (helmet, vest), path, bbox in items:
        img = cv2.imread(str(path))
        h, w = img.shape[:2]
        x1, y1, x2, y2 = expand_box(bbox, w, h)
        r = model.predict(img[y1:y2, x1:x2], imgsz=320, conf=conf_min, verbose=False)[0]
        boxes = [(int(c), float(p), *map(float, b)) for c, p, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn)]
        state = decide_state(boxes, conf_min)
        for item, truth in (("helmet", helmet), ("vest", vest)):
            got = state[item]["status"]
            table[item, truth][got] += 1
            per[scene, who, item][got] += 1
    return table, per


def main():
    p = argparse.ArgumentParser()
    p.add_argument("weights", nargs="+", type=Path)
    p.add_argument("--every", type=int, default=3, help="서버 묶음 몇 개마다 하나씩 볼지")
    p.add_argument("--conf", type=float, default=0.4)
    a = p.parse_args()
    items = list(samples(a.every))
    print(f"채점 사진: {len(items)}장 (s20 t2, s21 t1, s22 t1)")
    for weights in a.weights:
        table, per = score(weights, items, a.conf)
        print(f"\n== {weights}")
        for item in ("helmet", "vest"):
            for truth in (W, N):
                c = table[item, truth]
                n = sum(c.values()) or 1
                print(f"  {item:6s} 정답 {truth:11s} {sum(c.values()):4d}장 | 맞음 {100 * c[truth] / n:5.1f}% "
                      f"| 판별 못함 {100 * c['unknown'] / n:5.1f}% | 반대로 봄 {100 * c[N if truth == W else W] / n:5.1f}%")
        for (scene, who, item), c in sorted(per.items()):
            if item == "helmet":
                print(f"    {scene} {who} 안전모: {dict(c)}")


if __name__ == "__main__":
    main()
