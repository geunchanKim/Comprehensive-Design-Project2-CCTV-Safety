import copy
import json
import zipfile
from pathlib import Path

import pytest

from backend.tools.measurement_report import report
from backend.tools.prepare_replay_calibrations import prepare
from backend.tools.check_unity_metadata import check


def write_jsonl(folder, name, rows):
    (folder / name).write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_replay_plan_preserves_calibration_and_registers_both_profiles():
    source = Path(__file__).resolve().parents[2] / "ai/calibration/output/calib-classroom-1014-2x2b.json"
    calibration = json.loads(source.read_text(encoding="utf-8"))
    original = copy.deepcopy(calibration)
    sessions = ["classroom-1014-s10-t1-v6", "classroom-1014-s10-t1-v7"]
    plan = prepare(calibration, sessions)
    assert len(plan) == 8
    assert {row["body"]["session_id"] for row in plan} == set(sessions)
    assert {row["body"]["calibration_profile"] for row in plan} == {"basic", "precise"}
    for row in plan:
        camera = row["path"].split("/")[2]
        profile = row["body"]["calibration_profile"]
        assert row["body"]["K"] == original[camera][profile]["K"]
        assert row["body"]["tvec"] == original[camera][profile]["tvec"]
    assert calibration == original
    with pytest.raises(ValueError, match="distinct"):
        prepare(calibration, sessions * 2)
    calibration["cam1"]["basic"]["calibration_profile"] = "precise"
    with pytest.raises(ValueError, match="disagree"):
        prepare(calibration, sessions)


def test_measurement_report_handles_legacy_and_new_fields(tmp_path):
    sent = [{"session_id": "v6", "pair_id": n, "frames": [{"ts": n * 100, "recv_ms": n * 100}]}
            for n in (1, 2)]
    write_jsonl(tmp_path, "sent_detections.jsonl", sent)
    write_jsonl(tmp_path, "timings.jsonl", [
        {"frame": 1, "wait_ms": 2, "age_ms": 9, "detect_ms": {"cam1": 5}},
        {"frame": 2, "wait_ms": 3, "age_ms": 10, "detect_ms": {"cam1": 7},
         "yolo_ms": {"cam1": 4}, "pose_ms": {"cam1": 0}, "rtt_ms": 20},
    ])
    write_jsonl(tmp_path, "responses_detections.jsonl", [
        {"session_id": "v6", "pair_id": 1},
        {"session_id": "v6", "pair_id": 2, "timings_ms": {"total_ms": 8}},
    ])
    write_jsonl(tmp_path, "failed.jsonl", [
        {"path": "/detections", "status": 409, "message": {"session_id": "v6", "pair_id": 3}},
        {"path": "/ground-truth", "status": 422},
    ])
    text = report(tmp_path)
    assert "Pairs present in all three logs: 2" in text
    assert "Detection failures: 1" in text
    assert "second: 10.000" in text
    assert "| edge.pose_ms.cam1 | 1 | 0.000" in text
    assert "| edge.rtt_ms | 1 | 20.000" in text
    assert "| server.total_ms | 1 | 8.000" in text


def test_measurement_report_does_not_invent_missing_timings(tmp_path):
    write_jsonl(tmp_path, "timings.jsonl", [{"frame": 1, "detect_ms": {"cam1": 4}}])
    text = report(tmp_path)
    assert "pose_ms: unavailable" in text
    assert "rtt_ms: unavailable" in text
    assert "Server stage timings: unavailable" in text
    write_jsonl(tmp_path, "timings.jsonl", [{"frame": 1, "detect_ms": {"cam1": -1}}])
    with pytest.raises(ValueError, match="nonnegative"):
        report(tmp_path)


def test_measurement_report_rejects_mixed_sessions_and_duplicate_pairs(tmp_path):
    write_jsonl(tmp_path, "sent_detections.jsonl", [
        {"session_id": "v6", "pair_id": 1}, {"session_id": "v7", "pair_id": 1},
    ])
    with pytest.raises(ValueError, match="one session"):
        report(tmp_path)
    write_jsonl(tmp_path, "sent_detections.jsonl", [{"session_id": "v6", "pair_id": 1}] * 2)
    with pytest.raises(ValueError, match="duplicate"):
        report(tmp_path)


def test_measurement_report_warmup_aligns_logs_and_keeps_dropped_counts(tmp_path):
    write_jsonl(tmp_path, "timings.jsonl", [
        {"frame": 20, "queue_ms": 4, "rtt_ms": 30, "status": 201},
        {"frame": 1, "queue_ms": 999, "rtt_ms": 999, "status": "dropped"},
    ])
    write_jsonl(tmp_path, "responses_detections.jsonl", [
        {"session_id": "v6", "pair_id": 20, "timings_ms": {"total_ms": 10}},
    ])
    text = report(tmp_path, warmup=1)
    assert "'dropped': 1" in text
    assert "Detection failures: 0" in text
    assert "| edge.queue_ms | 1 | 4.000" in text
    assert "| server.total_ms | 1 | 10.000" in text
    assert "p90 ms" in text
    assert "999.000" not in text
    assert "rtt_ms: unavailable" in report(tmp_path, warmup=10)
    with pytest.raises(ValueError, match="nonnegative integer"):
        report(tmp_path, warmup=-1)


def test_measurement_report_pools_samples_and_excludes_warmup_per_session(tmp_path):
    folders = [tmp_path / name for name in ("a", "b")]
    for folder, values in zip(folders, ([999, 10], [999, 20, 30])):
        folder.mkdir()
        write_jsonl(folder, "timings.jsonl", [
            {"frame": n * 10, "rtt_ms": value, "status": 201}
            for n, value in enumerate(values)
        ])
        write_jsonl(folder, "sent_detections.jsonl", [
            {"session_id": folder.name + "-v6", "pair_id": n * 10}
            for n in range(len(values))
        ])
    text = report(folders, warmup=1)
    assert "| edge.rtt_ms | 3 | 20.000 | 20.000 | 28.000 | 29.000 | 30.000 |" in text
    assert "'timings': 5" in text
    assert "## a" in text and "## b" in text
    with pytest.raises(ValueError, match="distinct"):
        report([folders[0], folders[0]])
    write_jsonl(folders[1], "sent_detections.jsonl", [{"session_id": "b-v7", "pair_id": 0}])
    with pytest.raises(ValueError, match="different version"):
        report(folders)


def test_unity_metadata_zip_uses_world_frame_and_checks_timestamps(tmp_path):
    def make_zip(timestamp):
        cameras = {"cameras": [
            {"camera_id": name, "image_size": [1920, 1080], "vertical_fov_deg": 46.8,
             "position": [x, 2, 0], "rotation_quat": [0, 0, 0, 1]}
            for name, x in (("cam1", -1), ("cam2", 1))
        ]}
        frames = [{"frame": n, "ts": ts, "objects": [
            {"object_id": "person_1", "cls": "person", "world": [0, 0, 3]},
        ]} for n, ts in ((1, 1000), (2, timestamp))]
        path = tmp_path / f"scene-{timestamp}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("scene/cameras.json", json.dumps(cameras))
            archive.writestr("scene/frames.jsonl", "\n".join(json.dumps(f) for f in frames))
            archive.writestr("scene/events.json", json.dumps({"fps": 15, "frame_count": 2,
                                                           "events": [], "expected_alerts": []}))
            for camera in ("cam1", "cam2"):
                for n in (1, 2):
                    archive.writestr(f"scene/{camera}/{n:06d}.jpg", b"metadata-only-test")
        return path
    result = check(make_zip(1067))
    assert result["frames"] == 2 and result["object_frames"] == 2
    assert result["coordinate_frame_id"] == "unity-world-xzy"
    assert result["max_calibration_roundtrip_error_m"] < 1e-4
    with pytest.raises(ValueError, match="timestamp"):
        check(make_zip(1090))
