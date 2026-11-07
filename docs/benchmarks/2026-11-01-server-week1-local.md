# Server processing times

Successful bundles only; excludes HTTP parsing, serialization and network latency.

## local-s4-baseline / basic / baseline / ba7ec7ef4b27c956722c5c4c16cb939f90d5c362

Bundles: 100

| Stage | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| calibration_bundle_ms | 100 | 8.113 | 7.082 | 13.404 | 14.988 | 35.023 |
| commit_ms | 100 | 11.845 | 10.921 | 18.778 | 19.738 | 31.890 |
| floor_tracking_ms | 100 | 0.003 | 0.002 | 0.004 | 0.004 | 0.007 |
| ingest_undistort_ms | 100 | 1.112 | 0.632 | 1.731 | 4.492 | 7.155 |
| matching_position_tracking_ms | 100 | 12.717 | 11.025 | 19.886 | 22.816 | 43.491 |
| response_prepare_ms | 100 | 3.990 | 3.783 | 6.860 | 8.343 | 14.076 |
| risk_ms | 100 | 0.001 | 0.001 | 0.002 | 0.003 | 0.004 |
| total_ms | 100 | 51.243 | 50.021 | 71.039 | 82.969 | 101.454 |
| validation_ms | 100 | 13.458 | 12.543 | 21.033 | 23.707 | 26.593 |

## local-s4-f-cdfg / basic / f-cdfg / ba7ec7ef4b27c956722c5c4c16cb939f90d5c362

Bundles: 100

| Stage | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| calibration_bundle_ms | 100 | 11.312 | 9.812 | 20.105 | 25.163 | 39.279 |
| commit_ms | 100 | 22.120 | 17.626 | 39.426 | 50.839 | 65.228 |
| floor_tracking_ms | 100 | 7.170 | 5.352 | 13.501 | 18.110 | 39.589 |
| ingest_undistort_ms | 100 | 1.723 | 0.696 | 4.504 | 5.871 | 11.158 |
| matching_position_tracking_ms | 100 | 21.299 | 16.127 | 40.646 | 53.039 | 118.624 |
| response_prepare_ms | 100 | 5.383 | 4.846 | 9.908 | 13.261 | 22.296 |
| risk_ms | 100 | 3.811 | 2.944 | 8.330 | 11.690 | 15.566 |
| total_ms | 100 | 92.193 | 75.322 | 157.627 | 208.209 | 267.994 |
| validation_ms | 100 | 19.368 | 16.879 | 30.938 | 38.454 | 66.000 |

## Measurement environment

Local replay, temporary SQLite; excludes HTTP/network/camera/display.

- Platform: Windows-11-10.0.26200-SP0
- Python: 3.12.10
- Pack: ai/eval/packs/s4
- Measured pairs per condition: 100
- Warmup pairs per condition: 10
- Source: working tree based on APP_COMMIT_SHA; uncommitted changes included.

```json
{
  "baseline": {
    "matching_method": "epipolar",
    "kalman_filter": false,
    "track_pair_hold": false,
    "ankle_pairing": false,
    "floor_tracking": false,
    "single_camera_fallback": false,
    "time_offset_correction": false,
    "warning_hysteresis": false,
    "features": [],
    "max_ground_distance_m": 1.5,
    "kalman_process_noise": 30.0,
    "kalman_measurement_noise": 0.005,
    "floor_track_gate_m": 0.8,
    "floor_track_max_missed": 20,
    "single_camera_ankle_z_m": 0.08,
    "ground_ankle_z_m": 0.08,
    "single_camera_measurement_noise": 0.05,
    "warning_release_margin_m": 0.1,
    "bbox_position_method": "triangulate",
    "track_pair_confirm_frames": 3,
    "track_pair_improvement_ratio": 0.9,
    "risk_analysis": false,
    "min_ankle_confidence": 0.6,
    "warning_distance_m": 1.0,
    "danger_distance_m": 0.5
  },
  "f-cdfg": {
    "matching_method": "ground-plane",
    "kalman_filter": false,
    "track_pair_hold": false,
    "ankle_pairing": false,
    "floor_tracking": true,
    "single_camera_fallback": true,
    "time_offset_correction": false,
    "warning_hysteresis": true,
    "features": [
      "fallback",
      "floor",
      "ground",
      "hysteresis"
    ],
    "max_ground_distance_m": 1.5,
    "kalman_process_noise": 30.0,
    "kalman_measurement_noise": 0.005,
    "floor_track_gate_m": 0.8,
    "floor_track_max_missed": 20,
    "single_camera_ankle_z_m": 0.08,
    "ground_ankle_z_m": 0.08,
    "single_camera_measurement_noise": 0.05,
    "warning_release_margin_m": 0.1,
    "bbox_position_method": "triangulate",
    "track_pair_confirm_frames": 3,
    "track_pair_improvement_ratio": 0.9,
    "risk_analysis": false,
    "min_ankle_confidence": 0.6,
    "warning_distance_m": 1.0,
    "danger_distance_m": 0.5
  }
}
```
