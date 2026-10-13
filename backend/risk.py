from dataclasses import dataclass

import numpy as np


# F 경고 유지: 켜진 경고(위험)는 기준 거리보다 이만큼 더 멀어져야 끈다.
#   1.0m 근처에서 위치가 몇 cm 흔들릴 때 경고가 켜졌다 꺼졌다 하는 것을 막는다
WARNING_RELEASE_MARGIN_M = 0.1


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
    # Collision risk is measured on the ground plane; source-dependent foot
    # heights must not inflate the distance or TTC.
    relative_position = (np.asarray(position_b, dtype=float)
                         - np.asarray(position_a, dtype=float))[:2]
    relative_velocity = (np.asarray(velocity_b, dtype=float)
                         - np.asarray(velocity_a, dtype=float))[:2]
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


def hysteresis_level(distance_m: float, previous: str, warning_distance_m: float = 1.0,
                     danger_distance_m: float = 0.5, margin_m: float = WARNING_RELEASE_MARGIN_M) -> str:
    """F 경고 유지: 켜질 때는 기준 거리(1.0m·0.5m), 꺼질 때는 기준 + 여유(1.1m·0.6m)"""
    if distance_m < danger_distance_m or (previous == "danger" and distance_m < danger_distance_m + margin_m):
        return "danger"
    if distance_m < warning_distance_m or (previous in ("warning", "danger")
                                           and distance_m < warning_distance_m + margin_m):
        return "warning"
    return "safe"
