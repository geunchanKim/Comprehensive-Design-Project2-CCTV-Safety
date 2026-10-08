import sys
from pathlib import Path

import cv2
import numpy as np

CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "calibration"
sys.path.insert(0, str(CALIBRATION_DIR))

from calibrate_grid import solve  # noqa: E402


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
