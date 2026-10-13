from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

# 칼만 잡음 값 (Unity s2·s4 오프라인 시뮬로 정함, 2026-10-13)
#   측정 잡음 0.005 m² ≈ 위치 측정 오차 7cm (실제 측정 오차 수준)
#   과정 잡음 30 → 사람이 방향을 틀어도 늦지 않게 따라감
#   예전 값(1.0, 0.04)은 측정을 20cm 오차로 봐서 실제 위치보다 늦게 따라갔다
KALMAN_PROCESS_NOISE = 30.0
KALMAN_MEASUREMENT_NOISE = 0.005


@dataclass
class KalmanState:
    mean: np.ndarray
    covariance: np.ndarray
    timestamp_ms: int


@dataclass
class PairHysteresis:
    challenger: int | None = None
    streak: int = 0


def update_pair_hysteresis(costs, incumbent: int | None, state: PairHysteresis,
                           confirm_frames: int = 3, improvement_ratio: float = 0.9):
    """Keep an incumbent column until a better challenger wins repeatedly.

    Returns ``(locked_column, next_state)``. A ``None`` lock lets the global
    assignment select a new counterpart.
    """
    values = np.asarray(costs, dtype=float)
    if values.ndim != 1 or not len(values):
        return None, PairHysteresis()
    if confirm_frames < 1 or not 0 < improvement_ratio <= 1:
        raise ValueError("invalid pair hysteresis settings")
    if incumbent is None or incumbent < 0 or incumbent >= len(values) or not np.isfinite(values[incumbent]):
        return None, PairHysteresis()

    challenger = int(np.argmin(values))
    if challenger == incumbent or values[challenger] > values[incumbent] * improvement_ratio:
        return incumbent, PairHysteresis()
    streak = state.streak + 1 if state.challenger == challenger else 1
    next_state = PairHysteresis(challenger=challenger, streak=streak)
    if streak >= confirm_frames:
        return None, next_state
    return incumbent, next_state


def initialize_kalman(position, timestamp_ms: int) -> KalmanState:
    mean = np.zeros(6, dtype=float)
    mean[:3] = np.asarray(position, dtype=float)
    covariance = np.diag([0.25, 0.25, 0.25, 4.0, 4.0, 4.0])
    return KalmanState(mean=mean, covariance=covariance, timestamp_ms=int(timestamp_ms))


def update_kalman(state: KalmanState, position, timestamp_ms: int,
                  process_noise: float = KALMAN_PROCESS_NOISE,
                  measurement_noise: float = KALMAN_MEASUREMENT_NOISE) -> KalmanState:
    dt = (int(timestamp_ms) - state.timestamp_ms) / 1000.0
    if dt <= 0:
        return state

    transition = np.eye(6, dtype=float)
    transition[:3, 3:] = np.eye(3) * dt
    dt2, dt3, dt4 = dt * dt, dt * dt * dt, dt * dt * dt * dt
    process = process_noise * np.block([
        [np.eye(3) * dt4 / 4.0, np.eye(3) * dt3 / 2.0],
        [np.eye(3) * dt3 / 2.0, np.eye(3) * dt2],
    ])
    predicted_mean = transition @ state.mean
    predicted_covariance = transition @ state.covariance @ transition.T + process

    observation = np.hstack((np.eye(3), np.zeros((3, 3))))
    noise = np.eye(3) * measurement_noise
    innovation = np.asarray(position, dtype=float) - observation @ predicted_mean
    innovation_covariance = observation @ predicted_covariance @ observation.T + noise
    gain = np.linalg.solve(innovation_covariance, observation @ predicted_covariance).T
    mean = predicted_mean + gain @ innovation
    identity = np.eye(6)
    covariance = ((identity - gain @ observation) @ predicted_covariance
                  @ (identity - gain @ observation).T + gain @ noise @ gain.T)
    return KalmanState(mean=mean, covariance=covariance, timestamp_ms=int(timestamp_ms))


# C 바닥 좌표 추적: 사람 번호를 카메라 트랙 번호가 아니라 바닥 위 움직임으로 이어 붙인다
#   예측 위치에서 0.8m 안에 있는 사람만 같은 사람 후보, 20묶음(약 2초) 동안 안 보이면 지운다
#   (Unity s2·s4 오프라인 시뮬로 정함, 2026-10-13)
FLOOR_TRACK_GATE_M = 0.8
FLOOR_TRACK_MAX_MISSED = 20


def predict_floor_position(state: KalmanState, timestamp_ms: int) -> np.ndarray:
    """칼만 상태에서 timestamp_ms 때의 바닥 위치 (x, y) 예측"""
    dt = max(0.0, (int(timestamp_ms) - state.timestamp_ms) / 1000.0)
    return state.mean[:2] + state.mean[3:5] * dt


def associate_floor_tracks(predicted, positions, gate_m: float = FLOOR_TRACK_GATE_M):
    """예측 위치들과 이번 위치들을 바닥 거리 합이 가장 작게 짝짓는다 → [(트랙 번호, 위치 번호)]

    gate_m보다 먼 짝은 만들지 않는다 (그 위치는 새 사람, 그 트랙은 이번에 못 본 사람)."""
    if not len(predicted) or not len(positions):
        return []
    a = np.asarray(predicted, dtype=float)[:, None, :2]
    b = np.asarray(positions, dtype=float)[None, :, :2]
    distance = np.linalg.norm(a - b, axis=2)
    cost = np.where(distance <= gate_m, distance, gate_m * 1000.0 + 1e6)
    rows, cols = linear_sum_assignment(cost)
    return [(int(r), int(c)) for r, c in zip(rows, cols) if distance[r, c] <= gate_m]
