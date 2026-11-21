"""
짝 끊김 원인 나누기: 사람이 서버 결과에서 잠깐 빠질 때 엣지가 못 본 건지, 서버가 짝을 못 지은 건지 센다

무엇을 하나
  - realtime.py --send 가 남긴 runs/edge/<session_id>/ 의 두 파일을 짝 번호(pair_id)로 맞춘다
      sent_detections.jsonl       엣지가 보낸 카메라별 탐지
      responses_detections.jsonl  서버가 돌려준 짝(matches)과 짝 못 지은 트랙(unmatched)
  - 주요 사람(서버 결과에 --min-pairs 번 이상 나온 object_id)마다 처음~마지막 등장 사이에서 빠진 짝을 찾는다
  - 빠진 짝마다 그 사람의 카메라별 트랙 번호(빠지기 직전·직후 짝에서 쓰던 번호)가 그 짝에서 어떤 상태였는지 본다
      unmatched  엣지는 보냈는데 서버가 짝을 못 지음
      missing    엣지가 그 트랙을 보내지 않음 (못 봤거나 트랙 번호가 바뀜)
                 이때 그 카메라에 짝 못 지은 다른 사람 트랙이 있으면 "엣지 트랙 번호 바뀜 의심"으로 따로 센다
      other      다른 object_id 의 짝에 들어감
  - 두 카메라 상태로 원인을 정한다
      pair_fail   두 카메라 모두 unmatched → 서버 짝짓기 실패
      one_cam     한쪽만 unmatched, 다른 쪽 missing → 한 카메라 엣지 놓침 (서버 기본값은 한 카메라만으로 위치를 내지 않음)
      both_miss   두 카메라 모두 missing → 두 카메라 엣지 놓침
      id_switch   한쪽이라도 other → 서버가 다른 사람 번호로 묶음
  - pair_fail 짝은 발 위치를 어디서 얻었는지(foot_src: ankle 발목 / box 박스 하단)도 센다. 박스 하단은 짝짓기 오차가 크다
  - 연속으로 빠진 구간(끊김 1번)은 구간 안에서 가장 많은 원인으로 센다

명령 (ai/ 폴더에서)
  python eval/pair_drops.py runs/edge/classroom-1014-s10-t1-v93 runs/edge/classroom-1014-s10-t1-v94
  python eval/pair_drops.py runs/edge/classroom-1014-s10-t1-v94 --json > drops-v94.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

CAUSES = ("pair_fail", "one_cam", "both_miss", "id_switch")
CAUSE_KO = {"pair_fail": "서버 짝짓기 실패", "one_cam": "한 카메라 놓침", "both_miss": "두 카메라 놓침",
            "id_switch": "다른 번호로 묶임"}
CAMS = ("cam1", "cam2")


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def classify(state1: str, state2: str) -> str:
    """카메라 두 대 상태 (unmatched / missing / other) → 원인"""
    states = {state1, state2}
    if "other" in states:
        return "id_switch"
    if states == {"unmatched"}:
        return "pair_fail"
    if states == {"missing"}:
        return "both_miss"
    return "one_cam"


def gaps(present: list[bool]) -> list[tuple[int, int]]:
    """등장 여부 목록 → 처음~마지막 등장 사이의 빠진 구간 [(시작, 끝 포함)]"""
    idx = [i for i, p in enumerate(present) if p]
    if not idx:
        return []
    out, start = [], None
    for i in range(idx[0], idx[-1] + 1):
        if not present[i] and start is None:
            start = i
        elif present[i] and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def camera_state(track_ids: set, cam: str, obj: int, sent: dict, resp: dict) -> tuple[str, str | None]:
    """빠진 짝에서 이 사람의 한 카메라 트랙 상태와 (보냈다면) 발 위치 출처"""
    for m in resp["matches"]:
        if m["object_id"] != obj and m["camera_tracks"].get(cam) in track_ids:
            return "other", None
    sent_dets = {d["track_id"]: d for f in sent["frames"] if f["camera_id"] == cam for d in f["detections"]}
    unmatched = resp.get("unmatched", {}).get(cam, [])
    for tid in track_ids:
        if tid in unmatched and tid in sent_dets:
            return "unmatched", sent_dets[tid].get("foot_src")
    other_person = any(d["cls"] == "person" and tid not in track_ids for tid, d in sent_dets.items() if tid in unmatched)
    return "missing", "new_track" if other_person else None


def analyze(folder: Path, min_pairs: int = 30) -> dict:
    sent = {s["pair_id"]: s for s in read_jsonl(folder / "sent_detections.jsonl")}
    resps = sorted((r for r in read_jsonl(folder / "responses_detections.jsonl") if r.get("status") == "processed"),
                   key=lambda r: r["pair_id"])
    resps = [r for r in resps if r["pair_id"] in sent]
    seen = Counter(m["object_id"] for r in resps for m in r["matches"] if m["cls"] == "person")
    people = sorted(o for o, n in seen.items() if n >= min_pairs)

    per_person, pair_causes, run_causes, foot_src = {}, Counter(), Counter(), Counter()
    track_change = 0   # missing 카메라에 짝 못 지은 다른 사람 트랙이 있던 경우 (카메라 단위)
    for obj in people:
        tracks = [next((m["camera_tracks"] for m in r["matches"] if m["object_id"] == obj), None) for r in resps]
        present = [t is not None for t in tracks]
        person = {"pairs_present": sum(present), "pairs_missing": 0, "drops": 0, "causes": Counter(),
                  "longest_drop_pairs": 0}
        for a, b in gaps(present):
            before, after = tracks[a - 1], tracks[b + 1]
            ids = {cam: {t[cam] for t in (before, after) if cam in t} for cam in CAMS}
            run = Counter()
            for i in range(a, b + 1):
                r = resps[i]
                (s1, f1), (s2, f2) = (camera_state(ids[c], c, obj, sent[r["pair_id"]], r) for c in CAMS)
                cause = classify(s1, s2)
                run[cause] += 1
                if cause == "pair_fail":
                    foot_src.update(f for f in (f1, f2) if f)
                track_change += sum(1 for st, f in ((s1, f1), (s2, f2)) if st == "missing" and f == "new_track")
            pair_causes.update(run)
            person["causes"].update(run)
            run_causes[run.most_common(1)[0][0]] += 1
            person["pairs_missing"] += b - a + 1
            person["drops"] += 1
            person["longest_drop_pairs"] = max(person["longest_drop_pairs"], b - a + 1)
        per_person[obj] = person
    return {"session": folder.name, "pairs": len(resps), "people": per_person, "pair_causes": pair_causes,
            "drop_causes": run_causes, "pair_fail_foot_src": foot_src, "missing_with_other_unmatched": track_change,
            "settings": resps[0].get("settings", {}) if resps else {}}


def pct(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.0f}%)" if total else "0"


def report(results: list[dict]) -> str:
    lines = []
    for res in results:
        st = res["settings"]
        lines += [f"## {res['session']}", "",
                  f"서버 결과 짝 {res['pairs']}개 · 짝짓기 {st.get('matching_method', '?')} · "
                  f"한 카메라 위치 {'켬' if st.get('single_camera_fallback') else '끔'} · "
                  f"트랙 짝 유지 {'켬' if st.get('track_pair_hold') else '끔'}", "",
                  "| 사람 | 나온 짝 | 빠진 짝 | 끊김 | 가장 긴 끊김(짝) | " + " | ".join(CAUSE_KO[c] for c in CAUSES) + " |",
                  "|---|---|---|---|---|" + "---|" * len(CAUSES)]
        for obj, p in res["people"].items():
            lines.append(f"| #{obj} | {p['pairs_present']} | {p['pairs_missing']} | {p['drops']} | "
                         f"{p['longest_drop_pairs']} | " + " | ".join(str(p['causes'][c]) for c in CAUSES) + " |")
        tp, td = sum(res["pair_causes"].values()), sum(res["drop_causes"].values())
        lines += ["", "| 원인 | 빠진 짝 | 끊김 (구간마다 가장 많은 원인) |", "|---|---|---|"]
        lines += [f"| {CAUSE_KO[c]} | {pct(res['pair_causes'][c], tp)} | {pct(res['drop_causes'][c], td)} |"
                  for c in CAUSES]
        fs = res["pair_fail_foot_src"]
        if fs:
            lines += ["", "서버 짝짓기 실패 짝의 발 위치 출처: " +
                      ", ".join(f"{k} {pct(v, sum(fs.values()))}" for k, v in fs.most_common())]
        lines.append(f"엣지가 보내지 않은 카메라 중 짝 못 지은 다른 사람 트랙이 있던 경우 (트랙 번호 바뀜 의심): "
                     f"{res['missing_with_other_unmatched']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="짝 끊김 원인 나누기 (엣지 놓침 vs 서버 짝짓기 실패)")
    parser.add_argument("folders", nargs="+", type=Path, help="runs/edge/<session_id> 폴더")
    parser.add_argument("--min-pairs", type=int, default=30, help="주요 사람으로 볼 최소 등장 짝 수")
    parser.add_argument("--json", action="store_true", help="표 대신 JSON")
    args = parser.parse_args()
    results = [analyze(f, args.min_pairs) for f in args.folders]
    print(json.dumps(results, ensure_ascii=False, indent=1, default=dict) if args.json else report(results))
