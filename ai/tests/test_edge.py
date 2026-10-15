"""
엣지 코드 테스트 (CI에서 PR마다 실행)

YOLO·torch 없이 돌 수 있는 부분만 검사한다.
  - unity_calibration: Unity 카메라 → OpenCV 캘리브레이션 변환이 정확한지 (투영 → 삼각측량 왕복)
  - server_client: dry-run 저장, 대기열이 꽉 차도 메시지를 버리지 않는지
  - eval_position: 서버 응답과 정답 비교 계산
  - bundle: session_id 규칙, 서버로 보내는 탐지 묶음 형식
  - realtime: 두 카메라 프레임을 가장 가까운 것끼리 짝짓는지
  - feet: 발 위치(foot)와 좌우 발목(ankles)
  - run_experiment·crossing: 다른 조건 결과(results.csv) 변환, 교차 구간 지표

실행 (레포 루트에서): python -m pytest ai/tests -q
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR / "edge"))
sys.path.insert(0, str(AI_DIR / "eval"))

import pytest  # noqa: E402
from bundle import build_bundle, build_frame, check_session_id, clean_detections  # noqa: E402
import camera_source  # noqa: E402
from camera_source import Frame  # noqa: E402
from eval_position import evaluate  # noqa: E402
from feet import LEFT_ANKLE, RIGHT_ANKLE, attach_feet  # noqa: E402
from realtime import Recorder  # noqa: E402
from server_client import ServerClient  # noqa: E402
from unity_calibration import load_calibrations, project, projection, unity_to_world  # noqa: E402

# 실제 Unity 강의실 카메라 값 (unity-classroom-03)
CAMERAS = {
    "unity_version": "6000.3.8f1",
    "cameras": [
        {"camera_id": "cam1", "image_size": [1920, 1080], "vertical_fov_deg": 46.8, "position": [0.3, 2, 0.3],
         "rotation_quat": [0.195, 0.4233, -0.0938, 0.8798], "rotation_euler_deg": [25, 51.3892, 0]},
        {"camera_id": "cam2", "image_size": [1920, 1080], "vertical_fov_deg": 46.8, "position": [10.28, 2, 0.3],
         "rotation_quat": [0.195, -0.4233, 0.0938, 0.8798], "rotation_euler_deg": [25, 308.6108, 0]},
    ],
}


def make_scene(tmp_path: Path) -> Path:
    folder = tmp_path / "unity-test-01"
    folder.mkdir()
    (folder / "cameras.json").write_text(json.dumps(CAMERAS), encoding="utf-8")
    return folder


def test_unity_to_world_swaps_y_and_z():
    assert unity_to_world([1.0, 2.0, 3.0]) == [1.0, 3.0, 2.0]


def test_calibration_format_matches_backend_schema(tmp_path):
    calibs = load_calibrations(make_scene(tmp_path), session_id="unity-test-01-run1")
    for cam in ("cam1", "cam2"):
        c = calibs[cam]
        assert c["session_id"] == "unity-test-01-run1"
        assert c["method"] == "unity-gt"
        assert c["image_size"] == [1920, 1080]
        assert len(c["K"]) == 3 and all(len(row) == 3 for row in c["K"])
        assert len(c["dist"]) == 5 and len(c["rvec"]) == 3 and len(c["tvec"]) == 3
        assert abs(c["K"][0][2] - 960) < 1e-6 and abs(c["K"][1][2] - 540) < 1e-6


def test_projection_and_triangulation_round_trip(tmp_path):
    """방 안 여러 바닥 점을 두 카메라에 투영했다가 다시 삼각측량하면 원래 점이 나와야 한다"""
    calibs = load_calibrations(make_scene(tmp_path))
    P = {c: projection(calibs[c]) for c in calibs}
    for x, z in [(2.0, 2.0), (5.3, 3.4), (8.6, 2.0), (5.3, 7.6)]:
        X = np.array(unity_to_world([x, 0.0, z]))
        uv = {}
        for cam in P:
            uv[cam], depth = project(P[cam], X)
            assert depth > 0, f"{cam} 뒤쪽에 있음: {(x, z)}"
        h = cv2.triangulatePoints(P["cam1"], P["cam2"], uv["cam1"].reshape(2, 1), uv["cam2"].reshape(2, 1))
        assert np.linalg.norm((h[:3] / h[3]).ravel() - X) < 1e-4


def test_camera_looks_down_with_y_axis_pointing_down(tmp_path):
    """바닥 점은 화면 아래쪽, 높은 점은 화면 위쪽에 찍혀야 한다 (Unity y-up → OpenCV y-down 변환 확인)"""
    calibs = load_calibrations(make_scene(tmp_path))
    P = projection(calibs["cam1"])
    floor, _ = project(P, np.array(unity_to_world([3.0, 0.0, 3.0])))
    head, _ = project(P, np.array(unity_to_world([3.0, 1.7, 3.0])))
    assert floor[1] > head[1]


def test_server_client_dry_run_keeps_every_message(tmp_path):
    client = ServerClient(None, tmp_path, dry_run=True, max_queue=5)
    for i in range(50):
        client.send({"pair_id": i}, "/detections")
        client.send({"frame": i}, "/ground-truth")
    client.close()
    assert len((tmp_path / "sent_detections.jsonl").read_text().splitlines()) == 50
    assert len((tmp_path / "sent_ground-truth.jsonl").read_text().splitlines()) == 50
    assert client.stats["dropped"] == 0


def test_eval_position_compares_server_world_with_ground_truth(tmp_path):
    run_dir, gt_dir = tmp_path / "run", tmp_path / "gt"
    run_dir.mkdir()
    gt_dir.mkdir()
    (gt_dir / "frames.jsonl").write_text(json.dumps({
        "frame": 1, "ts": 0, "objects": [{"object_id": "person_1", "cls": "person", "world": [2.0, 0.0, 3.0],
                                           "bbox": {"cam1": [0, 0, 10, 10], "cam2": [0, 0, 10, 10]}}]}) + "\n")
    (run_dir / "responses_detections.jsonl").write_text(json.dumps({
        "pair_id": 1, "matches": [{"object_id": 1, "cls": "person", "world": {"x": 2.1, "y": 3.0, "z": 0.0},
                                    "epipolar_error_px": 5.0}]}) + "\n")
    rows, visible = evaluate(run_dir, gt_dir)
    assert len(rows) == 1 and visible == {"person": 1}
    assert abs(rows[0]["floor_err_cm"] - 10.0) < 0.1
    assert abs(rows[0]["dx_cm"] - 10.0) < 0.1


def test_pipeline_diagram_marks_changed_settings():
    import pipeline_diagram as pd
    rows = [{"pack": "s1", "cls": "person", "ok": 9, "chance": 10, "mean_cm": 6.0, "mismatch_rate": 0.0}]
    meta = {"packs": ["s1"], "pack_runs": {"s1": {"edge": {"model": "coco", "imgsz": 1280, "foot": "ankle"}}},
            "health": {"commit": "a", "max_epipolar_error_px": 50.0, "bbox_position_method": "triangulate"}}
    before = pd.describe(meta, rows)
    meta["health"]["bbox_position_method"] = "plane"
    text = pd.mermaid(pd.describe(meta, rows), before)
    assert "삼각측량 → <b>바닥 평면 교점</b>" in text
    assert "class position changed" in text
    assert "class" not in pd.mermaid(before, before).split("classDef")[1].split("\n", 1)[1]


def test_session_id_rule_and_list(tmp_path):
    for ok in ("classroom-1014-s2-t1", "diy-1014-s10-t3-v2"):
        assert check_session_id(ok) == ok
    for bad in ("classroom-s1", "lab-1014-s1-t1", "classroom-1014-s1", "classroom-1014-s1-t1-run1"):
        with pytest.raises(SystemExit):
            check_session_id(bad)
    sessions = tmp_path / "classroom-1014.txt"
    sessions.write_text("# 강의실\nclassroom-1014-s1-t1\n\nclassroom-1014-s2-t1\n", encoding="utf-8")
    assert check_session_id("classroom-1014-s2-t1", str(sessions))
    with pytest.raises(SystemExit):
        check_session_id("classroom-1014-s3-t1", str(sessions))


def test_bundle_follows_server_rules():
    dets = [
        {"track_id": 1, "cls": "person", "conf": 0.9, "bbox": [-5, 10, 300, 1085], "foot": [150, 1080], "foot_src": "ankle"},
        {"track_id": None, "cls": "person", "conf": 0.9, "bbox": [0, 0, 10, 10]},   # 추적 번호 없음
        {"track_id": 2, "cls": "tv", "conf": 0.9, "bbox": [0, 0, 10, 10]},          # 서버가 모르는 클래스
        {"track_id": 3, "cls": "chair", "conf": 0.9, "bbox": [1919.5, 0, 1925, 10]},  # 잘라내면 폭 1px 미만
    ]
    kept, removed = clean_detections(dets, 1920, 1080)
    assert removed == 3 and len(kept) == 1
    assert kept[0]["bbox"] == [0.0, 10.0, 300.0, 1080.0]
    assert kept[0]["foot"][1] < 1080                     # 서버는 foot < 이미지 크기 를 요구
    frames = [build_frame("cam1", 7, 1000, (1920, 1080), kept), build_frame("cam2", 7, 1030, (1920, 1080), [])]
    bundle = build_bundle("classroom-1014-s1-t1", 7, frames)
    assert bundle["calibration_profile"] == "basic" and bundle["pair_id"] == 7
    assert bundle["max_sync_delta_ms"] == 50
    assert [f["camera_id"] for f in bundle["frames"]] == ["cam1", "cam2"]
    assert set(bundle["frames"][0]) == {"camera_id", "frame_id", "ts", "image_size", "detections"}


def test_frame_carries_pts_and_receive_times():
    frame = build_frame("cam1", 1, 1000, (1920, 1080), [], pts_ms=12.25, recv_ms=1010)
    assert frame["pts_ms"] == 12.25
    assert frame["recv_ms"] == 1010


def test_tapo_credentials_are_url_encoded(monkeypatch):
    monkeypatch.setattr(camera_source, "_credentials", ("user@name", "p:a/ss"))
    target, shown, kind = camera_source.resolve("tapo:192.168.0.10")
    assert target == "rtsp://user%40name:p%3Aa%2Fss@192.168.0.10:554/stream1"
    assert shown == "rtsp://192.168.0.10:554/stream1"
    assert kind == "rtsp"


def test_recorder_pairs_nearest_frames(tmp_path):
    """cam1 30fps, cam2 15fps: cam2 프레임마다 시각이 가장 가까운 cam1 프레임과 짝지어야 한다"""
    image = np.zeros((4, 4, 3), np.uint8)
    pairs = []
    rec = Recorder(tmp_path, tol_ms=50, cam2_offset_ms=0, jpeg_quality=90, save=False,
                   on_pair=lambda n, f1, f2, dt: pairs.append((f1.seq, f2.seq, dt)))
    events = [(round(i * 33.3), "cam1", i) for i in range(60)] + [(round(i * 66.7 + 20), "cam2", i) for i in range(30)]
    for t, cam, seq in sorted(events):
        rec.add(Frame(cam, seq, 0.0, 1_000_000 + t, image))
    rec.close()
    assert len(pairs) >= 29
    assert max(abs(dt) for _, _, dt in pairs) <= 17          # 30fps 간격(33ms)의 절반 이하
    assert all(f1 in (2 * f2, 2 * f2 + 1) for f1, f2, _ in pairs)


def _pose(box, left, right):
    """포즈 결과 하나: 17개 키포인트 중 발목만 값을 넣는다. left/right = (x, y, conf)"""
    kps = [(0.0, 0.0, 0.0)] * 17
    kps[LEFT_ANKLE], kps[RIGHT_ANKLE] = left, right
    return (box, kps)


def test_attach_feet_sends_left_and_right_ankles():
    box = [100.0, 100.0, 200.0, 400.0]
    both, one, none = (
        attach_feet([{"cls": "person", "bbox": box}], [_pose(box, left, right)])[0]
        for left, right in (((130, 390, 0.9), (170, 395, 0.8)),     # 두 발목 보임
                            ((130, 390, 0.9), (170, 395, 0.2)),     # 오른발목 가려짐
                            ((130, 390, 0.1), (170, 395, 0.2))))    # 둘 다 안 보임
    assert both["foot_src"] == "ankle" and both["foot"] == [150.0, 392.5]
    assert both["ankles"] == {"left": [130, 390, 0.9], "right": [170, 395, 0.8]}
    assert one["foot_src"] == "box" and one["ankles"] == {"left": [130, 390, 0.9], "right": None}
    assert none["foot_src"] == "box" and "ankles" not in none
    chair = attach_feet([{"cls": "chair", "bbox": box}], [_pose(box, (1, 1, 0.9), (2, 2, 0.9))])[0]
    assert "ankles" not in chair                              # 사람이 아니면 발목 없음
    far = attach_feet([{"cls": "person", "bbox": box}], [_pose([500, 500, 600, 800], (1, 1, 0.9), (2, 2, 0.9))])[0]
    assert "ankles" not in far                                # 겹치는 포즈가 없으면 발목 없음


def test_bundle_keeps_ankles_inside_image():
    d = {"track_id": 1, "cls": "person", "conf": 0.9, "bbox": [10, 10, 100, 1080], "foot": [50, 1080],
         "foot_src": "ankle", "ankles": {"left": [40, 1085, 0.9], "right": None}}
    kept, _ = clean_detections([d], 1920, 1080)
    assert kept[0]["ankles"]["left"][1] < 1080 and kept[0]["ankles"]["left"][2] == 0.9
    assert kept[0]["ankles"]["right"] is None


def test_results_csv_becomes_responses(tmp_path):
    """recompute 결과(results.csv)를 카메라별 ts 로 짝 번호에 붙이고, 같은 물체는 한 번만 넣는다"""
    import gzip
    import run_experiment as rx
    pack = tmp_path / "pack"
    pack.mkdir()
    bundles = [{"pair_id": 1, "frames": [{"camera_id": "cam1", "ts": 1000}, {"camera_id": "cam2", "ts": 1010}]},
               {"pair_id": 2, "frames": [{"camera_id": "cam1", "ts": 1100}, {"camera_id": "cam2", "ts": 1105}]}]
    with gzip.open(pack / "detections.jsonl.gz", "wt", encoding="utf-8") as f:
        f.writelines(json.dumps(b) + "\n" for b in bundles)
    text = "\n".join(["record_type,timestamp_ms,object_id,object2_id,cls,x,y,z,distance_m,ttc_s,level,settings",
                      "position,1000,7,,person,1.0,2.0,0.1,,,,{}",
                      "position,1010,7,,person,1.0,2.0,0.1,,,,{}",       # 같은 묶음의 cam2 줄
                      "risk,1000,7,8,,,,,0.8,,warning,{}"])
    resp = rx.results_to_responses(text, pack)
    assert [r["pair_id"] for r in resp] == [1, 2]
    assert resp[0]["matches"] == [{"object_id": 7, "cls": "person", "world": {"x": 1.0, "y": 2.0, "z": 0.1}}]
    assert resp[1]["matches"] == []


def test_crossing_metrics_counts_close_frames():
    import crossing
    gt = {f: {"objects": [{"object_id": "a", "cls": "person", "world": [0.0, 0, 0.0]},
                          {"object_id": "b", "cls": "person", "world": [d, 0, 0.0]}]}
          for f, d in ((1, 2.0), (2, 0.8), (3, 0.5), (4, 0.5))}
    ok = lambda f, o, x, sid: {"frame": f, "cls": "person", "status": "ok", "object_id": o,
                               "server_object_id": sid, "est_x": x, "est_y": 0.0}
    rows = [ok(1, "a", 0.0, 1), ok(1, "b", 0.9, 2),          # 정답 2m 인데 서버 0.9m → 오경보
            ok(2, "a", 0.0, 1), ok(2, "b", 0.8, 2),          # 0.8m: 둘 다 추적, 경고 맞음
            ok(3, "a", 0.0, 1),                               # 0.5m: b 놓침 → 경고 놓침
            ok(4, "a", 0.0, 3), ok(4, "b", 0.6, 2)]           # a 의 ID 가 1 → 3 으로 바뀜 (가까운 구간)
    m = crossing.crossing_metrics(rows, gt)
    assert (m["near_1m"], m["near_06m"]) == (3, 2)
    assert m["both_1m"] == round(2 / 3, 4) and m["both_06m"] == 0.5
    assert (m["warn_tp"], m["warn_fn"], m["warn_fp"]) == (2, 1, 1)
    assert m["id_switches_near"] == 1
    assert m["dist_err_cm"] == 5.0                            # (0 + 10) / 2
    one = {1: {"objects": [{"object_id": "a", "cls": "person", "world": [0, 0, 0]}]}}
    assert crossing.crossing_metrics([], one) is None          # 사람 한 명이면 계산 안 함


def test_experiment_conditions_and_feature_labels():
    import run_experiment as rx
    assert rx.build_conditions("basic", "baseline,improved", None) == ["basic/baseline", "basic/improved"]
    assert rx.build_conditions("basic", "ablation", None) == [f"basic/{a}" for a in rx.ABLATION]
    both = rx.build_conditions("all", "baseline,f-g", None)
    assert both == ["basic/baseline", "basic/f-g", "precise/baseline", "precise/f-g"]
    assert rx.build_conditions("basic", "f-g", None)[0] == "basic/baseline"     # 탐지를 보내는 조건은 항상 포함
    assert rx.build_conditions("basic", "x", "all") == rx.ALL_CONDITIONS         # 예전 --conditions 가 우선
    with pytest.raises(SystemExit):
        rx.build_conditions("basic", "fast", None)
    assert rx.cond_label("basic/f-gk") == "+바닥+칼만"
    assert rx.cond_label("precise/improved") == "정밀 · 개선(전체)"
    assert rx.cond_label("basic/f-cdef") == "+바닥추적+한카메라+시간보정+경고유지"


def test_results_csv_with_pair_id_keeps_every_person(tmp_path):
    """#58 이후 csv 는 pair_id 가 있고 한 사람당 한 줄 → 번호가 겹쳐도 사람을 빼지 않는다"""
    import gzip
    import run_experiment as rx
    pack = tmp_path / "pack"
    pack.mkdir()
    with gzip.open(pack / "detections.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"pair_id": 3, "frames": [{"camera_id": "cam1", "ts": 1}, {"camera_id": "cam2", "ts": 2}]}) + "\n")
    text = "\n".join(["record_type,pair_id,frame_id,timestamp_ms,object_id,object2_id,cls,x,y,z,distance_m,ttc_s,level,settings",
                      "position,3,3,1,5,,person,1.0,2.0,0.1,,,,{}",
                      "position,3,3,1,5,,person,4.0,2.0,0.1,,,,{}"])
    resp = rx.results_to_responses(text, pack)
    assert len(resp[0]["matches"]) == 2


def test_crossing_uses_server_warning_levels_and_band():
    """서버가 경고 단계(F)를 주면 그걸로 채점하고, 0.9~1.1m 여유 구간은 따로 뺀 개수도 센다"""
    import crossing
    gt = {f: {"objects": [{"object_id": "a", "cls": "person", "world": [0.0, 0, 0.0]},
                          {"object_id": "b", "cls": "person", "world": [d, 0, 0.0]}]}
          for f, d in ((1, 0.95), (2, 1.05), (3, 2.0))}
    ok = lambda f, o, x, sid: {"frame": f, "cls": "person", "status": "ok", "object_id": o,
                               "server_object_id": sid, "est_x": x, "est_y": 0.0}
    rows = [ok(1, "a", 0.0, 1), ok(1, "b", 1.02, 2),      # 정답 0.95m, 서버 1.02m → 거리로는 놓침
            ok(2, "a", 0.0, 1), ok(2, "b", 1.05, 2),      # 정답 1.05m, 서버 1.05m → 맞게 경고 없음
            ok(3, "a", 0.0, 1), ok(3, "b", 1.9, 2)]
    plain = crossing.crossing_metrics(rows, gt)
    assert (plain["warn_tp"], plain["warn_fn"], plain["warn_fp"]) == (0, 1, 0)
    assert (plain["warn_fn_band"], plain["warn_fp_band"]) == (0, 0)       # 놓친 1개는 여유 구간 안
    # 서버 경고 유지(F): 1번 프레임은 경고, 2번 프레임도 아직 경고 유지 → 맞음 1, 오경보 1 (여유 구간 안)
    risks = crossing.risk_levels([{"pair_id": 1, "risks": [{"object1_id": 1, "object2_id": 2, "level": "warning"}]},
                                  {"pair_id": 2, "risks": [{"object1_id": 1, "object2_id": 2, "level": "warning"}]},
                                  {"pair_id": 3, "risks": [{"object1_id": 1, "object2_id": 2, "level": "safe"}]}])
    held = crossing.crossing_metrics(rows, gt, risks)
    assert (held["warn_tp"], held["warn_fn"], held["warn_fp"]) == (1, 0, 1)
    assert (held["warn_fn_band"], held["warn_fp_band"]) == (0, 0)
    # 깜빡임: 정답은 1번→2번 프레임에서 꺼짐(1번). 서버 거리는 계속 꺼짐(0번), 경고 유지는 2→3번에서 꺼짐(1번)
    assert (plain["warn_toggles"], plain["gt_toggles"]) == (0, 1)
    assert (held["warn_toggles"], held["gt_toggles"]) == (1, 1)


def test_results_csv_risk_rows_become_response_risks(tmp_path):
    import gzip
    import run_experiment as rx
    pack = tmp_path / "pack"
    pack.mkdir()
    with gzip.open(pack / "detections.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"pair_id": 3, "frames": [{"camera_id": "cam1", "ts": 1}, {"camera_id": "cam2", "ts": 2}]}) + "\n")
    text = "\n".join(["record_type,pair_id,frame_id,timestamp_ms,object_id,object2_id,cls,x,y,z,distance_m,ttc_s,level,settings",
                      "position,3,3,1,5,,person,1.0,2.0,0.1,,,,{}",
                      "risk,3,,2,5,6,,,,,1.04,,warning,{}"])
    resp = rx.results_to_responses(text, pack)
    assert resp[0]["risks"] == [{"object1_id": 5, "object2_id": 6, "level": "warning", "distance_m": 1.04}]


def test_shift_pack_makes_cam2_late(tmp_path, monkeypatch):
    """E 실험용 pack: 묶음 k 에 cam2 의 k-1 번째 사진을 붙이고, 서버 시간차 허용을 넓힌다"""
    import gzip
    import types
    import run_experiment as rx
    monkeypatch.setattr(rx, "PACK_DIR", tmp_path)
    src = tmp_path / "base"
    src.mkdir()
    bundles = [{"pair_id": k, "frames": [{"camera_id": "cam1", "ts": 100 * k, "detections": []},
                                         {"camera_id": "cam2", "ts": 100 * k, "detections": [{"track_id": k}]}]}
               for k in range(1, 4)]
    with gzip.open(src / "detections.jsonl.gz", "wt", encoding="utf-8") as f:
        f.writelines(json.dumps(b) + "\n" for b in bundles)
    (src / "meta.json").write_text(json.dumps({"name": "base"}), encoding="utf-8")
    (src / "calibration.json").write_text("{}", encoding="utf-8")
    rx.shift_pack(types.SimpleNamespace(source="base", name="late", cam2_frames=1, force=False))
    shifted = rx.read_jsonl(tmp_path / "late" / "detections.jsonl.gz")
    assert [b["pair_id"] for b in shifted] == [2, 3]
    assert [(b["frames"][0]["ts"], b["frames"][1]["ts"]) for b in shifted] == [(200, 100), (300, 200)]
    assert shifted[0]["frames"][1]["detections"] == [{"track_id": 1}]
    meta = json.loads((tmp_path / "late" / "meta.json").read_text(encoding="utf-8"))
    assert meta["max_sync_delta_ms"] == 150 and meta["cam2_late_frames"] == 1


def _down_looking_calib():
    """(0, -3, 2)에서 바닥 원점을 내려다보는 카메라 두 대 (cam2는 x로 1m 옆)"""
    out = {}
    for cam, cx in (("cam1", 0.0), ("cam2", 1.0)):
        center, target = np.array([cx, -3.0, 2.0]), np.array([cx, 0.0, 0.0])
        forward = (target - center) / np.linalg.norm(target - center)
        right = np.cross(forward, [0.0, 0.0, 1.0])
        right /= np.linalg.norm(right)
        rotation = np.vstack([right, np.cross(forward, right), forward])
        rvec, _ = cv2.Rodrigues(rotation)
        body = {"method": "test", "image_size": [1920, 1080], "K": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
                "dist": [0, 0, 0, 0, 0], "rvec": rvec.reshape(3).tolist(), "tvec": (-rotation @ center).tolist(),
                "reproj_error_px": 0}
        out[cam] = {"basic": body, "precise": body}
    return out


def test_real_pack_keeps_all_detections_and_scores_only_gt_frames(tmp_path):
    """실측 pack: 탐지는 전부 넣고 정답은 일부 프레임만. 채점은 정답 프레임만 한다"""
    import run_experiment as rx
    import real_pack
    edge = tmp_path / "edge"
    edge.mkdir()
    rx.write_jsonl(edge / "sent_detections.jsonl",
                   [{"session_id": "s", "pair_id": p, "frames": []} for p in (1, 2, 3)])
    (tmp_path / "calib.json").write_text(json.dumps(_down_looking_calib()), encoding="utf-8")
    rx.write_jsonl(tmp_path / "gt.jsonl", [{"frame": 2, "objects": [
        {"object_id": "person_1", "cls": "person", "rel": [0.5, 0.5, 0]},
        {"object_id": "person_2", "cls": "person", "rel": [0.0, -10.0, 0]},    # 카메라 뒤
        {"object_id": "chair_1", "cls": "chair", "rel": [1.0, 0.0, 0]}]}])
    pack = real_pack.make_real_pack(edge, tmp_path / "gt.jsonl", tmp_path / "calib.json", "real-x",
                                    real_pack.parse_exclude("2:chair_1"), pack_root=tmp_path / "packs")
    assert len(rx.read_jsonl(pack / "detections.jsonl.gz")) == 3
    assert "session_id" not in rx.read_jsonl(pack / "detections.jsonl.gz")[0]
    frames = rx.read_jsonl(pack / "frames.jsonl.gz")
    objects = {o["object_id"]: o for o in frames[0]["objects"]}
    assert set(objects) == {"person_1", "person_2"}                          # 뺀 의자 없음
    assert objects["person_1"]["world"] == [0.5, 0, 0.5]                     # 바닥 (x, y) → Unity [x, 0, y]
    assert set(objects["person_1"]["bbox"]) == {"cam1", "cam2"}
    assert objects["person_2"]["bbox"] == {}
    meta = json.loads((pack / "meta.json").read_text(encoding="utf-8"))
    assert meta["sparse_gt"] and meta["gt_frames"] == [2] and meta["excluded_count"] == 1

    out = tmp_path / "out"
    out.mkdir()
    hit = {"object_id": 7, "cls": "person", "world": {"x": 0.52, "y": 0.5, "z": 0.1}}
    rx.write_jsonl(out / "responses_detections.jsonl",
                   [{"pair_id": 1, "matches": [hit]}, {"pair_id": 2, "matches": [hit]}, {"pair_id": 3, "matches": [hit]}])
    rows, visible = rx.score(out, pack, 50.0)
    assert [(r["frame"], r["status"]) for r in rows] == [(2, "ok")]          # 정답 없는 1·3 프레임은 채점 안 함
    assert visible == {"person": 1}
    assert not (out / "gt_only").exists()


def test_real_pack_refuses_gt_frame_missing_from_detections(tmp_path):
    import run_experiment as rx
    import real_pack
    edge = tmp_path / "edge"
    edge.mkdir()
    rx.write_jsonl(edge / "sent_detections.jsonl", [{"pair_id": 1, "frames": []}])
    (tmp_path / "calib.json").write_text(json.dumps(_down_looking_calib()), encoding="utf-8")
    rx.write_jsonl(tmp_path / "gt.jsonl", [{"frame": 5, "objects": []}])
    with pytest.raises(SystemExit):
        real_pack.make_real_pack(edge, tmp_path / "gt.jsonl", tmp_path / "calib.json", "real-y", set(),
                                 pack_root=tmp_path / "packs")
