"""짝 끊김 원인 나누기(eval/pair_drops.py): 작은 가짜 기록으로 원인 분류 검사"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from pair_drops import analyze, classify, gaps  # noqa: E402


def test_classify_and_gaps():
    assert classify("unmatched", "unmatched") == "pair_fail"
    assert classify("unmatched", "missing") == "one_cam" == classify("missing", "unmatched")
    assert classify("missing", "missing") == "both_miss"
    assert classify("other", "unmatched") == "id_switch"
    assert gaps([False, True, False, False, True, True, False, True, False]) == [(2, 3), (6, 6)]
    assert gaps([False, False]) == []


def _det(tid, foot_src="ankle"):
    return {"track_id": tid, "cls": "person", "foot_src": foot_src}


def _write(folder, rows):
    """rows: [(cam1 탐지 트랙들, cam2 탐지 트랙들, 짝 [(obj, t1, t2)], unmatched1, unmatched2)]"""
    sent, resp = [], []
    for pid, (c1, c2, matches, u1, u2) in enumerate(rows):
        sent.append({"pair_id": pid, "frames": [{"camera_id": "cam1", "detections": [_det(t) for t in c1]},
                                                 {"camera_id": "cam2", "detections": [_det(t, "box") for t in c2]}]})
        resp.append({"pair_id": pid, "status": "processed", "settings": {},
                     "matches": [{"object_id": o, "cls": "person", "camera_tracks": {"cam1": a, "cam2": b}}
                                 for o, a, b in matches],
                     "unmatched": {"cam1": u1, "cam2": u2}})
    for name, data in (("sent_detections.jsonl", sent), ("responses_detections.jsonl", resp)):
        (folder / name).write_text("".join(json.dumps(x) + "\n" for x in data))


def test_analyze_splits_causes(tmp_path):
    ok = ([1, 2], [5, 6], [(10, 1, 5), (20, 2, 6)], [], [])
    _write(tmp_path, [
        ok,
        ([1, 2], [5, 6], [(20, 2, 6)], [1], [5]),          # #10 두 카메라 다 보냈는데 짝 없음 → pair_fail
        ([1, 2], [6], [(20, 2, 6)], [1], []),               # #10 cam2 트랙 5 없음 → one_cam
        ([2], [6], [(20, 2, 6)], [], []),                   # #10 둘 다 없음 → both_miss
        ([1, 2], [5, 6], [(20, 2, 6), (30, 1, 5)], [], []),  # #10 트랙이 #30 짝에 들어감 → id_switch
        ([1, 2, 7], [6], [(20, 2, 6)], [1, 7], []),         # cam2 없음, cam1 트랙 7 짝 못 지음 → one_cam (+번호 바뀜 의심 0)
        ([1, 2], [6, 8], [(20, 2, 6)], [1], [8]),           # cam2 트랙 5 없고 다른 트랙 8 짝 못 지음 → 번호 바뀜 의심 1
        ok,
    ])
    res = analyze(tmp_path, min_pairs=2)
    p = res["people"][10]
    assert (p["pairs_present"], p["pairs_missing"], p["drops"], p["longest_drop_pairs"]) == (2, 6, 1, 6)
    assert res["pair_causes"] == {"pair_fail": 1, "one_cam": 3, "both_miss": 1, "id_switch": 1}
    assert res["drop_causes"] == {"one_cam": 1}
    assert res["pair_fail_foot_src"] == {"ankle": 1, "box": 1}
    assert res["missing_with_other_unmatched"] == 1
    assert 20 in res["people"] and res["people"][20]["drops"] == 0
