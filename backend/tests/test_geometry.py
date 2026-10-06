import numpy as np

import backend.geometry as geometry
from backend.geometry import Calibration, foot_point, fundamental_matrix, match_class, triangulate, undistort


def calibration(translation):
    return Calibration(K=np.array([[1000.0, 0, 960], [0, 1000.0, 540], [0, 0, 1]]),
                       dist=np.zeros(5), R=np.eye(3), t=np.asarray(translation, dtype=float))


def test_foot_point_is_bbox_bottom_center():
    assert foot_point([10, 20, 30, 80]) == (20, 80)


def test_undistort_and_triangulate_with_sub_centimeter_error():
    left, right = calibration([0, 0, 0]), calibration([-1, 0, 0])
    expected = np.array([0.25, 0.1, 10.0])

    def project(c):
        camera_point = c.R @ expected + c.t
        pixel = c.K @ camera_point
        return pixel[:2] / pixel[2]

    p1, p2 = undistort(project(left), left), undistort(project(right), right)
    actual = triangulate(p1, p2, left, right)
    assert np.linalg.norm(actual - expected) < 0.01


def test_epipolar_matching_rejects_wrong_row():
    left, right = calibration([0, 0, 0]), calibration([-1, 0, 0])
    essential = fundamental_matrix(left, right)
    matches = match_class([np.array([0.0, 0.0])],
                          [np.array([-0.1, 0.0]), np.array([-0.1, 0.1])],
                          essential, pixel_scale=1000, max_error_px=5)
    assert matches == [(0, 0, 0.0)]


def test_epipolar_matching_excludes_pair_rejected_by_height():
    left, right = calibration([0, 0, 0]), calibration([-1, 0, 0])
    essential = fundamental_matrix(left, right)
    matches = match_class(
        [np.array([0.0, 0.0])],
        [np.array([-0.1, 0.0])],
        essential,
        pixel_scale=1000,
        max_error_px=50,
        pair_is_valid=lambda _row, _col: False,
    )
    assert matches == []


def test_epipolar_threshold_is_applied_before_hungarian(monkeypatch):
    errors = {
        (0, 0): 1.0,
        (0, 1): 4.0,
        (1, 0): 4.0,
        (1, 1): 6.0,
    }
    monkeypatch.setattr(
        geometry,
        "symmetric_epipolar_distance",
        lambda left, right, _essential: errors[(int(left[0]), int(right[0]))],
    )

    matches = match_class(
        [np.array([0.0, 0.0]), np.array([1.0, 0.0])],
        [np.array([0.0, 0.0]), np.array([1.0, 0.0])],
        np.eye(3),
        pixel_scale=1,
        max_error_px=5,
    )

    assert matches == [(0, 1, 4.0), (1, 0, 4.0)]


def test_height_check_skips_pair_over_epipolar_threshold(monkeypatch):
    monkeypatch.setattr(geometry, "symmetric_epipolar_distance", lambda *_args: 100.0)
    checked_pairs = []

    matches = match_class(
        [np.array([0.0, 0.0])],
        [np.array([0.0, 0.0])],
        np.eye(3),
        pixel_scale=1,
        max_error_px=10,
        pair_is_valid=lambda row, col: checked_pairs.append((row, col)) or True,
    )

    assert matches == []
    assert checked_pairs == []
