import sys
from pathlib import Path

import cv2
import numpy as np

CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "calibration"
sys.path.insert(0, str(CALIBRATION_DIR))

from calibrate_grid import solve  # noqa: E402
from detect_aruco import marker_object_points  # noqa: E402


def test_basic_marker_uses_measured_176mm_size():
    points = marker_object_points()
    assert np.isclose(np.ptp(points[:, 0]), 0.176)
    assert np.isclose(np.ptp(points[:, 1]), 0.176)


def test_multi_point_pnp_and_held_out_height_validation():
    K = np.array([[1000.0, 0, 960], [0, 1000.0, 540], [0, 0, 1]])
    dist = np.zeros(5)
    rvec = np.array([np.pi, 0, 0], dtype=float)
    tvec = np.array([0, 0, 5], dtype=float)
    worlds = [(-2, -1, 0), (0, -1, 0), (2, -1, 0),
              (-2, 1, 0), (0, 1, 0), (2, 1, 0),
              (3, 0, 0), (1.5, -0.5, 1)]
    projected, _ = cv2.projectPoints(np.asarray(worlds, dtype=float), rvec, tvec, K, dist)
    centers = {index: point for index, point in enumerate(projected.reshape(-1, 2))}
    points = {index: {"marker_id": index, "role": "pnp" if index < 6 else "validation",
                      "world": list(world)} for index, world in enumerate(worlds)}

    _, _, reproj, validation, errors = solve(points, centers, (1920, 1080), K, dist)

    assert reproj < 1e-5
    assert len(validation) == 2
    assert max(errors) < 1e-4


def test_basic_from_precise_skips_single_marker(tmp_path, monkeypatch):
    import json
    import build_calibration as build

    intrinsic = tmp_path / "intrinsic.json"
    intrinsic.write_text(json.dumps({"K": np.eye(3).tolist(), "dist": [0.0] * 5, "image_size": [1920, 1080]}))
    output = tmp_path / "calib.json"
    monkeypatch.setattr(build, "load_points", lambda path: {})
    monkeypatch.setattr(build, "detect_centers", lambda images, best: ({}, {}, (1920, 1080)))
    monkeypatch.setattr(build, "solve", lambda *args: (np.array([1.0, 2, 3]), np.array([4.0, 5, 6]), 0.5,
                                                       [{"marker_id": 6}], np.array([1.0])))
    def single_marker(*args):
        raise AssertionError("단일 마커 계산을 부르면 안 됨")
    monkeypatch.setattr(build, "estimate_extrinsics", single_marker)
    monkeypatch.setattr(sys, "argv", ["build", "--run", str(tmp_path), "--points", "p.json",
                                      "--cam1-intrinsics", str(intrinsic), "--cam2-intrinsics", str(intrinsic),
                                      "--output", str(output), "--basic-from-precise"])
    build.main()
    saved = json.loads(output.read_text())
    for camera in ("cam1", "cam2"):
        basic, precise = saved[camera]["basic"], saved[camera]["precise"]
        assert basic["calibration_profile"] == "basic"
        assert (basic["rvec"], basic["tvec"], basic["reproj_error_px"]) == (precise["rvec"], precise["tvec"], 0.5)
        assert "validation_rmse_cm" not in basic
