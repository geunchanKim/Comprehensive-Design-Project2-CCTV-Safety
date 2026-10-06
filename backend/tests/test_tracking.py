import numpy as np

from backend.tracking import PairHysteresis, initialize_kalman, update_kalman, update_pair_hysteresis


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


def test_pair_hysteresis_switches_only_after_consecutive_better_frames():
    state = PairHysteresis()

    for expected_streak in (1, 2):
        locked, state = update_pair_hysteresis([10.0, 5.0], incumbent=0, state=state)
        assert locked == 0
        assert state == PairHysteresis(challenger=1, streak=expected_streak)

    locked, state = update_pair_hysteresis([10.0, 5.0], incumbent=0, state=state)
    assert locked is None
    assert state == PairHysteresis(challenger=1, streak=3)


def test_pair_hysteresis_resets_when_incumbent_recovers():
    state = PairHysteresis(challenger=1, streak=2)

    locked, state = update_pair_hysteresis([5.0, 10.0], incumbent=0, state=state)

    assert locked == 0
    assert state == PairHysteresis()
