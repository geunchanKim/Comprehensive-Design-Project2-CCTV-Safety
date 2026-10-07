"""
서버가 계산한 바닥 위치 vs 정답 위치 오차 측정 (1:1 비교)

엣지 실행 결과 폴더의 responses_detections.jsonl(서버가 돌려준 매칭·3D 좌표)과
Unity 폴더의 frames.jsonl(정답 좌표)을 프레임별로 맞대서 오차를 계산한다.

  - 정답 좌표는 unity_reader 와 같은 규칙으로 변환: Unity (x, y, z) → 월드 (x, z, y)
  - 프레임·클래스마다 서버 결과와 정답 물체를 헝가리안으로 1:1 배정한다 (바닥 거리 합이 최소가 되게)
    "가장 가까운 정답" 비교는 잘못 짝지은 결과도 근처 다른 사람에 붙어 오차가 작아 보이므로 쓰지 않는다
  - 배정된 쌍의 바닥 오차가 --thr(기본 50cm) 이하면 "맞음", 넘으면 "오매칭"
  - 정답에 배정되지 못한 서버 결과도 "오매칭"(남는 결과)으로 센다
  - 두 카메라 정답 bbox에 모두 보였는데 "맞음" 결과가 없는 정답은 "놓침"
  - ID 바뀜: 같은 정답 물체에 붙은 서버 object_id가 직전 "맞음" 프레임과 달라진 횟수

출력
  화면: 클래스별 요약
    - 맞음 수 / 기회, 오차(맞음만) 평균·중앙값·90%·최대, x·y 치우침, 평균 z
    - 오매칭 비율 = 오매칭 / 서버 결과 수, 놓침 비율 = 놓침 / 기회, ID 바뀜 횟수
  파일: <결과 폴더>/position_errors.csv (결과·놓침 하나당 한 줄, status = ok / mismatch / extra / missed)

실행 (ai/ 폴더에서)
  python eval/eval_position.py runs/edge/unity-classroom-02-run3
  python eval/eval_position.py runs/edge/unity-classroom-02-run3 --gt runs/unity/unity-classroom-02
  python eval/eval_position.py runs/edge/unity-classroom-02-run3 --thr 30
  (--gt 를 안 주면 session 이름에서 -runN 을 떼고 runs/unity/ 에서 찾는다)
"""

import argparse
import csv
import itertools
import json
import math
import re
import statistics
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
FIELDS = ["frame", "cls", "status", "object_id", "server_object_id", "gt_x", "gt_y",
          "est_x", "est_y", "est_z", "dx_cm", "dy_cm", "floor_err_cm", "epipolar_px"]


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


def assign(cost: list[list[float]]) -> list[tuple[int, int]]:
    """비용 합이 최소인 1:1 배정 (행 = 서버 결과, 열 = 정답). 한 프레임 물체 수가 적어 전부 따져 본다"""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return []
    if n <= m:
        best = min(itertools.permutations(range(m), n), key=lambda p: sum(cost[i][p[i]] for i in range(n)))
        return [(i, best[i]) for i in range(n)]
    return [(i, j) for j, i in assign([list(col) for col in zip(*cost)])]


def visible_in_both(o) -> bool:
    return {"cam1", "cam2"} <= set((o.get("bbox") or {}).keys())


def evaluate(run_dir: Path, gt_dir: Path, thr_cm: float = 50.0):
    """반환: (rows, visible) — rows 는 결과·놓침 한 줄씩, visible 은 클래스별 기회(두 카메라 모두 보인 정답 수)"""
    responses = read_jsonl(run_dir / "responses_detections.jsonl")
    gt = {r["frame"]: r for r in read_jsonl(gt_dir / "frames.jsonl")}

    rows, visible = [], {}
    for resp in responses:
        frame = resp["pair_id"]
        objects = gt.get(frame, {}).get("objects", [])
        matches = resp.get("matches", [])
        for cls in sorted({o["cls"] for o in objects} | {m["cls"] for m in matches}):
            gts = [(o, unity_to_world(o["world"])) for o in objects if o["cls"] == cls]
            res = [m for m in matches if m["cls"] == cls]
            visible[cls] = visible.get(cls, 0) + sum(visible_in_both(o) for o, _ in gts)
            cost = [[math.hypot(m["world"]["x"] - g[0], m["world"]["y"] - g[1]) for _, g in gts] for m in res]
            pairs = dict(assign(cost))
            hit_gt = set()
            for i, m in enumerate(res):
                w = m["world"]
                row = {"frame": frame, "cls": cls, "server_object_id": m["object_id"],
                       "est_x": round(w["x"], 4), "est_y": round(w["y"], 4), "est_z": round(w["z"], 4),
                       "epipolar_px": m.get("epipolar_error_px")}
                if i in pairs:
                    o, g = gts[pairs[i]]
                    dx, dy = w["x"] - g[0], w["y"] - g[1]
                    err = math.hypot(dx, dy) * 100
                    ok = err <= thr_cm
                    if ok:
                        hit_gt.add(pairs[i])
                    row.update(status="ok" if ok else "mismatch", object_id=o["object_id"],
                               gt_x=round(g[0], 4), gt_y=round(g[1], 4),
                               dx_cm=round(dx * 100, 1), dy_cm=round(dy * 100, 1), floor_err_cm=round(err, 1))
                else:
                    row.update(status="extra")
                rows.append(row)
            for j, (o, g) in enumerate(gts):
                if visible_in_both(o) and j not in hit_gt:
                    rows.append({"frame": frame, "cls": cls, "status": "missed", "object_id": o["object_id"],
                                 "gt_x": round(g[0], 4), "gt_y": round(g[1], 4)})
    return rows, visible


def id_switches(rows) -> int:
    """같은 정답 물체에 붙은 서버 object_id 가 직전 '맞음' 프레임과 달라진 횟수"""
    last, switches = {}, 0
    for r in sorted((r for r in rows if r["status"] == "ok"), key=lambda r: r["frame"]):
        prev = last.get(r["object_id"])
        if prev is not None and prev != r["server_object_id"]:
            switches += 1
        last[r["object_id"]] = r["server_object_id"]
    return switches


def summarize(rows, visible) -> dict:
    """클래스별 요약 지표 (실험 자동화에서도 이 함수를 쓴다)"""
    out = {}
    for cls in sorted({r["cls"] for r in rows} | set(visible)):
        rs = [r for r in rows if r["cls"] == cls]
        ok = [r for r in rs if r["status"] == "ok"]
        results = [r for r in rs if r["status"] in ("ok", "mismatch", "extra")]
        wrong = [r for r in results if r["status"] != "ok"]
        missed = [r for r in rs if r["status"] == "missed"]
        e = [r["floor_err_cm"] for r in ok]
        chance = visible.get(cls, 0)
        out[cls] = {
            "ok": len(ok), "chance": chance, "results": len(results),
            "mean_cm": statistics.mean(e) if e else None, "median_cm": statistics.median(e) if e else None,
            "p90_cm": percentile(e, 0.9) if e else None, "max_cm": max(e) if e else None,
            "bias_x_cm": statistics.mean(r["dx_cm"] for r in ok) if ok else None,
            "bias_y_cm": statistics.mean(r["dy_cm"] for r in ok) if ok else None,
            "mean_z_cm": statistics.mean(r["est_z"] for r in ok) * 100 if ok else None,
            "mismatch_rate": len(wrong) / len(results) if results else 0.0,
            "miss_rate": len(missed) / chance if chance else 0.0,
            "id_switches": id_switches(rs),
        }
    return out


def fmt(v, spec="8.1f"):
    return f"{v:{spec}}" if v is not None else f"{'-':>{spec.split('.')[0]}}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="엣지 결과 폴더 (responses_detections.jsonl 이 있는 곳)")
    parser.add_argument("--gt", default=None, help="정답 Unity 폴더 (frames.jsonl). 기본: session 이름으로 찾기")
    parser.add_argument("--thr", type=float, default=50.0, help="맞음 기준 바닥 오차 cm (기본 50)")
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

    rows, visible = evaluate(run_dir, gt_dir, args.thr)
    out = run_dir / "position_errors.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"결과: {run_dir.name}  정답: {gt_dir.name}  (1:1 배정, 맞음 기준 {args.thr:g}cm)\n")
    print(f"{'클래스':<8}{'맞음/기회':>11}{'평균':>8}{'중앙값':>8}{'90%':>8}{'최대':>8}"
          f"{'오매칭':>8}{'놓침':>7}{'ID바뀜':>7}{'x치우침':>9}{'y치우침':>9}{'평균z':>8}")
    for cls, s in summarize(rows, visible).items():
        ratio = f"{s['ok']}/{s['chance']}"
        print(f"{cls:<8}{ratio:>11}"
              f"{fmt(s['mean_cm'])}{fmt(s['median_cm'])}{fmt(s['p90_cm'])}{fmt(s['max_cm'])}"
              f"{s['mismatch_rate'] * 100:7.1f}%{s['miss_rate'] * 100:6.1f}%{s['id_switches']:7d}"
              f"{fmt(s['bias_x_cm'], '9.1f')}{fmt(s['bias_y_cm'], '9.1f')}{fmt(s['mean_z_cm'])}")
    print("\n오차·치우침·평균z(cm)는 '맞음' 결과만 계산")
    print("오매칭 = (기준 초과 + 남는 결과) / 서버 결과 수, 놓침 = 맞음 없는 정답 / 기회")
    print("기회 = 두 카메라 정답 bbox에 모두 보인 정답 수")
    print(f"프레임별 자세한 값: {out}")


if __name__ == "__main__":
    main()
