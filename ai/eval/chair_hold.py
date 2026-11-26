"""
의자 위치 유지 시뮬레이션: 의자가 서버 결과에서 잠깐 빠져도 마지막 위치를 몇 초 유지하면 사람–의자 경고 구간이 얼마나 줄어드는지 본다

왜
  - 사람–의자 경고가 끊기는 이유의 약 80%는 의자가 결과에서 빠지는 것이다 (거리가 1m를 넘는 경우는 약 20%)
  - 의자는 대부분 서 있으므로, 빠진 동안 마지막 위치를 쓰는 것이 안전 쪽(fail-safe)이다

무엇을 하나
  - algorithm_replay.py 가 저장한 <조건>.csv(위치 기록)와 같은 녹화의 sent_detections.jsonl(묶음 시각)을 읽는다
  - 의자마다 빠진 묶음에서 마지막 위치를 --holds 초까지 유지한다
  - 사람–의자 거리가 --warning-m 미만이면 경고로 보고, 경고 구간 수를 센다
  - --alert-hold 초 안에 다시 켜진 경고는 같은 구간으로 본다 (서버 ALERT_HOLD_MS 와 같은 규칙, 0이면 끔)
  - 위치는 서버 결과 그대로 쓴다. 서버 위험 계산(속도·TTC)은 다시 하지 않는다

명령 (ai/ 폴더에서)
  python eval/chair_hold.py runs/experiments/algorithm-replay-1119/classroom-1014-s10-t1-v94/f-cd.csv \\
      runs/edge/classroom-1014-s10-t1-v94 --holds 0,1,3,10 --alert-hold 0,1
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load(csv_path: Path, edge: Path) -> tuple[dict, dict, list[int]]:
    """→ ({object_id: {묶음 순번: (x, y)}}, {object_id: cls}, 묶음 시각 목록(ms))"""
    bundles = [json.loads(line) for line in (edge / "sent_detections.jsonl").read_text().splitlines() if line.strip()]
    idx = {b["pair_id"]: i for i, b in enumerate(bundles)}
    times = [min(f["ts"] for f in b["frames"]) for b in bundles]
    pos, cls = defaultdict(dict), {}
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            if row["record_type"] == "position" and row["object_id"] and row.get("pair_id") and int(row["pair_id"]) in idx:
                obj = int(row["object_id"])
                cls[obj] = row["cls"]
                pos[obj][idx[int(row["pair_id"])]] = (float(row["x"]), float(row["y"]))
    return pos, cls, times


def held_positions(track: dict, times: list[int], hold_s: float) -> dict:
    """빠진 묶음에 마지막 위치를 hold_s 초까지 채운다"""
    out, last = {}, None
    for i in range(len(times)):
        if i in track:
            out[i], last = track[i], i
        elif last is not None and (times[i] - times[last]) / 1000 <= hold_s:
            out[i] = track[last]
    return out


def episodes(pos: dict, cls: dict, times: list[int], hold_s: float, alert_hold_s: float = 0.0,
             warning_m: float = 1.0) -> int:
    """사람–의자 경고 구간 수"""
    people = [o for o in pos if cls[o] == "person"]
    chairs = {o: held_positions(pos[o], times, hold_s) for o in pos if cls[o] == "chair"}
    count = 0
    for p in people:
        for chair in chairs.values():
            last_on = None
            for i in range(len(times)):
                a, b = pos[p].get(i), chair.get(i)
                if a is None or b is None or ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 >= warning_m:
                    continue
                if last_on is None or (i != last_on + 1 and (times[i] - times[last_on]) / 1000 > alert_hold_s):
                    count += 1
                last_on = i
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="의자 위치 유지 시뮬레이션 (사람–의자 경고 구간 수)")
    parser.add_argument("csv", type=Path, help="algorithm_replay.py 가 저장한 <조건>.csv")
    parser.add_argument("edge", type=Path, help="같은 녹화의 runs/edge/<session_id>")
    parser.add_argument("--holds", default="0,1,3,10", help="의자 위치 유지 초 (쉼표)")
    parser.add_argument("--alert-hold", default="0,1", help="경고 이어 보기 초 (쉼표, 0 = 끔)")
    parser.add_argument("--warning-m", type=float, default=1.0)
    args = parser.parse_args()
    pos, cls, times = load(args.csv, args.edge)
    holds = [float(h) for h in args.holds.split(",")]
    print("| 경고 이어 보기 | " + " | ".join(f"의자 유지 {h:g}초" for h in holds) + " |")
    print("|---|" + "---|" * len(holds))
    for ah in (float(a) for a in args.alert_hold.split(",")):
        cells = [str(episodes(pos, cls, times, h, ah, args.warning_m)) for h in holds]
        print(f"| {ah:g}초 | " + " | ".join(cells) + " |")
