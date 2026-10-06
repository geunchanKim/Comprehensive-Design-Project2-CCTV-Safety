from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanState:
    mean: np.ndarray
    covariance: np.ndarray
    timestamp_ms: int


def initialize_kalman(position, timestamp_ms: int) -> KalmanState:
    mean = np.zeros(6, dtype=float)
    mean[:3] = np.asarray(position, dtype=float)
    covariance = np.diag([0.25, 0.25, 0.25, 4.0, 4.0, 4.0])
    return KalmanState(mean=mean, covariance=covariance, timestamp_ms=int(timestamp_ms))


def update_kalman(state: KalmanState, position, timestamp_ms: int,
                  process_noise: float = 1.0, measurement_noise: float = 0.04) -> KalmanState:
    dt = (int(timestamp_ms) - state.timestamp_ms) / 1000.0
    if dt <= 0:
        raise ValueError("Kalman timestamps must increase")

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
