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


def complete_box_foot(bbox, image_width, other_bbox, depth, other_depth) -> tuple[float, float]:
    """Restore the bottom centre of a horizontally clipped bounding box."""
    x1, _, x2, y2 = map(float, bbox)
    if depth <= 0 or other_depth <= 0:
        raise ValueError("bbox depth must be positive")
    estimated_width = (float(other_bbox[2]) - float(other_bbox[0])) * other_depth / depth
    if estimated_width <= x2 - x1:
        return foot_point(bbox)
    if x1 <= 0 < x2:
        return (x2 - estimated_width / 2.0, y2)
    if x1 < image_width <= x2:
        return (x1 + estimated_width / 2.0, y2)
    return foot_point(bbox)


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


def in_front_of_both(world, a: Calibration, b: Calibration) -> bool:
    point = np.asarray(world, dtype=float).reshape(3)
    return all(float((calibration.R @ point + calibration.t.reshape(3))[2]) > 0 for calibration in (a, b))


def position_on_plane(point, calibration: Calibration, plane_z: float) -> np.ndarray:
    """Intersect an undistorted normalized image ray with a world Z plane."""
    camera_center = -calibration.R.T @ calibration.t.reshape(3)
    world_direction = calibration.R.T @ np.array([point[0], point[1], 1.0], dtype=float)
    if abs(world_direction[2]) < 1e-12:
        raise ValueError("camera ray is parallel to the requested plane")
    scale = (float(plane_z) - camera_center[2]) / world_direction[2]
    if scale <= 0:
        raise ValueError("plane intersection is behind the camera")
    world = camera_center + scale * world_direction
    world[2] = float(plane_z)
    return world.astype(float)


def match_class(points1, points2, essential, pixel_scale, max_error_px=5.0,
                pair_is_valid=None, pair_points=None):
    if not points1 or not points2:
        return []
    costs = np.empty((len(points1), len(points2)), dtype=float)
    for row, point1 in enumerate(points1):
        for col, point2 in enumerate(points2):
            candidate1, candidate2 = point1, point2
            if pair_points is not None:
                candidate1, candidate2 = pair_points(row, col)
            costs[row, col] = symmetric_epipolar_distance(candidate1, candidate2, essential) * pixel_scale
    invalid_cost = max(float(np.max(costs)), max_error_px) + 1e9
    for row in range(len(points1)):
        for col in range(len(points2)):
            if costs[row, col] > max_error_px:
                costs[row, col] = invalid_cost
            elif pair_is_valid is not None and not pair_is_valid(row, col):
                costs[row, col] = invalid_cost
    rows, cols = linear_sum_assignment(costs)
    return [(int(r), int(c), float(costs[r, c])) for r, c in zip(rows, cols) if costs[r, c] <= max_error_px]
