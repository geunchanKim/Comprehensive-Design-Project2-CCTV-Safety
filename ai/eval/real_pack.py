"""
실측 정지 프레임 pack 만들기: 녹화 전체 탐지 + 캘리브레이션 + 일부 프레임 정답 → ai/eval/packs/<이름>/

왜 따로 만드나
  - 실측은 Unity처럼 매 프레임 정답이 없다. 사람이 바닥 표시점에 선 순간(정지 프레임)만 정답이 있다.
  - 탐지·추적은 녹화 전체로 해야 C(추적)·D(한 카메라 보완)가 실제처럼 이어서 동작한다.
  - 그래서 pack 에는 전체 탐지를 넣고, 정답 파일에는 정답 프레임만 넣는다.
    meta.json 의 "sparse_gt": true 를 보고 run_experiment 가 정답 프레임만 채점한다.

입력
  --edge    unity_reader --dry-run 결과 폴더 (sent_detections.jsonl, edge_config.json)
  --gt      정답 frames.jsonl. 줄마다 {"frame", "objects": [{"object_id", "cls", "rel": [x, y, 0]}]}
            rel 은 캘리브레이션과 같은 바닥 좌표(m)여야 한다 (classroom-1014: ID 0 마커 = (0, 0))
  --calib   캘리브레이션 json. {cam: {basic: 본문, precise: 본문}} 또는 {cam: 본문}
  --exclude 채점에서 뺄 정답. "프레임:object_id" 를 쉼표로 (예: 510:chair_1)

정답 변환
  - world: 바닥 (x, y) → Unity 형식 [x, 0, y] (eval_position.unity_to_world 가 다시 (x, y, 0) 으로 바꾼다)
  - bbox: 정답 점이 카메라 이미지 안에 투영되면 그 카메라 키를 넣는다 → 두 카메라 모두면 "기회"로 센다
    (가림은 따지지 않는다. 의자 뒤에 가려진 사람도 기회에 들어간다)

실행 (ai/ 폴더에서)
  python eval/real_pack.py --edge runs/edge/classroom-1014-s1-t1-v5 \\
      --gt ~/Downloads/clroom/diy-1014-s1-t1/frames.jsonl \\
      --calib calibration/output/calib-classroom-1014-floorcross.json --name real-s1-t1
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from run_experiment import PACK_DIR, read_jsonl, write_jsonl


def camera_bodies(calib: dict) -> dict:
    """{cam: {basic, precise}} 또는 {cam: 본문} → {cam: 투영에 쓸 본문(basic 우선)}"""
    return {cam: (body if "K" in body else body.get("basic") or body.get("precise")) for cam, body in calib.items()}


def project_point(body: dict, xy) -> tuple[float, float] | None:
    """바닥 점 → 픽셀. 카메라 뒤에 있으면 None"""
    point = np.array([[float(xy[0]), float(xy[1]), 0.0]])
    rvec, tvec = np.asarray(body["rvec"], float), np.asarray(body["tvec"], float).reshape(3)
    rotation, _ = cv2.Rodrigues(rvec)
    if (rotation @ point[0] + tvec)[2] <= 0:
        return None
    pixel, _ = cv2.projectPoints(point, rvec, tvec, np.asarray(body["K"], float), np.asarray(body["dist"], float))
    return tuple(float(v) for v in pixel.reshape(2))


def convert_gt(rows: list[dict], calib: dict, exclude: set[tuple[int, str]]) -> tuple[list[dict], int]:
    """정답 frames.jsonl → pack frames (world·bbox 채움, exclude 는 뺌). 반환: (프레임들, 뺀 개수)"""
    bodies = camera_bodies(calib)
    out, removed = [], 0
    for row in rows:
        objects = []
        for o in row["objects"]:
            if (int(row["frame"]), o["object_id"]) in exclude:
                removed += 1
                continue
            x, y = o["rel"][:2]
            bbox = {}
            for cam, body in bodies.items():
                pixel = project_point(body, (x, y))
                width, height = body["image_size"]
                if pixel and 0 <= pixel[0] < width and 0 <= pixel[1] < height:
                    u, v = pixel
                    bbox[cam] = [round(u, 1), round(v, 1), round(u, 1), round(v, 1)]
            objects.append({"object_id": o["object_id"], "cls": o["cls"], "world": [x, 0, y], "bbox": bbox,
                            "rel": o["rel"]})
        out.append({"frame": int(row["frame"]), "objects": objects,
                    **({"note": row["note"]} if row.get("note") else {})})
    return out, removed


def parse_exclude(text: str | None) -> set[tuple[int, str]]:
    items = set()
    for item in filter(None, (text or "").split(",")):
        frame, object_id = item.strip().split(":", 1)
        items.add((int(frame), object_id.strip()))
    return items


def make_real_pack(edge_dir: Path, gt_path: Path, calib_path: Path, name: str, exclude: set, force: bool = False,
                   pack_root: Path = PACK_DIR) -> Path:
    pack = pack_root / name
    if pack.exists() and not force:
        raise SystemExit(f"이미 있는 pack 이에요: {pack} (덮어쓰려면 --force)")
    sent = edge_dir / "sent_detections.jsonl"
    if not sent.exists():
        raise SystemExit(f"탐지 결과가 없어요: {sent} (unity_reader --dry-run 먼저)")
    calib = json.loads(calib_path.read_text(encoding="utf-8"))
    gt_rows = read_jsonl(gt_path)
    dets = [{k: v for k, v in b.items() if k != "session_id"} for b in read_jsonl(sent)]
    pair_ids = {b["pair_id"] for b in dets}
    missing = sorted(int(r["frame"]) for r in gt_rows if int(r["frame"]) not in pair_ids)
    if missing:
        raise SystemExit(f"정답 프레임이 탐지 결과에 없어요: {missing} (탐지가 끝까지 돌았는지 확인)")
    frames, removed = convert_gt(gt_rows, calib, exclude)

    pack.mkdir(parents=True, exist_ok=True)
    (pack / "calibration.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")
    write_jsonl(pack / "detections.jsonl.gz", dets)
    write_jsonl(pack / "frames.jsonl.gz", frames)
    edge = {}
    if (edge_dir / "edge_config.json").exists():
        edge = json.loads((edge_dir / "edge_config.json").read_text(encoding="utf-8"))
    count = lambda cls: sum(o["cls"] == cls for f in frames for o in f["objects"])
    visible = lambda cls: sum(o["cls"] == cls and {"cam1", "cam2"} <= set(o["bbox"]) for f in frames for o in f["objects"])
    meta = {"name": name, "source": str(edge_dir), "gt": str(gt_path), "calibration": str(calib_path),
            "note": "실측 정지 프레임: 전체 탐지 + 정답 프레임만 채점", "sparse_gt": True,
            "edge": edge or None, "pairs": len(dets), "gt_frames": [f["frame"] for f in frames],
            "gt_objects": {"person": count("person"), "chair": count("chair")},
            "gt_visible_both": {"person": visible("person"), "chair": visible("chair")},
            "excluded": sorted(f"{f}:{o}" for f, o in exclude), "excluded_count": removed,
            "created": datetime.now().isoformat(timespec="seconds")}
    (pack / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"pack 저장: {pack} (탐지 {len(dets)}묶음, 정답 {len(frames)}프레임 · 사람 {meta['gt_objects']['person']} · "
          f"의자 {meta['gt_objects']['chair']}, 두 카메라 시야 사람 {meta['gt_visible_both']['person']}, 뺀 정답 {removed})")
    return pack


def main():
    parser = argparse.ArgumentParser(description="실측 정지 프레임 pack 만들기")
    parser.add_argument("--edge", required=True, type=Path, help="unity_reader --dry-run 결과 폴더")
    parser.add_argument("--gt", required=True, type=Path, help="정답 frames.jsonl")
    parser.add_argument("--calib", required=True, type=Path, help="캘리브레이션 json")
    parser.add_argument("--name", required=True, help="pack 이름. 예: real-s1-t1")
    parser.add_argument("--exclude", default=None, help="채점에서 뺄 정답. 예: 510:chair_1")
    parser.add_argument("--force", action="store_true", help="같은 이름 pack 덮어쓰기")
    args = parser.parse_args()
    make_real_pack(args.edge.expanduser(), args.gt.expanduser(), args.calib.expanduser(), args.name,
                   parse_exclude(args.exclude), args.force)


if __name__ == "__main__":
    main()
