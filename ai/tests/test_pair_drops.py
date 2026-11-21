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


def test_algorithm_replay_count():
    from algorithm_replay import count
    head = "record_type,pair_id,object_id,object2_id,cls,level\n"
    rows = [f"position,{p},1,,person," for p in (10, 11, 14, 15)]                 # 12·13 빠짐 → 끊김 1
    rows += [f"position,{p},2,,person," for p in (10, 11, 12, 13, 14, 15)]
    rows += ["position,10,9,,person,"]                                            # 한 번만 나온 번호
    rows += [f"risk,{p},1,2,,warning" for p in (10, 11, 14)]                       # 경고 10~11, 14 → 구간 2
    rows += ["risk,15,1,2,,safe"]
    c = count(head + "\n".join(rows) + "\n", [10, 11, 12, 13, 14, 15], min_pairs=3)
    assert c == {"people": 2, "short_ids": 1, "pairs_missing": 2, "drops": 1, "longest_drop_pairs": 2,
                 "warning_episodes": 2, "warning_pairs": 3}


def test_chair_hold_fills_gaps_and_merges_episodes():
    from chair_hold import episodes, held_positions
    times = [0, 100, 200, 300, 400, 1600, 1700]
    assert held_positions({0: (1, 1), 3: (2, 2)}, times, 0.15) == {0: (1, 1), 1: (1, 1), 3: (2, 2), 4: (2, 2)}
    pos = {1: {i: (0.0, 0.0) for i in range(7)},                    # 사람은 계속 그 자리
           2: {0: (0.5, 0), 2: (0.5, 0), 3: (1.5, 0), 5: (0.5, 0)}}  # 의자: 1번 빠짐, 3번 1m 밖, 4번 빠짐
    cls = {1: "person", 2: "chair"}
    assert episodes(pos, cls, times, hold_s=0) == 3                  # 0 / 2 / 5
    assert episodes(pos, cls, times, hold_s=0.15) == 2               # 0~2 이어짐 / 5 (3번은 1m 밖)
    assert episodes(pos, cls, times, hold_s=0.15, alert_hold_s=1.0) == 2   # 2→5 사이 1.4초 > 1초
    assert episodes(pos, cls, times, hold_s=0.15, alert_hold_s=1.5) == 1


def test_missing_chair_uses_requested_class_for_new_track():
    from pair_drops import camera_state
    def state(cls):
        sent = {"frames": [{"camera_id": "cam1", "detections": [
            {"track_id": 8, "cls": cls}]}]}
        resp = {"matches": [], "unmatched": {"cam1": [8]}}
        return camera_state({5}, "cam1", 10, sent, resp, "chair")
    assert state("chair") == ("missing", "new_track")
    assert state("person") == ("missing", None)
