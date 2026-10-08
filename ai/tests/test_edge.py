"""
엣지 코드 테스트 (CI에서 PR마다 실행)

YOLO·torch 없이 돌 수 있는 부분만 검사한다.
  - unity_calibration: Unity 카메라 → OpenCV 캘리브레이션 변환이 정확한지 (투영 → 삼각측량 왕복)
  - server_client: dry-run 저장, 대기열이 꽉 차도 메시지를 버리지 않는지
  - eval_position: 서버 응답과 정답 비교 계산

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

from eval_position import evaluate  # noqa: E402
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
