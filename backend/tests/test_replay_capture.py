import copy
import json
import zipfile

import pytest

from backend.tools.replay_capture import load_capture, require_ready, shifted


def bundle(pair=1, ts=1000):
    return {"session_id": "classroom-1014-s10-t1-v7", "calibration_profile": "basic", "pair_id": pair,
            "frames": [{"camera_id": cam, "frame_id": pair, "ts": ts+offset,
                        "recv_ms": ts+offset+7, "pts_ms": 42.5, "image_size": [1920, 1080], "detections": []}
                       for cam, offset in (("cam1", 0), ("cam2", 8))]}


def test_shift_preserves_sync_receive_delay_and_pts():
    original = bundle()
    before = copy.deepcopy(original)
    result = shifted(original, "classroom-1014-s10-t1-v91", 50000)
    assert original == before
    assert result["session_id"].endswith("v91")
    assert result["frames"][1]["ts"] - result["frames"][0]["ts"] == 8
    for old, new in zip(original["frames"], result["frames"]):
        assert new["ts"] - old["ts"] == new["recv_ms"] - old["recv_ms"] == 50000
        assert new["pts_ms"] == old["pts_ms"]
    assert shifted(bundle(2, 1123), "new", 50000)["frames"][0]["ts"] - result["frames"][0]["ts"] == 123


def test_load_zip_accepts_gapped_pairs_and_rejects_duplicates(tmp_path):
    path = tmp_path / "input.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sent_detections.jsonl", "\n".join(json.dumps(b) for b in [bundle(), bundle(7, 1100)]))
    rows, timestamps = load_capture(path)
    assert len(rows) == 2 and timestamps == [1000, 1100]
    plain = tmp_path / "bad.jsonl"
    plain.write_text("\n".join(json.dumps(bundle()) for _ in range(2)))
    with pytest.raises(ValueError, match="duplicate"):
        load_capture(plain)


def test_reject_old_server_before_any_writes():
    with pytest.raises(ValueError, match="lacks demo APIs"):
        require_ready({"algorithms": {"baseline": {"risk_analysis": False}}}, {"/detections": {}})
    paths = {p: {} for p in ("/dashboard/configuration", "/dashboard/snapshot", "/dashboard/cameras",
                            "/edge/heartbeat", "/alerts", "/alerts/{alert_id}/ack")}
    with pytest.raises(ValueError, match="disabled"):
        require_ready({"algorithms": {"baseline": {"risk_analysis": False}}}, paths)
    require_ready({"algorithms": {"baseline": {"risk_analysis": True}}}, paths)
