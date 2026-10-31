"""
실측 프레임에 검출 박스와 발 위치를 그린다: 논문의 검출 예시 그림을 다시 만든다

무엇을 하나
  - 실험 팩(eval/packs/<pack>/detections.jsonl.gz)에서 한 프레임 쌍의 검출 결과를 읽는다
  - 원본 사진(runs/real/classroom/s<장면>/t<회차>/cam1, cam2)에 박스를 그린다
      사람 = 빨간 박스, 의자 = 파란 박스, 노란 점 = 발 위치(두 발목 중점 또는 박스 하단 중점)
  - 카메라별 그림 2장과 두 그림을 나란히 붙인 그림 1장을 저장한다

명령 (ai/ 폴더에서)
  python eval/draw_detections.py real-s10-t1 604
  python eval/draw_detections.py real-s10-t1 604 --out runs/figures --scale 0.6
"""
import argparse
import gzip
import json
from pathlib import Path

import cv2
import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
COLORS = {"person": (40, 40, 230), "chair": (230, 130, 0)}   # BGR
FOOT_COLOR = (0, 220, 255)


def load_bundle(pack: str, pair_id: int) -> dict:
    """팩에서 pair_id 가 같은 프레임 쌍을 찾는다"""
    path = AI_DIR / "eval" / "packs" / pack / "detections.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            bundle = json.loads(line)
            if bundle["pair_id"] == pair_id:
                return bundle
    raise SystemExit(f"{pack} 에 pair_id {pair_id} 가 없음")


def image_dir(pack: str) -> Path:
    """real-s10-t1 → runs/real/classroom/s10/t1"""
    _, scene, take = pack.split("-")
    return AI_DIR / "runs" / "real" / "classroom" / scene / take


def draw(frame: dict, folder: Path, tag: str) -> np.ndarray:
    image = cv2.imread(str(folder / frame["camera_id"] / f"{frame['frame_id']:06d}.jpg"))
    if image is None:
        raise SystemExit(f"사진 없음: {folder / frame['camera_id']}")
    dets = [d for d in frame["detections"] if d["cls"] in COLORS]
    for d in dets:   # 박스를 먼저 다 그려야 이름표가 박스 선에 가리지 않는다
        x1, y1, x2, y2 = map(int, d["bbox"])
        cv2.rectangle(image, (x1, y1), (x2, y2), COLORS[d["cls"]], 4)
    for d in dets:
        x1, y1, _, _ = map(int, d["bbox"])
        (tw, th), _ = cv2.getTextSize(d["cls"], cv2.FONT_HERSHEY_SIMPLEX, 1.1, 2)
        ty = y1 if y1 > th + 14 else y1 + th + 14   # 사진 위쪽에 잘리면 박스 안쪽에 쓴다
        cv2.rectangle(image, (x1, ty - th - 12), (x1 + tw + 10, ty), COLORS[d["cls"]], -1)
        cv2.putText(image, d["cls"], (x1 + 5, ty - 7), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        if d["cls"] == "person" and d.get("foot"):
            fx, fy = map(int, d["foot"])
            cv2.circle(image, (fx, fy), 10, FOOT_COLOR, -1)
            cv2.circle(image, (fx, fy), 10, (0, 0, 0), 2)
    h, w = image.shape[:2]
    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 4)
    cv2.rectangle(image, (w - tw - 50, h - th - 50), (w - 10, h - 10), (255, 255, 255), -1)
    cv2.putText(image, tag, (w - tw - 30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    return image


def main():
    parser = argparse.ArgumentParser(description="실측 프레임에 검출 박스와 발 위치 그리기")
    parser.add_argument("pack", help="실험 팩 이름 (예: real-s10-t1)")
    parser.add_argument("pair_id", type=int, help="프레임 쌍 번호")
    parser.add_argument("--out", default="runs/figures", help="저장 폴더 (ai/ 기준)")
    parser.add_argument("--scale", type=float, default=0.6, help="나란히 붙인 그림의 축소 비율")
    args = parser.parse_args()

    bundle = load_bundle(args.pack, args.pair_id)
    folder = image_dir(args.pack)
    out = AI_DIR / args.out
    out.mkdir(parents=True, exist_ok=True)
    images = []
    for tag, frame in zip("ab", sorted(bundle["frames"], key=lambda f: f["camera_id"])):
        image = draw(frame, folder, f"({tag}) {frame['camera_id']}")
        cv2.imwrite(str(out / f"{args.pack}_{args.pair_id}_{frame['camera_id']}.jpg"), image,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        images.append(image)
        counts = {c: sum(d["cls"] == c for d in frame["detections"]) for c in COLORS}
        print(frame["camera_id"], counts)
    gap = np.full((images[0].shape[0], 20, 3), 255, np.uint8)
    both = cv2.resize(np.hstack([images[0], gap, images[1]]), None, fx=args.scale, fy=args.scale)
    path = out / f"{args.pack}_{args.pair_id}_both.jpg"
    cv2.imwrite(str(path), both, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("저장:", path)


if __name__ == "__main__":
    main()
