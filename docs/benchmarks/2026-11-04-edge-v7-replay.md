# v7 녹화 재생 로그 검증

2026-11-04 BE가 사용자 제공 `v7-edge-logs.zip` 원본으로 재계산했다. SHA256: `269fe949b8d224985bc873166b2b3bfe81202e3d0c4a4a902172c962df26d45b`.

실행 메타의 시작/종료는 2026-11-03 17:12:57~17:18:31(오프셋 없는 기록, 공유 맥락상 KST)이다. 배포 `2e1d2c3`·엣지 `30d2e97`·MacBook Pro M3 Pro/MPS는 #71 실행자 회신 기준이며 로그의 machine은 macOS/arm64/Python 3.13.0이다. 모델 설정 파일은 15세션 모두 동일하고 COCO/imgsz 1280/ankle/ByteTrack이다. 실행 메타의 sessions_file은 null이지만 planned/done과 실제 폴더가 확정 v7 15세션 목록과 일치한다.

응답은 모두 **basic / baseline**, 동일 settings이며 total 포함 서버 timing 9개가 모두 존재한다. cdfg의 floor/fallback/경고 유지와 전체 위험 분석은 비활성이다. 이번 표를 cdfg 또는 활성 위험 분석의 성능으로 일반화하지 않는다. frame/pair_id 중복·로그 간 불일치가 없고 서버 응답 status는 모두 processed다. 실패 파일 부재를 확인했으며 timings status도 모두 201이다.

세션별 첫 관측 5짝을 제외한다. 전체·세션별 표본을 합쳐 계산했으며 AI 공유 표와 반올림 범위 내에서 일치한다. RTT는 화면까지의 전체 지연이 아니며 입력 수신 시각 기준 전송률도 서버 완료율이 아니다.

# Edge and server measurement report

## Overall

Sessions: 15; warmup: first 5 observed pairs per session.
Latency statistics pool individual samples; record/status counts include warmup; send rates exclude warmup.
- Records (all pairs): {'timings': 3020, 'sent': 3020, 'responses': 3020, 'failed': 0, 'missing_responses': 0, 'orphan_responses': 0, 'pairs_in_all_three_logs': 3020}
- Timing status counts (all rows): {'201': 3020}
- Detection failure status counts (all rows): {}

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 2945 | 141.973 | 133.500 | 193.200 | 223.800 | 700.400 |
| edge.detect_ms.cam1 | 2945 | 43.123 | 39.900 | 47.460 | 58.360 | 224.600 |
| edge.detect_ms.cam2 | 2945 | 42.308 | 39.700 | 44.400 | 51.860 | 204.400 |
| edge.detect_ms.total | 2945 | 85.431 | 79.600 | 92.300 | 107.620 | 429.000 |
| edge.pose_ms.cam1 | 2945 | 21.777 | 20.300 | 23.100 | 26.480 | 199.300 |
| edge.pose_ms.cam2 | 2945 | 21.487 | 20.300 | 22.400 | 26.280 | 68.100 |
| edge.pose_ms.total | 2945 | 43.264 | 40.600 | 46.000 | 51.940 | 233.600 |
| edge.queue_ms | 2945 | 71.513 | 0.100 | 146.440 | 627.380 | 2024.300 |
| edge.rtt_ms | 2945 | 49.694 | 35.700 | 75.260 | 107.460 | 1326.900 |
| edge.wait_ms | 2945 | 56.505 | 50.500 | 101.000 | 122.100 | 487.800 |
| edge.yolo_ms.cam1 | 2945 | 21.321 | 19.600 | 23.400 | 32.000 | 165.900 |
| edge.yolo_ms.cam2 | 2945 | 20.798 | 19.500 | 21.800 | 25.200 | 170.000 |
| edge.yolo_ms.total | 2945 | 42.119 | 39.100 | 46.300 | 57.280 | 195.200 |
| server.calibration_bundle_ms | 2945 | 1.608 | 1.062 | 3.966 | 4.466 | 7.099 |
| server.commit_ms | 2945 | 8.294 | 7.938 | 11.554 | 12.801 | 50.759 |
| server.floor_tracking_ms | 2945 | 0.001 | 0.001 | 0.002 | 0.003 | 0.021 |
| server.ingest_undistort_ms | 2945 | 0.510 | 0.377 | 1.121 | 1.604 | 3.517 |
| server.matching_position_tracking_ms | 2945 | 3.699 | 2.893 | 7.338 | 9.447 | 43.044 |
| server.response_prepare_ms | 2945 | 1.010 | 0.793 | 1.856 | 2.414 | 4.643 |
| server.risk_ms | 2945 | 0.001 | 0.001 | 0.001 | 0.001 | 0.030 |
| server.total_ms | 2945 | 20.074 | 16.943 | 34.908 | 38.968 | 61.054 |
| server.validation_ms | 2945 | 4.947 | 2.995 | 12.603 | 13.670 | 17.077 |

## classroom-1014-s1-t1-v7

Folder: classroom-1014-s1-t1-v7
Session/profile: ('classroom-1014-s1-t1-v7', 'basic')

- Timing rows: 210; successful send records: 210; responses: 210
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 210}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 210
- Observed pair range: 1..525
- Successful sends per input receive-time second: 10.949

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 205 | 142.834 | 134.100 | 184.020 | 213.320 | 572.100 |
| edge.detect_ms.cam1 | 205 | 41.686 | 40.400 | 44.500 | 46.520 | 95.200 |
| edge.detect_ms.cam2 | 205 | 40.697 | 40.000 | 43.460 | 44.000 | 52.700 |
| edge.detect_ms.total | 205 | 82.382 | 80.200 | 87.660 | 89.300 | 147.900 |
| edge.pose_ms.cam1 | 205 | 20.875 | 20.500 | 22.180 | 23.080 | 35.100 |
| edge.pose_ms.cam2 | 205 | 20.638 | 20.400 | 21.960 | 22.300 | 27.500 |
| edge.pose_ms.total | 205 | 41.513 | 40.800 | 44.160 | 45.900 | 56.300 |
| edge.queue_ms | 205 | 1.730 | 0.100 | 0.160 | 11.640 | 57.300 |
| edge.rtt_ms | 205 | 43.872 | 36.100 | 69.780 | 88.320 | 134.800 |
| edge.wait_ms | 205 | 60.409 | 52.900 | 102.440 | 127.780 | 471.200 |
| edge.yolo_ms.cam1 | 205 | 20.784 | 20.000 | 22.160 | 22.980 | 68.800 |
| edge.yolo_ms.cam2 | 205 | 20.033 | 19.700 | 21.260 | 21.860 | 30.600 |
| edge.yolo_ms.total | 205 | 40.817 | 39.600 | 43.260 | 44.480 | 99.400 |
| server.calibration_bundle_ms | 205 | 1.665 | 1.113 | 3.977 | 4.699 | 5.656 |
| server.commit_ms | 205 | 8.452 | 8.083 | 11.690 | 12.297 | 16.290 |
| server.floor_tracking_ms | 205 | 0.001 | 0.001 | 0.002 | 0.002 | 0.003 |
| server.ingest_undistort_ms | 205 | 0.653 | 0.451 | 1.455 | 1.970 | 2.251 |
| server.matching_position_tracking_ms | 205 | 5.380 | 4.598 | 9.464 | 11.140 | 43.044 |
| server.response_prepare_ms | 205 | 1.003 | 0.804 | 1.633 | 2.142 | 4.643 |
| server.risk_ms | 205 | 0.001 | 0.001 | 0.001 | 0.001 | 0.013 |
| server.total_ms | 205 | 21.931 | 18.630 | 35.457 | 39.580 | 56.294 |
| server.validation_ms | 205 | 4.775 | 2.971 | 11.331 | 13.711 | 15.993 |

## classroom-1014-s1-t2-v7

Folder: classroom-1014-s1-t2-v7
Session/profile: ('classroom-1014-s1-t2-v7', 'basic')

- Timing rows: 164; successful send records: 164; responses: 164
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 164}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 164
- Observed pair range: 1..397
- Successful sends per input receive-time second: 12.281

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 159 | 127.666 | 125.800 | 161.820 | 188.230 | 225.700 |
| edge.detect_ms.cam1 | 159 | 39.926 | 39.700 | 40.620 | 41.120 | 51.700 |
| edge.detect_ms.cam2 | 159 | 39.765 | 39.600 | 40.500 | 41.220 | 48.100 |
| edge.detect_ms.total | 159 | 79.691 | 79.200 | 80.800 | 82.230 | 99.800 |
| edge.pose_ms.cam1 | 159 | 20.217 | 20.100 | 20.700 | 20.910 | 28.700 |
| edge.pose_ms.cam2 | 159 | 20.207 | 20.100 | 20.700 | 21.000 | 22.900 |
| edge.pose_ms.total | 159 | 40.424 | 40.200 | 41.400 | 41.710 | 49.400 |
| edge.queue_ms | 159 | 3.075 | 0.100 | 3.840 | 21.710 | 67.600 |
| edge.rtt_ms | 159 | 48.878 | 40.000 | 80.960 | 105.620 | 147.400 |
| edge.wait_ms | 159 | 47.925 | 45.100 | 81.720 | 108.750 | 140.200 |
| edge.yolo_ms.cam1 | 159 | 19.683 | 19.600 | 20.200 | 20.410 | 28.100 |
| edge.yolo_ms.cam2 | 159 | 19.537 | 19.500 | 20.020 | 20.300 | 27.400 |
| edge.yolo_ms.total | 159 | 39.220 | 39.000 | 40.000 | 40.700 | 50.400 |
| server.calibration_bundle_ms | 159 | 1.751 | 1.119 | 4.088 | 4.776 | 5.061 |
| server.commit_ms | 159 | 8.700 | 8.070 | 11.940 | 12.500 | 18.213 |
| server.floor_tracking_ms | 159 | 0.001 | 0.001 | 0.002 | 0.002 | 0.021 |
| server.ingest_undistort_ms | 159 | 0.776 | 0.480 | 1.995 | 2.203 | 2.660 |
| server.matching_position_tracking_ms | 159 | 6.551 | 5.614 | 11.904 | 13.278 | 21.416 |
| server.response_prepare_ms | 159 | 0.942 | 0.827 | 1.481 | 1.771 | 2.719 |
| server.risk_ms | 159 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| server.total_ms | 159 | 23.646 | 19.984 | 39.399 | 41.683 | 48.845 |
| server.validation_ms | 159 | 4.921 | 3.031 | 12.446 | 13.497 | 14.207 |

## classroom-1014-s1-t3-v7

Folder: classroom-1014-s1-t3-v7
Session/profile: ('classroom-1014-s1-t3-v7', 'basic')

- Timing rows: 133; successful send records: 133; responses: 133
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 133}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 133
- Observed pair range: 1..335
- Successful sends per input receive-time second: 11.690

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 128 | 132.355 | 129.000 | 169.520 | 178.230 | 313.100 |
| edge.detect_ms.cam1 | 128 | 40.686 | 40.000 | 41.720 | 44.420 | 58.500 |
| edge.detect_ms.cam2 | 128 | 40.043 | 39.700 | 41.160 | 41.700 | 46.500 |
| edge.detect_ms.total | 128 | 80.729 | 79.700 | 82.620 | 87.250 | 104.500 |
| edge.pose_ms.cam1 | 128 | 20.314 | 20.300 | 21.360 | 22.200 | 25.100 |
| edge.pose_ms.cam2 | 128 | 20.355 | 20.300 | 20.930 | 21.230 | 23.300 |
| edge.pose_ms.total | 128 | 40.669 | 40.600 | 42.090 | 43.265 | 48.000 |
| edge.queue_ms | 128 | 3.462 | 0.100 | 8.000 | 30.230 | 65.500 |
| edge.rtt_ms | 128 | 47.262 | 36.600 | 76.290 | 108.080 | 145.500 |
| edge.wait_ms | 128 | 51.590 | 49.500 | 88.500 | 99.185 | 210.700 |
| edge.yolo_ms.cam1 | 128 | 20.343 | 19.700 | 20.500 | 22.185 | 35.200 |
| edge.yolo_ms.cam2 | 128 | 19.655 | 19.500 | 20.300 | 20.700 | 23.100 |
| edge.yolo_ms.total | 128 | 39.998 | 39.100 | 40.560 | 43.415 | 57.300 |
| server.calibration_bundle_ms | 128 | 1.792 | 1.121 | 4.497 | 4.867 | 5.171 |
| server.commit_ms | 128 | 8.825 | 8.104 | 11.573 | 13.566 | 34.779 |
| server.floor_tracking_ms | 128 | 0.001 | 0.001 | 0.002 | 0.002 | 0.003 |
| server.ingest_undistort_ms | 128 | 0.741 | 0.468 | 2.002 | 2.230 | 2.575 |
| server.matching_position_tracking_ms | 128 | 5.061 | 3.904 | 9.291 | 11.554 | 17.064 |
| server.response_prepare_ms | 128 | 0.937 | 0.811 | 1.444 | 1.719 | 3.263 |
| server.risk_ms | 128 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| server.total_ms | 128 | 22.563 | 18.814 | 39.548 | 41.651 | 50.013 |
| server.validation_ms | 128 | 5.203 | 3.074 | 13.686 | 13.812 | 14.976 |

## classroom-1014-s10-t1-v7

Folder: classroom-1014-s10-t1-v7
Session/profile: ('classroom-1014-s10-t1-v7', 'basic')

- Timing rows: 822; successful send records: 822; responses: 822
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 822}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 822
- Observed pair range: 1..2034
- Successful sends per input receive-time second: 9.694

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 817 | 157.365 | 143.500 | 227.200 | 249.920 | 700.400 |
| edge.detect_ms.cam1 | 817 | 49.449 | 41.400 | 84.040 | 95.600 | 205.700 |
| edge.detect_ms.cam2 | 817 | 48.288 | 41.300 | 82.000 | 93.160 | 125.200 |
| edge.detect_ms.total | 817 | 97.737 | 82.900 | 163.320 | 185.660 | 272.400 |
| edge.pose_ms.cam1 | 817 | 25.006 | 21.000 | 44.200 | 49.820 | 92.800 |
| edge.pose_ms.cam2 | 817 | 24.467 | 21.000 | 38.400 | 47.280 | 63.900 |
| edge.pose_ms.total | 817 | 49.473 | 42.000 | 79.740 | 94.600 | 142.600 |
| edge.queue_ms | 817 | 47.870 | 0.100 | 50.900 | 457.900 | 1071.900 |
| edge.rtt_ms | 817 | 50.658 | 36.100 | 74.800 | 110.480 | 1121.100 |
| edge.wait_ms | 817 | 59.583 | 52.400 | 107.240 | 129.660 | 487.800 |
| edge.yolo_ms.cam1 | 817 | 24.412 | 20.400 | 41.200 | 46.400 | 165.900 |
| edge.yolo_ms.cam2 | 817 | 23.789 | 20.300 | 40.440 | 45.220 | 67.100 |
| edge.yolo_ms.total | 817 | 48.201 | 40.800 | 81.140 | 91.800 | 190.300 |
| server.calibration_bundle_ms | 817 | 1.683 | 1.091 | 4.246 | 4.670 | 6.589 |
| server.commit_ms | 817 | 8.840 | 8.395 | 12.010 | 13.187 | 50.759 |
| server.floor_tracking_ms | 817 | 0.001 | 0.001 | 0.002 | 0.003 | 0.016 |
| server.ingest_undistort_ms | 817 | 0.640 | 0.416 | 1.607 | 1.930 | 3.517 |
| server.matching_position_tracking_ms | 817 | 4.665 | 3.756 | 8.949 | 10.825 | 17.905 |
| server.response_prepare_ms | 817 | 0.987 | 0.808 | 1.651 | 2.058 | 4.000 |
| server.risk_ms | 817 | 0.001 | 0.001 | 0.001 | 0.001 | 0.002 |
| server.total_ms | 817 | 21.704 | 18.489 | 36.946 | 40.433 | 61.054 |
| server.validation_ms | 817 | 4.883 | 2.988 | 12.771 | 13.687 | 17.077 |

## classroom-1014-s2-t1-v7

Folder: classroom-1014-s2-t1-v7
Session/profile: ('classroom-1014-s2-t1-v7', 'basic')

- Timing rows: 138; successful send records: 138; responses: 138
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 138}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 138
- Observed pair range: 1..336
- Successful sends per input receive-time second: 12.105

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 133 | 129.250 | 127.800 | 166.020 | 176.320 | 217.300 |
| edge.detect_ms.cam1 | 133 | 39.789 | 39.400 | 40.300 | 41.240 | 52.100 |
| edge.detect_ms.cam2 | 133 | 39.422 | 39.300 | 40.080 | 40.480 | 41.500 |
| edge.detect_ms.total | 133 | 79.211 | 78.900 | 80.200 | 81.000 | 93.600 |
| edge.pose_ms.cam1 | 133 | 20.183 | 20.100 | 20.700 | 20.940 | 22.400 |
| edge.pose_ms.cam2 | 133 | 20.084 | 20.000 | 20.500 | 20.600 | 21.400 |
| edge.pose_ms.total | 133 | 40.268 | 40.200 | 40.980 | 41.200 | 43.300 |
| edge.queue_ms | 133 | 1.632 | 0.100 | 0.100 | 8.880 | 65.400 |
| edge.rtt_ms | 133 | 40.138 | 30.400 | 63.340 | 88.940 | 142.600 |
| edge.wait_ms | 133 | 50.008 | 48.800 | 87.240 | 97.000 | 132.800 |
| edge.yolo_ms.cam1 | 133 | 19.589 | 19.300 | 19.900 | 20.040 | 31.100 |
| edge.yolo_ms.cam2 | 133 | 19.312 | 19.300 | 19.800 | 20.000 | 20.600 |
| edge.yolo_ms.total | 133 | 38.902 | 38.700 | 39.500 | 39.960 | 50.400 |
| server.calibration_bundle_ms | 133 | 1.479 | 0.978 | 4.085 | 4.381 | 5.619 |
| server.commit_ms | 133 | 7.680 | 7.573 | 10.852 | 12.075 | 15.053 |
| server.floor_tracking_ms | 133 | 0.001 | 0.001 | 0.002 | 0.003 | 0.003 |
| server.ingest_undistort_ms | 133 | 0.340 | 0.223 | 0.861 | 1.111 | 1.166 |
| server.matching_position_tracking_ms | 133 | 2.479 | 1.859 | 4.954 | 6.785 | 7.862 |
| server.response_prepare_ms | 133 | 0.975 | 0.759 | 1.910 | 2.294 | 3.189 |
| server.risk_ms | 133 | 0.001 | 0.001 | 0.001 | 0.001 | 0.002 |
| server.total_ms | 133 | 17.790 | 15.154 | 31.765 | 35.635 | 43.035 |
| server.validation_ms | 133 | 4.832 | 3.040 | 12.616 | 13.682 | 14.128 |

## classroom-1014-s3-t1-v7

Folder: classroom-1014-s3-t1-v7
Session/profile: ('classroom-1014-s3-t1-v7', 'basic')

- Timing rows: 162; successful send records: 162; responses: 162
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 162}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 162
- Observed pair range: 1..377
- Successful sends per input receive-time second: 11.971

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 157 | 132.173 | 127.700 | 180.500 | 207.100 | 272.000 |
| edge.detect_ms.cam1 | 157 | 39.650 | 39.100 | 40.080 | 41.900 | 54.900 |
| edge.detect_ms.cam2 | 157 | 39.006 | 38.900 | 39.540 | 39.800 | 42.300 |
| edge.detect_ms.total | 157 | 78.656 | 78.100 | 79.700 | 82.100 | 95.900 |
| edge.pose_ms.cam1 | 157 | 19.987 | 19.900 | 20.400 | 20.500 | 22.400 |
| edge.pose_ms.cam2 | 157 | 19.890 | 19.800 | 20.300 | 20.500 | 22.000 |
| edge.pose_ms.total | 157 | 39.877 | 39.800 | 40.400 | 40.800 | 43.100 |
| edge.queue_ms | 157 | 3.285 | 0.100 | 4.040 | 24.460 | 91.800 |
| edge.rtt_ms | 157 | 42.443 | 34.600 | 70.080 | 93.320 | 168.200 |
| edge.wait_ms | 157 | 53.489 | 49.900 | 102.380 | 121.940 | 184.900 |
| edge.yolo_ms.cam1 | 157 | 19.643 | 19.100 | 19.740 | 21.320 | 33.900 |
| edge.yolo_ms.cam2 | 157 | 19.096 | 19.000 | 19.500 | 19.700 | 20.300 |
| edge.yolo_ms.total | 157 | 38.739 | 38.200 | 39.300 | 40.600 | 53.000 |
| server.calibration_bundle_ms | 157 | 1.543 | 1.000 | 3.970 | 4.188 | 4.652 |
| server.commit_ms | 157 | 8.029 | 7.876 | 10.919 | 12.116 | 15.882 |
| server.floor_tracking_ms | 157 | 0.002 | 0.001 | 0.003 | 0.004 | 0.018 |
| server.ingest_undistort_ms | 157 | 0.359 | 0.225 | 0.839 | 1.098 | 1.253 |
| server.matching_position_tracking_ms | 157 | 2.595 | 1.823 | 6.131 | 7.013 | 9.141 |
| server.response_prepare_ms | 157 | 1.107 | 0.788 | 2.323 | 2.849 | 3.232 |
| server.risk_ms | 157 | 0.001 | 0.001 | 0.001 | 0.002 | 0.030 |
| server.total_ms | 157 | 18.706 | 15.499 | 31.618 | 37.081 | 41.848 |
| server.validation_ms | 157 | 5.067 | 3.075 | 12.145 | 13.649 | 15.263 |

## classroom-1014-s4-t1-v7

Folder: classroom-1014-s4-t1-v7
Session/profile: ('classroom-1014-s4-t1-v7', 'basic')

- Timing rows: 181; successful send records: 181; responses: 181
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 181}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 181
- Observed pair range: 1..406
- Successful sends per input receive-time second: 10.750

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 176 | 140.802 | 129.350 | 182.350 | 237.600 | 338.400 |
| edge.detect_ms.cam1 | 176 | 41.114 | 39.500 | 44.400 | 53.825 | 65.100 |
| edge.detect_ms.cam2 | 176 | 39.884 | 39.300 | 42.850 | 44.050 | 50.900 |
| edge.detect_ms.total | 176 | 80.998 | 78.800 | 88.050 | 98.150 | 116.000 |
| edge.pose_ms.cam1 | 176 | 20.543 | 20.100 | 22.300 | 23.225 | 26.100 |
| edge.pose_ms.cam2 | 176 | 20.311 | 20.100 | 21.750 | 22.100 | 26.400 |
| edge.pose_ms.total | 176 | 40.854 | 40.200 | 44.300 | 45.275 | 48.600 |
| edge.queue_ms | 176 | 140.183 | 0.100 | 726.650 | 952.100 | 1248.500 |
| edge.rtt_ms | 176 | 53.163 | 31.450 | 62.050 | 107.475 | 1326.900 |
| edge.wait_ms | 176 | 59.770 | 50.400 | 104.300 | 152.675 | 236.600 |
| edge.yolo_ms.cam1 | 176 | 20.550 | 19.400 | 22.000 | 30.275 | 42.800 |
| edge.yolo_ms.cam2 | 176 | 19.565 | 19.200 | 21.100 | 21.800 | 24.500 |
| edge.yolo_ms.total | 176 | 40.115 | 38.600 | 43.050 | 52.275 | 67.300 |
| server.calibration_bundle_ms | 176 | 1.621 | 1.002 | 3.966 | 4.266 | 4.724 |
| server.commit_ms | 176 | 8.132 | 7.648 | 11.422 | 13.427 | 18.731 |
| server.floor_tracking_ms | 176 | 0.002 | 0.001 | 0.003 | 0.004 | 0.007 |
| server.ingest_undistort_ms | 176 | 0.398 | 0.254 | 0.924 | 1.124 | 1.500 |
| server.matching_position_tracking_ms | 176 | 2.524 | 1.783 | 5.124 | 6.873 | 15.350 |
| server.response_prepare_ms | 176 | 1.069 | 0.764 | 2.151 | 2.925 | 3.728 |
| server.risk_ms | 176 | 0.001 | 0.001 | 0.001 | 0.002 | 0.003 |
| server.total_ms | 176 | 18.868 | 15.593 | 36.129 | 38.223 | 45.662 |
| server.validation_ms | 176 | 5.118 | 3.067 | 12.516 | 13.910 | 14.365 |

## classroom-1014-s4-t2-v7

Folder: classroom-1014-s4-t2-v7
Session/profile: ('classroom-1014-s4-t2-v7', 'basic')

- Timing rows: 143; successful send records: 143; responses: 143
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 143}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 143
- Observed pair range: 1..348
- Successful sends per input receive-time second: 12.100

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 138 | 136.356 | 130.800 | 183.560 | 196.960 | 316.700 |
| edge.detect_ms.cam1 | 138 | 40.000 | 39.600 | 40.200 | 41.015 | 59.600 |
| edge.detect_ms.cam2 | 138 | 39.561 | 39.400 | 40.130 | 40.400 | 47.400 |
| edge.detect_ms.total | 138 | 79.561 | 78.900 | 79.930 | 80.905 | 106.300 |
| edge.pose_ms.cam1 | 138 | 20.259 | 20.100 | 20.630 | 20.900 | 25.000 |
| edge.pose_ms.cam2 | 138 | 20.147 | 20.100 | 20.500 | 20.815 | 23.900 |
| edge.pose_ms.total | 138 | 40.406 | 40.200 | 41.000 | 41.300 | 48.500 |
| edge.queue_ms | 138 | 3.684 | 0.100 | 12.060 | 30.335 | 62.400 |
| edge.rtt_ms | 138 | 45.428 | 35.650 | 74.870 | 108.035 | 140.500 |
| edge.wait_ms | 138 | 56.761 | 52.250 | 102.680 | 115.670 | 210.400 |
| edge.yolo_ms.cam1 | 138 | 19.727 | 19.350 | 19.900 | 20.515 | 34.500 |
| edge.yolo_ms.cam2 | 138 | 19.393 | 19.300 | 19.800 | 19.900 | 23.500 |
| edge.yolo_ms.total | 138 | 39.120 | 38.600 | 39.500 | 40.160 | 58.000 |
| server.calibration_bundle_ms | 138 | 1.650 | 1.037 | 4.220 | 4.471 | 7.099 |
| server.commit_ms | 138 | 8.126 | 8.067 | 11.484 | 12.573 | 18.479 |
| server.floor_tracking_ms | 138 | 0.002 | 0.001 | 0.003 | 0.003 | 0.016 |
| server.ingest_undistort_ms | 138 | 0.428 | 0.270 | 1.096 | 1.243 | 1.544 |
| server.matching_position_tracking_ms | 138 | 3.110 | 2.052 | 7.069 | 8.849 | 11.014 |
| server.response_prepare_ms | 138 | 1.177 | 0.818 | 2.398 | 3.055 | 4.403 |
| server.risk_ms | 138 | 0.001 | 0.001 | 0.001 | 0.002 | 0.003 |
| server.total_ms | 138 | 19.773 | 16.141 | 36.198 | 39.452 | 48.831 |
| server.validation_ms | 138 | 5.275 | 3.108 | 13.319 | 13.984 | 15.624 |

## classroom-1014-s5-t1-v7

Folder: classroom-1014-s5-t1-v7
Session/profile: ('classroom-1014-s5-t1-v7', 'basic')

- Timing rows: 154; successful send records: 154; responses: 154
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 154}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 154
- Observed pair range: 1..382
- Successful sends per input receive-time second: 12.194

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 149 | 133.143 | 131.700 | 171.160 | 189.560 | 214.300 |
| edge.detect_ms.cam1 | 149 | 40.306 | 39.900 | 41.020 | 42.560 | 53.100 |
| edge.detect_ms.cam2 | 149 | 40.170 | 39.900 | 40.600 | 41.240 | 65.500 |
| edge.detect_ms.total | 149 | 80.476 | 79.900 | 81.240 | 84.260 | 106.000 |
| edge.pose_ms.cam1 | 149 | 20.509 | 20.400 | 21.100 | 21.200 | 25.100 |
| edge.pose_ms.cam2 | 149 | 20.489 | 20.400 | 20.800 | 21.100 | 33.000 |
| edge.pose_ms.total | 149 | 40.999 | 40.800 | 41.700 | 42.340 | 53.900 |
| edge.queue_ms | 149 | 96.668 | 0.100 | 421.540 | 686.100 | 1030.600 |
| edge.rtt_ms | 149 | 51.588 | 33.300 | 68.380 | 110.700 | 1136.100 |
| edge.wait_ms | 149 | 52.633 | 50.900 | 91.540 | 109.680 | 129.200 |
| edge.yolo_ms.cam1 | 149 | 19.765 | 19.600 | 20.100 | 20.780 | 31.000 |
| edge.yolo_ms.cam2 | 149 | 19.665 | 19.600 | 20.000 | 20.600 | 32.500 |
| edge.yolo_ms.total | 149 | 39.430 | 39.100 | 39.920 | 41.940 | 52.200 |
| server.calibration_bundle_ms | 149 | 1.453 | 1.004 | 2.937 | 4.330 | 4.766 |
| server.commit_ms | 149 | 8.101 | 7.310 | 11.820 | 14.152 | 22.885 |
| server.floor_tracking_ms | 149 | 0.001 | 0.001 | 0.002 | 0.003 | 0.005 |
| server.ingest_undistort_ms | 149 | 0.405 | 0.292 | 0.930 | 1.269 | 1.540 |
| server.matching_position_tracking_ms | 149 | 3.053 | 2.632 | 5.070 | 7.364 | 12.773 |
| server.response_prepare_ms | 149 | 0.994 | 0.789 | 1.957 | 2.255 | 4.249 |
| server.risk_ms | 149 | 0.001 | 0.001 | 0.001 | 0.001 | 0.002 |
| server.total_ms | 149 | 18.670 | 15.361 | 32.132 | 37.953 | 48.917 |
| server.validation_ms | 149 | 4.659 | 2.903 | 12.270 | 13.854 | 14.614 |

## classroom-1014-s5-t2-v7

Folder: classroom-1014-s5-t2-v7
Session/profile: ('classroom-1014-s5-t2-v7', 'basic')

- Timing rows: 181; successful send records: 181; responses: 181
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 181}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 181
- Observed pair range: 2..408
- Successful sends per input receive-time second: 11.427

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 176 | 135.562 | 127.700 | 182.900 | 207.275 | 579.400 |
| edge.detect_ms.cam1 | 176 | 39.650 | 38.900 | 39.900 | 45.900 | 59.900 |
| edge.detect_ms.cam2 | 176 | 38.830 | 38.800 | 39.300 | 39.525 | 42.500 |
| edge.detect_ms.total | 176 | 78.480 | 77.800 | 79.250 | 84.625 | 98.200 |
| edge.pose_ms.cam1 | 176 | 19.856 | 19.800 | 20.300 | 20.400 | 22.000 |
| edge.pose_ms.cam2 | 176 | 19.757 | 19.700 | 20.100 | 20.225 | 21.500 |
| edge.pose_ms.total | 176 | 39.614 | 39.500 | 40.100 | 40.350 | 42.700 |
| edge.queue_ms | 176 | 53.728 | 0.100 | 81.950 | 440.825 | 1042.700 |
| edge.rtt_ms | 176 | 50.229 | 36.100 | 75.400 | 109.325 | 1119.800 |
| edge.wait_ms | 176 | 57.045 | 50.000 | 102.400 | 127.650 | 481.100 |
| edge.yolo_ms.cam1 | 176 | 19.774 | 19.100 | 19.800 | 25.900 | 39.900 |
| edge.yolo_ms.cam2 | 176 | 19.045 | 19.000 | 19.400 | 19.625 | 21.000 |
| edge.yolo_ms.total | 176 | 38.819 | 38.100 | 38.900 | 44.700 | 58.800 |
| server.calibration_bundle_ms | 176 | 1.704 | 1.030 | 4.246 | 4.350 | 4.579 |
| server.commit_ms | 176 | 7.903 | 7.362 | 11.120 | 12.545 | 17.181 |
| server.floor_tracking_ms | 176 | 0.001 | 0.001 | 0.003 | 0.003 | 0.004 |
| server.ingest_undistort_ms | 176 | 0.489 | 0.295 | 1.300 | 1.394 | 1.639 |
| server.matching_position_tracking_ms | 176 | 3.402 | 2.602 | 7.227 | 8.222 | 9.774 |
| server.response_prepare_ms | 176 | 1.011 | 0.802 | 2.017 | 2.479 | 3.123 |
| server.risk_ms | 176 | 0.001 | 0.001 | 0.001 | 0.001 | 0.002 |
| server.total_ms | 176 | 19.938 | 15.933 | 36.317 | 39.015 | 44.404 |
| server.validation_ms | 176 | 5.425 | 2.984 | 13.216 | 13.675 | 16.286 |

## classroom-1014-s6-t1-v7

Folder: classroom-1014-s6-t1-v7
Session/profile: ('classroom-1014-s6-t1-v7', 'basic')

- Timing rows: 59; successful send records: 59; responses: 59
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 59}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 59
- Observed pair range: 2..167
- Successful sends per input receive-time second: 12.018

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 54 | 134.439 | 130.600 | 175.530 | 186.045 | 252.900 |
| edge.detect_ms.cam1 | 54 | 40.033 | 39.650 | 40.670 | 41.505 | 49.900 |
| edge.detect_ms.cam2 | 54 | 39.681 | 39.700 | 40.400 | 40.435 | 41.000 |
| edge.detect_ms.total | 54 | 79.715 | 79.400 | 80.770 | 81.305 | 89.600 |
| edge.pose_ms.cam1 | 54 | 20.146 | 20.100 | 20.670 | 20.835 | 21.000 |
| edge.pose_ms.cam2 | 54 | 20.194 | 20.200 | 20.600 | 20.635 | 20.800 |
| edge.pose_ms.total | 54 | 40.341 | 40.300 | 40.900 | 41.135 | 41.500 |
| edge.queue_ms | 54 | 263.319 | 34.250 | 801.380 | 911.970 | 1042.900 |
| edge.rtt_ms | 54 | 62.885 | 33.200 | 70.440 | 111.680 | 1121.900 |
| edge.wait_ms | 54 | 54.681 | 51.300 | 96.120 | 106.140 | 165.100 |
| edge.yolo_ms.cam1 | 54 | 19.867 | 19.500 | 20.240 | 21.090 | 29.800 |
| edge.yolo_ms.cam2 | 54 | 19.469 | 19.400 | 19.900 | 20.135 | 20.200 |
| edge.yolo_ms.total | 54 | 39.335 | 38.850 | 40.000 | 40.620 | 49.500 |
| server.calibration_bundle_ms | 54 | 1.692 | 1.073 | 3.563 | 4.315 | 4.863 |
| server.commit_ms | 54 | 8.179 | 7.733 | 11.342 | 11.823 | 14.403 |
| server.floor_tracking_ms | 54 | 0.001 | 0.001 | 0.002 | 0.002 | 0.002 |
| server.ingest_undistort_ms | 54 | 0.675 | 0.425 | 1.359 | 1.720 | 2.172 |
| server.matching_position_tracking_ms | 54 | 4.551 | 3.407 | 8.011 | 9.563 | 9.979 |
| server.response_prepare_ms | 54 | 0.924 | 0.775 | 1.440 | 1.716 | 1.988 |
| server.risk_ms | 54 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| server.total_ms | 54 | 20.820 | 17.362 | 34.587 | 38.512 | 41.244 |
| server.validation_ms | 54 | 4.796 | 2.862 | 11.421 | 12.819 | 13.709 |

## classroom-1014-s7-t1-v7

Folder: classroom-1014-s7-t1-v7
Session/profile: ('classroom-1014-s7-t1-v7', 'basic')

- Timing rows: 139; successful send records: 139; responses: 139
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 139}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 139
- Observed pair range: 1..317
- Successful sends per input receive-time second: 10.817

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 134 | 135.013 | 127.250 | 183.660 | 200.405 | 250.300 |
| edge.detect_ms.cam1 | 134 | 40.593 | 39.500 | 41.800 | 45.855 | 64.800 |
| edge.detect_ms.cam2 | 134 | 39.702 | 39.400 | 40.940 | 42.105 | 46.800 |
| edge.detect_ms.total | 134 | 80.295 | 78.850 | 82.340 | 88.615 | 111.600 |
| edge.pose_ms.cam1 | 134 | 20.443 | 20.200 | 21.300 | 22.210 | 26.200 |
| edge.pose_ms.cam2 | 134 | 20.224 | 20.100 | 20.670 | 21.535 | 23.700 |
| edge.pose_ms.total | 134 | 40.667 | 40.300 | 41.770 | 43.320 | 48.800 |
| edge.queue_ms | 134 | 2.256 | 0.100 | 4.000 | 17.730 | 39.600 |
| edge.rtt_ms | 134 | 41.632 | 34.650 | 71.710 | 94.760 | 118.300 |
| edge.wait_ms | 134 | 54.698 | 48.550 | 105.410 | 120.370 | 163.800 |
| edge.yolo_ms.cam1 | 134 | 20.126 | 19.400 | 20.710 | 23.250 | 39.900 |
| edge.yolo_ms.cam2 | 134 | 19.460 | 19.300 | 20.270 | 20.735 | 23.100 |
| edge.yolo_ms.total | 134 | 39.586 | 38.600 | 40.570 | 43.690 | 63.000 |
| server.calibration_bundle_ms | 134 | 1.499 | 0.957 | 3.821 | 3.966 | 4.501 |
| server.commit_ms | 134 | 7.447 | 7.082 | 10.582 | 11.835 | 14.486 |
| server.floor_tracking_ms | 134 | 0.002 | 0.001 | 0.003 | 0.004 | 0.007 |
| server.ingest_undistort_ms | 134 | 0.282 | 0.181 | 0.705 | 0.864 | 1.107 |
| server.matching_position_tracking_ms | 134 | 1.681 | 1.064 | 4.171 | 4.482 | 6.309 |
| server.response_prepare_ms | 134 | 1.077 | 0.784 | 2.422 | 2.965 | 3.924 |
| server.risk_ms | 134 | 0.001 | 0.001 | 0.002 | 0.002 | 0.003 |
| server.total_ms | 134 | 17.176 | 14.081 | 32.458 | 34.544 | 43.476 |
| server.validation_ms | 134 | 5.183 | 2.985 | 13.043 | 13.912 | 16.667 |

## classroom-1014-s7-t2-v7

Folder: classroom-1014-s7-t2-v7
Session/profile: ('classroom-1014-s7-t2-v7', 'basic')

- Timing rows: 109; successful send records: 109; responses: 109
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 109}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 109
- Observed pair range: 1..265
- Successful sends per input receive-time second: 11.331

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 104 | 139.942 | 130.200 | 197.700 | 218.100 | 347.600 |
| edge.detect_ms.cam1 | 104 | 40.968 | 39.500 | 42.210 | 53.080 | 67.400 |
| edge.detect_ms.cam2 | 104 | 39.725 | 39.400 | 40.640 | 42.210 | 46.800 |
| edge.detect_ms.total | 104 | 80.693 | 78.950 | 82.450 | 95.965 | 114.200 |
| edge.pose_ms.cam1 | 104 | 20.557 | 20.200 | 21.300 | 22.925 | 26.500 |
| edge.pose_ms.cam2 | 104 | 20.247 | 20.200 | 20.800 | 21.285 | 23.700 |
| edge.pose_ms.total | 104 | 40.804 | 40.400 | 41.700 | 44.385 | 50.000 |
| edge.queue_ms | 104 | 2.487 | 0.100 | 0.100 | 20.585 | 57.600 |
| edge.rtt_ms | 104 | 40.883 | 30.150 | 81.030 | 101.570 | 135.200 |
| edge.wait_ms | 104 | 59.219 | 51.900 | 113.400 | 138.970 | 245.000 |
| edge.yolo_ms.cam1 | 104 | 20.398 | 19.400 | 21.000 | 30.745 | 41.100 |
| edge.yolo_ms.cam2 | 104 | 19.472 | 19.300 | 20.100 | 20.995 | 23.100 |
| edge.yolo_ms.total | 104 | 39.870 | 38.600 | 40.650 | 51.980 | 64.200 |
| server.calibration_bundle_ms | 104 | 1.330 | 0.941 | 2.658 | 3.896 | 4.254 |
| server.commit_ms | 104 | 7.646 | 6.859 | 10.911 | 12.222 | 14.422 |
| server.floor_tracking_ms | 104 | 0.001 | 0.001 | 0.003 | 0.004 | 0.006 |
| server.ingest_undistort_ms | 104 | 0.258 | 0.187 | 0.551 | 0.804 | 0.936 |
| server.matching_position_tracking_ms | 104 | 1.663 | 1.036 | 4.446 | 4.751 | 6.138 |
| server.response_prepare_ms | 104 | 0.942 | 0.742 | 1.675 | 2.573 | 3.343 |
| server.risk_ms | 104 | 0.001 | 0.001 | 0.001 | 0.002 | 0.003 |
| server.total_ms | 104 | 16.271 | 13.811 | 28.493 | 34.808 | 38.020 |
| server.validation_ms | 104 | 4.426 | 2.889 | 9.929 | 12.926 | 13.475 |

## classroom-1014-s8-t1-v7

Folder: classroom-1014-s8-t1-v7
Session/profile: ('classroom-1014-s8-t1-v7', 'basic')

- Timing rows: 182; successful send records: 182; responses: 182
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 182}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 182
- Observed pair range: 2..408
- Successful sends per input receive-time second: 11.832

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 177 | 135.532 | 128.300 | 178.440 | 205.100 | 296.300 |
| edge.detect_ms.cam1 | 177 | 40.286 | 39.400 | 41.500 | 45.520 | 57.900 |
| edge.detect_ms.cam2 | 177 | 39.568 | 39.300 | 40.660 | 41.640 | 45.100 |
| edge.detect_ms.total | 177 | 79.854 | 78.600 | 82.140 | 87.140 | 102.600 |
| edge.pose_ms.cam1 | 177 | 20.319 | 20.100 | 21.040 | 21.920 | 24.900 |
| edge.pose_ms.cam2 | 177 | 20.181 | 20.100 | 20.800 | 21.220 | 22.200 |
| edge.pose_ms.total | 177 | 40.501 | 40.200 | 41.840 | 42.920 | 47.100 |
| edge.queue_ms | 177 | 16.334 | 0.100 | 30.300 | 117.480 | 344.200 |
| edge.rtt_ms | 177 | 51.546 | 42.400 | 89.900 | 105.820 | 424.300 |
| edge.wait_ms | 177 | 55.654 | 49.400 | 100.100 | 121.800 | 194.600 |
| edge.yolo_ms.cam1 | 177 | 19.944 | 19.300 | 20.500 | 22.360 | 35.300 |
| edge.yolo_ms.cam2 | 177 | 19.363 | 19.200 | 20.040 | 20.620 | 22.900 |
| edge.yolo_ms.total | 177 | 39.306 | 38.500 | 40.340 | 42.640 | 56.200 |
| server.calibration_bundle_ms | 177 | 1.513 | 0.987 | 3.556 | 4.164 | 4.437 |
| server.commit_ms | 177 | 8.051 | 7.947 | 11.590 | 12.405 | 21.668 |
| server.floor_tracking_ms | 177 | 0.001 | 0.001 | 0.003 | 0.003 | 0.004 |
| server.ingest_undistort_ms | 177 | 0.367 | 0.230 | 0.911 | 1.104 | 1.365 |
| server.matching_position_tracking_ms | 177 | 2.394 | 1.808 | 4.907 | 5.911 | 9.417 |
| server.response_prepare_ms | 177 | 1.040 | 0.790 | 2.081 | 2.736 | 3.247 |
| server.risk_ms | 177 | 0.001 | 0.001 | 0.001 | 0.002 | 0.002 |
| server.total_ms | 177 | 18.410 | 15.528 | 31.216 | 35.812 | 44.714 |
| server.validation_ms | 177 | 5.039 | 2.953 | 12.005 | 12.987 | 13.729 |

## classroom-1014-s9-t1-v7

Folder: classroom-1014-s9-t1-v7
Session/profile: ('classroom-1014-s9-t1-v7', 'basic')

- Timing rows: 243; successful send records: 243; responses: 243
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 243}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 243
- Observed pair range: 1..573
- Successful sends per input receive-time second: 11.163

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 238 | 142.401 | 135.050 | 186.030 | 200.655 | 525.000 |
| edge.detect_ms.cam1 | 238 | 43.051 | 40.200 | 46.800 | 52.615 | 224.600 |
| edge.detect_ms.cam2 | 238 | 42.407 | 40.050 | 46.080 | 49.615 | 204.400 |
| edge.detect_ms.total | 238 | 85.458 | 80.200 | 94.330 | 101.165 | 429.000 |
| edge.pose_ms.cam1 | 238 | 22.117 | 20.600 | 23.700 | 24.875 | 199.300 |
| edge.pose_ms.cam2 | 238 | 21.358 | 20.500 | 23.500 | 24.400 | 68.100 |
| edge.pose_ms.total | 238 | 43.475 | 41.000 | 47.400 | 49.530 | 233.600 |
| edge.queue_ms | 238 | 431.790 | 196.800 | 1150.100 | 1456.795 | 2024.300 |
| edge.rtt_ms | 238 | 65.725 | 31.950 | 75.920 | 122.140 | 1293.300 |
| edge.wait_ms | 238 | 56.908 | 51.950 | 97.030 | 109.950 | 320.700 |
| edge.yolo_ms.cam1 | 238 | 20.916 | 19.700 | 23.100 | 24.860 | 58.500 |
| edge.yolo_ms.cam2 | 238 | 21.031 | 19.700 | 23.200 | 25.200 | 170.000 |
| edge.yolo_ms.total | 238 | 41.946 | 39.300 | 46.030 | 50.730 | 195.200 |
| server.calibration_bundle_ms | 238 | 1.453 | 0.968 | 3.191 | 4.033 | 4.632 |
| server.commit_ms | 238 | 7.843 | 7.338 | 10.927 | 12.005 | 36.874 |
| server.floor_tracking_ms | 238 | 0.001 | 0.001 | 0.002 | 0.003 | 0.004 |
| server.ingest_undistort_ms | 238 | 0.353 | 0.229 | 0.787 | 1.021 | 1.423 |
| server.matching_position_tracking_ms | 238 | 2.346 | 1.768 | 4.623 | 6.191 | 7.852 |
| server.response_prepare_ms | 238 | 0.992 | 0.755 | 2.017 | 2.454 | 3.365 |
| server.risk_ms | 238 | 0.001 | 0.001 | 0.001 | 0.001 | 0.002 |
| server.total_ms | 238 | 17.745 | 14.393 | 30.934 | 34.093 | 46.031 |
| server.validation_ms | 238 | 4.754 | 2.866 | 11.473 | 12.917 | 15.501 |

