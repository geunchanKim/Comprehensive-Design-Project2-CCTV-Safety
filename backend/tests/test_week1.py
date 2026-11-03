import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.dashboard import DashboardMap, DashboardSnapshot, MapBounds, ZoneSet, build_snapshot
from backend.profiling import StageTimer
from backend.schemas import DetectionBundleOut
from backend.tools.server_log_summary import summarize


def zone_set(vertices=None):
    return {"coordinate_frame_id": "unity-world-xzy", "zones": [{"zone_id": "classroom-demo-01", "name": "Review example",
                       "vertices": vertices or [[3, 3], [4, 3], [4, 4], [3, 4]],
                       "warning_distance_m": 0.5}]}


@pytest.mark.parametrize("vertices", [
    [[0, 0], [1, 1], [0, 1], [1, 0]],  # crossed
    [[0, 0], [1, 0], [2, 0]],  # no area
    [[0, 0], [1, 0], [1, 1], [0, 0]],  # repeated closing vertex
    [[0, 0], [float("nan"), 0], [1, 1]],
    [[0, 0], [2, 0], [1, 0], [1, 1]],  # adjacent overlap
])
def test_reject_invalid_polygon(vertices):
    with pytest.raises(ValidationError):
        ZoneSet.model_validate(zone_set(vertices))


def test_zone_ids_unique_and_warning_nonnegative():
    data = zone_set()
    data["zones"] *= 2
    with pytest.raises(ValidationError):
        ZoneSet.model_validate(data)
    data = zone_set()
    data["zones"][0]["warning_distance_m"] = -1
    with pytest.raises(ValidationError):
        ZoneSet.model_validate(data)


def test_concave_and_clockwise_polygons_supported():
    vertices = [[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]]
    for points in (vertices, vertices[::-1]):
        assert len(ZoneSet.model_validate(zone_set(points)).zones[0].vertices) == 5


def test_snapshot_preserves_identity_and_unevaluated_states():
    result = DetectionBundleOut.model_validate({
        "bundle_id": 1, "session_id": "demo", "pair_id": 10,
        "calibration_profile": "precise", "sync_delta_ms": 20, "max_sync_delta_ms": 50,
        "matches": [{"object_id": 7, "cls": "person", "camera_tracks": {"cam1": 9},
                     "foot_pixels": {}, "observations": [], "world": {"x": 3.5, "y": 3.5, "z": 0.08}}],
        "unmatched": {}, "settings": {"risk_analysis": False, "warning_hysteresis": False},
    })
    snapshot = build_snapshot(result, algorithm="improved", captured_at_ms=1000,
                              emitted_at_ms=1100, zones=ZoneSet.model_validate(zone_set()),
                              stream_id="test-stream", seq=1, map_config=map_config())
    assert snapshot.objects[0].object_id == 7
    assert snapshot.objects[0].vest.status == "unknown"
    assert snapshot.objects[0].zone_states[0].status == "unknown"
    assert not snapshot.zone_evaluated and not snapshot.vest_evaluated
    assert not snapshot.collision_evaluated
    assert snapshot.seq == 1 and snapshot.stream_id == "test-stream"
    assert snapshot.stale_after_ms == 1000
    assert snapshot.map.bounds.x_max - snapshot.map.bounds.x_min == 5
    assert set(snapshot.supported_classes) == {"person", "chair", "cart", "desk", "suitcase", "backpack"}
    result.settings["warning_hysteresis"] = True
    assert build_snapshot(result, algorithm="improved", captured_at_ms=1000,
                          emitted_at_ms=1100, zones=ZoneSet(zones=[], coordinate_frame_id="unity-world-xzy"),
                          stream_id="test-stream", seq=2, map_config=map_config()).collision_evaluated
    with pytest.raises(ValueError, match="coordinate frames"):
        build_snapshot(result, algorithm="improved", captured_at_ms=1000,
                       emitted_at_ms=1100, zones=ZoneSet(zones=[], coordinate_frame_id="marker-origin"),
                       stream_id="test-stream", seq=3, map_config=map_config())


def map_config():
    return DashboardMap(coordinate_frame_id="unity-world-xzy", bounds=MapBounds(
        x_min=2.79, x_max=7.79, y_min=1.785, y_max=6.785))


def test_map_bounds_and_sequence_validation():
    with pytest.raises(ValidationError):
        MapBounds(x_min=1, x_max=0, y_min=0, y_max=1)
    with pytest.raises(ValidationError):
        MapBounds(x_min=0, x_max=float("inf"), y_min=0, y_max=1)


def test_shared_examples_and_json_schemas_match_contract():
    examples = Path(__file__).resolve().parents[2] / "docs/specs/examples"
    for model, stem in ((ZoneSet, "risk-zones"), (DashboardSnapshot, "dashboard-snapshot")):
        schema = json.loads((examples / f"{stem}.schema.json").read_text(encoding="utf-8"))
        assert schema == model.model_json_schema()
    zones = ZoneSet.model_validate_json((examples / "classroom-risk-zones.example.json").read_text(encoding="utf-8"))
    snapshot = DashboardSnapshot.model_validate_json((examples / "dashboard-snapshot.example.json").read_text(encoding="utf-8"))
    assert snapshot.zones == zones.zones
    assert snapshot.objects[0].zone_states[0].zone_id == zones.zones[0].zone_id


def test_monotonic_stage_timer(monkeypatch):
    ticks = iter([1.0, 1.01, 1.03, 1.04])
    monkeypatch.setattr("backend.profiling.perf_counter", lambda: next(ticks))
    timer = StageTimer()
    timer.mark("validation_ms")
    timer.mark("commit_ms")
    assert timer.result() == pytest.approx({"validation_ms": 10, "commit_ms": 20, "total_ms": 40})


def test_summary_groups_conditions_and_ignores_other_log_lines():
    def row(algorithm, total):
        return "INFO: detection_timing " + json.dumps({
            "session_id": "demo", "calibration_profile": "basic", "algorithm": algorithm,
            "commit": "abc", "timings_ms": {"total_ms": total},
        })
    report = summarize(["GET /health 200", row("baseline", 10), row("baseline", 30), row("improved", 50)])
    assert "Bundles: 2" in report and "Bundles: 1" in report
    assert "20.000 | 20.000 | 28.000 | 29.000 | 30.000" in report
    with pytest.raises(ValueError, match="line 1"):
        summarize(["detection_timing {}"])
    with pytest.raises(ValueError, match="no detection_timing"):
        summarize(["GET /health 200"])
