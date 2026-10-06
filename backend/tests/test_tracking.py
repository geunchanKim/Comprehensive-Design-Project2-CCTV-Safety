import numpy as np

from backend.tracking import initialize_kalman, update_kalman


def test_kalman_estimates_constant_velocity():
    state = initialize_kalman([0.0, 0.0, 0.0], timestamp_ms=0)

    for second in range(1, 6):
        state = update_kalman(state, [float(second), 0.0, 0.0], timestamp_ms=second * 1000)

    assert np.allclose(state.mean[:3], [5.0, 0.0, 0.0], atol=0.1)
    assert np.allclose(state.mean[3:], [1.0, 0.0, 0.0], atol=0.1)


def test_kalman_rejects_non_increasing_timestamp():
    state = initialize_kalman([0.0, 0.0, 0.0], timestamp_ms=1000)

    with np.testing.assert_raises_regex(ValueError, "timestamps must increase"):
        update_kalman(state, [1.0, 0.0, 0.0], timestamp_ms=1000)
