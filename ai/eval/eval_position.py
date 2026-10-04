"""
서버가 계산한 3D 좌표 vs 정답 좌표 오차 측정

엣지 실행 결과 폴더의 responses_detections.jsonl(서버가 돌려준 매칭·3D 좌표)과
Unity 폴더의 frames.jsonl(정답 좌표)을 프레임별로 맞대서 오차를 계산한다.

  - 정답 좌표는 unity_reader 와 같은 규칙으로 변환: Unity (x, y, z) → 월드 (x, z, y)
  - 서버 매칭 하나마다 같은 클래스의 정답 물체 중 바닥에서 가장 가까운 것과 비교
  - 바닥 오차 = (x, y) 거리, 높이 오차 = z (바닥 접점이라 0이 정답)

출력
  화면: 클래스별 요약 (매칭된 프레임 수, 바닥 오차 평균·중앙값·90%·최대, x·y 치우침, 평균 z)
  파일: <결과 폴더>/position_errors.csv (매칭 하나당 한 줄)

실행 (ai/ 폴더에서)
  python eval/eval_position.py runs/edge/unity-classroom-02-run3
  python eval/eval_position.py runs/edge/unity-classroom-02-run3 --gt runs/unity/unity-classroom-02
  (--gt 를 안 주면 session 이름에서 -runN 을 떼고 runs/unity/ 에서 찾는다)
"""

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent


def unity_to_world(p):
    x, y, z = p
    return [float(x), float(z), float(y)]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def percentile(values, q):
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def evaluate(run_dir: Path, gt_dir: Path):
    responses = read_jsonl(run_dir / "responses_detections.jsonl")
    gt = {r["frame"]: r for r in read_jsonl(gt_dir / "frames.jsonl")}

    rows = []
    for resp in responses:
        frame = resp["pair_id"]
        objects = gt.get(frame, {}).get("objects", [])
        for m in resp.get("matches", []):
            w = m["world"]
            cands = [(o, unity_to_world(o["world"])) for o in objects if o["cls"] == m["cls"]]
            if not cands:
                continue
            o, g = min(cands, key=lambda c: math.hypot(w["x"] - c[1][0], w["y"] - c[1][1]))
            dx, dy = w["x"] - g[0], w["y"] - g[1]
            rows.append({
                "frame": frame, "cls": m["cls"], "object_id": o["object_id"], "server_object_id": m["object_id"],
                "gt_x": round(g[0], 4), "gt_y": round(g[1], 4),
                "est_x": round(w["x"], 4), "est_y": round(w["y"], 4), "est_z": round(w["z"], 4),
                "dx_cm": round(dx * 100, 1), "dy_cm": round(dy * 100, 1),
                "floor_err_cm": round(math.hypot(dx, dy) * 100, 1),
                "epipolar_px": m.get("epipolar_error_px"),
            })

    # 정답 물체가 두 카메라 정답 bbox 모두에 있는 프레임 수 (매칭될 수 있었던 기회)
    visible = {}
    for r in gt.values():
        if r["frame"] not in {x["pair_id"] for x in responses}:
            continue
        for o in r["objects"]:
            if {"cam1", "cam2"} <= set((o.get("bbox") or {}).keys()):
                visible[o["cls"]] = visible.get(o["cls"], 0) + 1
    return rows, visible


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="엣지 결과 폴더 (responses_detections.jsonl 이 있는 곳)")
    parser.add_argument("--gt", default=None, help="정답 Unity 폴더 (frames.jsonl). 기본: session 이름으로 찾기")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if args.gt:
        gt_dir = Path(args.gt)
    else:
        base = re.sub(r"-run\d+$", "", run_dir.name)
        gt_dir = AI_DIR / "runs" / "unity" / base
    for p in (run_dir / "responses_detections.jsonl", gt_dir / "frames.jsonl"):
        if not p.exists():
            raise SystemExit(f"파일이 없어요: {p}")

    rows, visible = evaluate(run_dir, gt_dir)
    if not rows:
        raise SystemExit("서버 매칭이 하나도 없어요 (responses_detections.jsonl 의 matches 가 비어 있음)")

    out = run_dir / "position_errors.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"결과: {run_dir.name}  정답: {gt_dir.name}\n")
    print(f"{'클래스':<8}{'매칭/기회':>10}{'평균':>8}{'중앙값':>8}{'90%':>8}{'최대':>8}{'x치우침':>9}{'y치우침':>9}{'평균z':>8}  (cm)")
    for cls in sorted({r["cls"] for r in rows} | set(visible)):
        rs = [r for r in rows if r["cls"] == cls]
        if not rs:
            print(f"{cls:<8}{f'0/{visible.get(cls, 0)}':>10}   (매칭 없음)")
            continue
        e = [r["floor_err_cm"] for r in rs]
        print(f"{cls:<8}{f'{len(rs)}/{visible.get(cls, 0)}':>10}"
              f"{statistics.mean(e):8.1f}{statistics.median(e):8.1f}{percentile(e, 0.9):8.1f}{max(e):8.1f}"
              f"{statistics.mean(r['dx_cm'] for r in rs):9.1f}{statistics.mean(r['dy_cm'] for r in rs):9.1f}"
              f"{statistics.mean(r['est_z'] for r in rs) * 100:8.1f}")
    print("\n매칭/기회 = 서버가 매칭한 수 / 두 카메라 정답 bbox에 모두 보인 프레임 수")
    print(f"프레임별 자세한 값: {out}")


if __name__ == "__main__":
    main()
