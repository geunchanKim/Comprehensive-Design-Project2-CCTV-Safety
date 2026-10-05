from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass
class Calibration:
    K: np.ndarray
    dist: np.ndarray
    R: np.ndarray
    t: np.ndarray

    @property
    def projection(self) -> np.ndarray:
        return np.hstack((self.R, self.t.reshape(3, 1)))


def foot_point(bbox) -> tuple[float, float]:
    x1, _, x2, y2 = bbox
    return ((x1 + x2) / 2.0, float(y2))


def undistort(point, calibration: Calibration) -> np.ndarray:
    points = np.asarray(point, dtype=np.float64).reshape(1, 1, 2)
    return cv2.undistortPoints(points, calibration.K, calibration.dist).reshape(2)


def fundamental_matrix(a: Calibration, b: Calibration) -> np.ndarray:
    # Relative transform from camera a coordinates to camera b coordinates.
    relative_r = b.R @ a.R.T
    relative_t = b.t.reshape(3) - relative_r @ a.t.reshape(3)
    tx, ty, tz = relative_t
    skew = np.array([[0, -tz, ty], [tz, 0, -tx], [-ty, tx, 0]], dtype=float)
    return skew @ relative_r  # normalized-coordinate essential matrix


def symmetric_epipolar_distance(p1, p2, essential) -> float:
    x1 = np.array([p1[0], p1[1], 1.0])
    x2 = np.array([p2[0], p2[1], 1.0])
    line2, line1 = essential @ x1, essential.T @ x2
    numerator = abs(float(x2 @ essential @ x1))
    d1 = numerator / max(np.linalg.norm(line1[:2]), 1e-12)
    d2 = numerator / max(np.linalg.norm(line2[:2]), 1e-12)
    return (d1 + d2) / 2.0


def triangulate(p1, p2, a: Calibration, b: Calibration) -> np.ndarray:
    homogeneous = cv2.triangulatePoints(a.projection, b.projection, p1.reshape(2, 1), p2.reshape(2, 1))
    if abs(homogeneous[3, 0]) < 1e-12:
        raise ValueError("rays are parallel; triangulation is undefined")
    return (homogeneous[:3, 0] / homogeneous[3, 0]).astype(float)


def match_class(points1, points2, essential, pixel_scale, max_error_px=5.0, pair_is_valid=None):
    if not points1 or not points2:
        return []
    costs = np.array([[symmetric_epipolar_distance(a, b, essential) * pixel_scale for b in points2] for a in points1])
    if pair_is_valid is not None:
        invalid_cost = max(float(np.max(costs)), max_error_px) + 1e9
        for row in range(len(points1)):
            for col in range(len(points2)):
                if not pair_is_valid(row, col):
                    costs[row, col] = invalid_cost
    rows, cols = linear_sum_assignment(costs)
    return [(int(r), int(c), float(costs[r, c])) for r, c in zip(rows, cols) if costs[r, c] <= max_error_px]
