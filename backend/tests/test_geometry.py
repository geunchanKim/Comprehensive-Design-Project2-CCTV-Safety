import numpy as np

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
