import pytest

from backend.risk import calculate_pair_risk, hysteresis_level


def test_risk_levels_follow_distance_thresholds():
    stopped = [0.0, 0.0, 0.0]

    assert calculate_pair_risk([0, 0, 0], stopped, [0.4, 0, 0], stopped).level == "danger"
    assert calculate_pair_risk([0, 0, 0], stopped, [0.8, 0, 0], stopped).level == "warning"
    assert calculate_pair_risk([0, 0, 0], stopped, [2.0, 0, 0], stopped).level == "safe"


def test_ttc_is_time_until_danger_radius_entry():
    risk = calculate_pair_risk([0, 0, 0], [0, 0, 0], [2, 0, 0], [-1, 0, 0])

    assert risk.distance_m == 2.0
    assert risk.ttc_s == pytest.approx(1.5)


def test_ttc_is_none_for_objects_moving_apart():
    risk = calculate_pair_risk([0, 0, 0], [-1, 0, 0], [2, 0, 0], [1, 0, 0])

    assert risk.ttc_s is None


def test_risk_ignores_height_difference():
    risk = calculate_pair_risk([0, 0, 0.14], [0, 0, 1],
                               [0.4, 0, 0], [0, 0, -1])

    assert risk.distance_m == pytest.approx(0.4)
    assert risk.level == "danger"
    assert risk.ttc_s == 0.0


def test_hysteresis_keeps_warning_until_release_margin():
    # 1.0m 안으로 들어오면 켜지고, 1.05m로 살짝 멀어져도 유지, 1.1m를 넘어야 꺼진다
    assert hysteresis_level(1.05, "safe") == "safe"
    assert hysteresis_level(0.95, "safe") == "warning"
    assert hysteresis_level(1.05, "warning") == "warning"
    assert hysteresis_level(1.12, "warning") == "safe"
    assert hysteresis_level(0.55, "danger") == "danger"
    assert hysteresis_level(0.65, "danger") == "warning"
