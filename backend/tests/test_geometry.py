import numpy as np

import backend.geometry as geometry
from backend.geometry import (Calibration, combine_plane_positions, complete_box_foot, foot_point, fundamental_matrix,
                              in_front_of_both, match_by_cost, match_class, position_on_plane,
                              triangulate, undistort)


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


def test_position_on_plane_intersects_world_height():
    camera = Calibration(K=np.eye(3), dist=np.zeros(5), R=np.eye(3), t=np.array([0.0, 0.0, -2.0]))

    world = position_on_plane(np.array([0.25, -0.5]), camera, plane_z=4.0)

    assert np.allclose(world, [0.5, -1.0, 4.0])


def test_position_on_plane_rejects_intersection_behind_camera():
    camera = Calibration(K=np.eye(3), dist=np.zeros(5), R=np.eye(3), t=np.zeros(3))

    with np.testing.assert_raises_regex(ValueError, "behind the camera"):
        position_on_plane(np.array([0.0, 0.0]), camera, plane_z=-1.0)


def test_in_front_of_both_cameras():
    left, right = calibration([0, 0, 0]), calibration([-1, 0, 0])

    assert in_front_of_both(np.array([0.0, 0.0, 3.0]), left, right)
    assert not in_front_of_both(np.array([0.0, 0.0, -3.0]), left, right)


def test_complete_box_foot_restores_clipped_centres_from_depth_ratio():
    other_box = [100, 20, 140, 180]

    assert complete_box_foot([0, 20, 30, 180], 200, other_box, depth=10, other_depth=5) == (20, 180.0)
    assert complete_box_foot([170, 20, 200, 180], 200, other_box, depth=10, other_depth=5) == (180, 180.0)
    assert complete_box_foot([50, 20, 90, 180], 200, other_box, depth=10, other_depth=5) == (70, 180.0)


def test_match_by_cost_uses_ground_distance_threshold_before_hungarian():
    distances = {
        (0, 0): 0.2,
        (0, 1): 0.8,
        (1, 0): 0.8,
        (1, 1): 1.1,
    }

    matches = match_by_cost(2, 2, lambda row, col: distances[(row, col)], max_cost=1.0)

    assert matches == [(0, 1, 0.8), (1, 0, 0.8)]


def test_combine_plane_positions_prefers_near_steep_observation():
    near = Calibration(K=np.eye(3), dist=np.zeros(5), R=np.eye(3), t=np.array([0.0, 0.0, -2.0]))
    far = Calibration(K=np.eye(3), dist=np.zeros(5), R=np.eye(3), t=np.array([-10.0, 0.0, -2.0]))

    combined = combine_plane_positions(
        [np.array([0.0, 0.0, 0.0]), np.array([4.0, 0.0, 0.0])],
        [near, far],
    )

    assert combined[0] < 1.0
    assert combined[2] == 0.0
