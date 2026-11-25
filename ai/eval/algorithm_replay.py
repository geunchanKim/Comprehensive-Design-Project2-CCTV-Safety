"""
알고리즘 조건별 사람 끊김·근접 경고 비교: 엣지 전송 기록을 서버에 다시 보내고 조건마다 재계산한다 (YOLO 다시 안 돌림)

무엇을 하나
  - runs/edge/<session_id>/sent_detections.jsonl 을 새 session_id 로 서버에 보낸다 (기본 baseline 으로 처리됨)
  - 조건마다 /sessions/<id>/recompute → results.csv 를 받아 <out>/<폴더 이름>/<조건>.csv 로 저장한다
  - 조건마다 센다
      주요 사람 수   --min-pairs 번 이상 나온 사람 번호 (짧게 나왔다 사라진 번호는 따로)
      빠진 묶음·끊김  처음~마지막 등장 사이에 사람이 결과에서 빠진 묶음 수와 구간 수 (pair_drops.py 와 같은 계산)
      경고 구간      두 물체 사이 warning·danger 가 이어진 구간 수. 한 묶음이라도 끊기면 새 구간 (화면에서는 새 경고)
  - 근접 경고를 세려면 서버가 ENABLE_RISK_ANALYSIS=true 여야 한다 (아니면 경고 구간 0)

데모 서버 대신 로컬 서버를 쓴다 (세션이 쌓이지 않게). 백엔드를 SQLite 로 띄우는 법은 docs/specs/ppe-integration-replay.md 7번

명령 (ai/ 폴더에서)
  python eval/algorithm_replay.py runs/edge/classroom-1014-s10-t1-v93 runs/edge/classroom-1014-s10-t1-v94 \\
      --server http://127.0.0.1:8123 --calib calibration/output/calib-classroom-1014-2x2b.json \\
      --algorithms baseline,f-cd,f-cdh --out runs/experiments/algorithm-replay
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair_drops import gaps, read_jsonl  # noqa: E402


def count(csv_text: str, pairs: list[int], min_pairs: int = 30) -> dict:
    """results.csv → 사람 끊김·경고 구간 수"""
    idx = {p: i for i, p in enumerate(pairs)}
    present, risky = {}, {}
    for row in csv.DictReader(csv_text.splitlines()):
        if not row.get("pair_id") or int(row["pair_id"]) not in idx:
            continue
        i = idx[int(row["pair_id"])]
        if row["record_type"] == "position" and row["cls"] == "person" and row["object_id"]:
            present.setdefault(int(row["object_id"]), set()).add(i)
        elif row["record_type"] == "risk" and row.get("object2_id") and row["level"] in ("warning", "danger"):
            risky.setdefault(tuple(sorted((int(row["object_id"]), int(row["object2_id"])))), set()).add(i)
    main = {o: s for o, s in present.items() if len(s) >= min_pairs}
    runs = [g for s in main.values() for g in gaps([i in s for i in range(len(pairs))])]
    episodes = sum(1 + sum(1 for a, b in zip(s, s[1:]) if b - a > 1) for s in map(sorted, risky.values()))
    return {"people": len(main), "short_ids": len(present) - len(main),
            "pairs_missing": sum(b - a + 1 for a, b in runs), "drops": len(runs),
            "longest_drop_pairs": max((b - a + 1 for a, b in runs), default=0),
            "warning_episodes": episodes, "warning_pairs": sum(len(s) for s in risky.values())}


def replay(server: str, folder: Path, calib: dict, algorithms: list[str], out: Path, min_pairs: int) -> dict:
    http = requests.Session()
    session = f"replay-{folder.name}-{int(time.time())}"[-64:]
    for cam in ("cam1", "cam2"):
        for profile in ("basic", "precise"):
            http.put(f"{server}/cameras/{cam}/calibration",
                     json={**calib[cam][profile], "session_id": session}, timeout=10).raise_for_status()
    bundles = read_jsonl(folder / "sent_detections.jsonl")
    for b in bundles:
        http.post(f"{server}/detections", json={**b, "session_id": session}, timeout=60).raise_for_status()
    pairs = [b["pair_id"] for b in bundles]
    (out / folder.name).mkdir(parents=True, exist_ok=True)
    result = {}
    for alg in algorithms:
        params = {"profile": "basic", "algorithm": alg}
        if alg != "baseline":
            http.post(f"{server}/sessions/{session}/recompute", params=params, timeout=900).raise_for_status()
        r = http.get(f"{server}/sessions/{session}/results.csv", params=params, timeout=120)
        r.raise_for_status()
        (out / folder.name / f"{alg}.csv").write_text(r.text, encoding="utf-8")
        result[alg] = count(r.text, pairs, min_pairs)
    return {"session_id": session, "pairs": len(pairs), "conditions": result}


def report(results: dict) -> str:
    lines = ["| 기록 | 조건 | 주요 사람 | 빠진 묶음 | 끊김 | 가장 긴 끊김 | 경고 구간 | 경고 묶음 |",
             "|---|---|---|---|---|---|---|---|"]
    for name, res in results.items():
        for alg, c in res["conditions"].items():
            lines.append(f"| {name} | {alg} | {c['people']} (+짧은 번호 {c['short_ids']}) | {c['pairs_missing']} | "
                         f"{c['drops']} | {c['longest_drop_pairs']} | {c['warning_episodes']} | {c['warning_pairs']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="알고리즘 조건별 사람 끊김·근접 경고 비교 (엣지 기록 재전송)")
    parser.add_argument("folders", nargs="+", type=Path, help="runs/edge/<session_id> 폴더")
    parser.add_argument("--server", default="http://127.0.0.1:8123")
    parser.add_argument("--calib", type=Path, required=True, help="calibration/output/calib-*.json")
    parser.add_argument("--algorithms", default="baseline,f-cd,f-cdh")
    parser.add_argument("--out", type=Path, default=Path("runs/experiments/algorithm-replay"))
    parser.add_argument("--min-pairs", type=int, default=30)
    args = parser.parse_args()
    calib = json.loads(args.calib.read_text(encoding="utf-8"))
    algs = args.algorithms.split(",")
    results = {f.name: replay(args.server.rstrip("/"), f, calib, algs, args.out, args.min_pairs) for f in args.folders}
    (args.out / "summary.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(report(results))
