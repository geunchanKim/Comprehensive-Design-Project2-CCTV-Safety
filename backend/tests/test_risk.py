import pytest

from backend.risk import calculate_pair_risk


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
