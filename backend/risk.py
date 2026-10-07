from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PairRisk:
    distance_m: float
    ttc_s: float | None
    level: str


def time_to_distance(relative_position, relative_velocity, threshold_m: float) -> float | None:
    position = np.asarray(relative_position, dtype=float)
    velocity = np.asarray(relative_velocity, dtype=float)
    c = float(position @ position - threshold_m * threshold_m)
    if c <= 0:
        return 0.0
    a = float(velocity @ velocity)
    if a < 1e-12:
        return None
    b = 2.0 * float(position @ velocity)
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return None
    entry = (-b - np.sqrt(discriminant)) / (2.0 * a)
    return float(entry) if entry >= 0 else None


def calculate_pair_risk(position_a, velocity_a, position_b, velocity_b,
                        warning_distance_m: float = 1.0,
                        danger_distance_m: float = 0.5) -> PairRisk:
    if not 0 < danger_distance_m < warning_distance_m:
        raise ValueError("danger distance must be positive and below warning distance")
    relative_position = np.asarray(position_b, dtype=float) - np.asarray(position_a, dtype=float)
    relative_velocity = np.asarray(velocity_b, dtype=float) - np.asarray(velocity_a, dtype=float)
    distance = float(np.linalg.norm(relative_position))
    if distance < danger_distance_m:
        level = "danger"
    elif distance < warning_distance_m:
        level = "warning"
    else:
        level = "safe"
    return PairRisk(distance_m=distance,
                    ttc_s=time_to_distance(relative_position, relative_velocity, danger_distance_m),
                    level=level)
