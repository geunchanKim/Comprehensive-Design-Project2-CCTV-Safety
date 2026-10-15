import numpy as np

from backend.tracking import (PairHysteresis, associate_floor_tracks, initialize_kalman, predict_floor_position,
                              update_kalman, update_pair_hysteresis)


def test_kalman_estimates_constant_velocity():
    state = initialize_kalman([0.0, 0.0, 0.0], timestamp_ms=0)

    # 실제 프레임 간격(약 100ms)으로 1초 동안 1m/s 이동
    for step in range(1, 11):
        state = update_kalman(state, [step * 0.1, 0.0, 0.0], timestamp_ms=step * 100)

    assert np.allclose(state.mean[:3], [1.0, 0.0, 0.0], atol=0.1)
    assert np.allclose(state.mean[3:], [1.0, 0.0, 0.0], atol=0.1)


def test_kalman_follows_turn_without_lag():
    # 1.2m/s로 걷다가 90도 꺾는 사람 (10fps). 꺾고 0.5초 뒤 측정 위치를 5cm 안으로 따라가야 한다.
    # 예전 잡음 값(1.0, 0.04)은 여기서 약 26cm 뒤처졌다.
    points = [(0.12 * i, 0.0) for i in range(11)] + [(1.2, 0.12 * i) for i in range(1, 6)]
    state = initialize_kalman([*points[0], 0.0], timestamp_ms=0)
    for i, (x, y) in enumerate(points[1:], start=1):
        state = update_kalman(state, [x, y, 0.0], timestamp_ms=i * 100)

    assert np.linalg.norm(state.mean[:2] - np.array(points[-1])) < 0.05


def test_kalman_skips_non_increasing_timestamp():
    state = initialize_kalman([0.0, 0.0, 0.0], timestamp_ms=1000)

    unchanged = update_kalman(state, [1.0, 0.0, 0.0], timestamp_ms=1000)

    assert unchanged is state
    assert unchanged.timestamp_ms == 1000
    assert np.array_equal(unchanged.mean[:3], [0.0, 0.0, 0.0])


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


def test_floor_tracks_follow_crossing_people_regardless_of_order():
    # 두 사람이 x자로 엇갈림: A는 왼쪽→오른쪽, B는 오른쪽→왼쪽 (1.2m/s, 10fps)
    # 이번 위치 목록 순서를 매번 뒤집어도 예측 위치로 같은 사람을 따라가야 한다
    a = [(-1.2 + 0.12 * i, 0.0 + 0.03 * i) for i in range(21)]
    b = [(1.2 - 0.12 * i, 0.6 - 0.03 * i) for i in range(21)]
    states = [initialize_kalman([*a[0], 0.0], 0), initialize_kalman([*b[0], 0.0], 0)]
    for step in range(1, 21):
        t = step * 100
        positions = [b[step], a[step]] if step % 2 else [a[step], b[step]]
        pairs = dict(associate_floor_tracks([predict_floor_position(s, t) for s in states], positions))
        assert len(pairs) == 2
        assert positions[pairs[0]] == a[step] and positions[pairs[1]] == b[step]
        states = [update_kalman(states[k], [*positions[pairs[k]], 0.0], t) for k in range(2)]


def test_floor_tracks_do_not_join_far_positions():
    state = initialize_kalman([0.0, 0.0, 0.0], 0)
    assert associate_floor_tracks([predict_floor_position(state, 100)], [(2.0, 0.0)]) == []
