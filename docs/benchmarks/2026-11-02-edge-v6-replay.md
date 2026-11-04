# v6 녹화 15세션 실측 검증 (2026-11-02)

출처: 사용자 제공 v6-edge-logs.zip 및 PR #73 리뷰. 원본 로그는 ai/runs/week1-v6-received/에 보관하며 Git에는 포함하지 않는다.

- 배포 서버 ba7ec7e, 엣지 ba17304는 PR 리뷰에서 공유한 실행 커밋이다. ZIP에는 replay 실행 메타데이터 2개와 세션별 edge_config.json이 있다.
- 장비: PR 공유 기준 MacBook Pro M3 Pro / MPS, COCO yolo11n.pt + yolo11n-pose.pt. ZIP 설정: imgsz 1280, foot ankle, conf 0.4, person 0.5.
- replay 메타데이터: 23:12:26~23:15:28에 9세션, 23:24:31~23:27:36에 나머지 6세션. 시각에는 UTC offset이 없어 파일 표기를 그대로 기록한다.
- 전체 2884짝 전송·응답, timings status 201이 2884건. 응답 누락·실패·dropped는 모두 0이다.
- 세션마다 앞 5짝을 제외한 2809표본의 평균·P50·P90·P95·최댓값은 PR 리뷰 표와 소수 첫째 자리까지 일치한다.
- 서버 단계별 시간은 계측 배포 전이므로 unavailable이다. 서버 최적화 두 단계는 v7 계측 후 결정한다.
- 전송률은 예열을 제외한 성공 입력 수신 시각 기준이다. RTT는 화면 표시까지의 전체 지연이 아니다. 엣지 age_ms와 RTT에는 전송 큐 대기가 빠져 있어 둘의 합도 전체 지연으로 해석하지 않는다.

재현: docs/specs/server-profiling.md의 여러 폴더 명령에서 --warmup 5를 사용한다.

# Edge and server measurement report

## Overall

Sessions: 15; warmup: first 5 observed pairs per session.
Latency statistics pool individual samples; record/status counts include warmup; send rates exclude warmup.
- Records (all pairs): {'timings': 2884, 'sent': 2884, 'responses': 2884, 'failed': 0, 'missing_responses': 0, 'orphan_responses': 0, 'pairs_in_all_three_logs': 2884}
- Timing status counts (all rows): {'201': 2884}
- Detection failure status counts (all rows): {}

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 2809 | 147.365 | 139.400 | 196.220 | 221.680 | 639.900 |
| edge.detect_ms.cam1 | 2809 | 44.578 | 43.000 | 47.900 | 52.300 | 319.700 |
| edge.detect_ms.cam2 | 2809 | 44.134 | 42.800 | 46.700 | 50.200 | 262.000 |
| edge.detect_ms.total | 2809 | 88.712 | 85.900 | 95.500 | 102.200 | 366.600 |
| edge.pose_ms.cam1 | 2809 | 22.420 | 21.800 | 24.200 | 25.660 | 126.200 |
| edge.pose_ms.cam2 | 2809 | 22.351 | 21.700 | 23.800 | 25.300 | 136.700 |
| edge.pose_ms.total | 2809 | 44.771 | 43.500 | 47.900 | 51.060 | 158.900 |
| edge.queue_ms | 2809 | 5.971 | 0.100 | 18.920 | 35.100 | 567.100 |
| edge.rtt_ms | 2809 | 53.306 | 40.500 | 103.720 | 118.360 | 652.800 |
| edge.wait_ms | 2809 | 58.609 | 51.700 | 105.400 | 127.960 | 537.600 |
| edge.yolo_ms.cam1 | 2809 | 22.131 | 21.100 | 23.700 | 26.560 | 253.100 |
| edge.yolo_ms.cam2 | 2809 | 21.755 | 21.000 | 23.100 | 24.300 | 191.600 |
| edge.yolo_ms.total | 2809 | 43.886 | 42.200 | 47.000 | 51.800 | 277.500 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s1-t1-v6

Folder: classroom-1014-s1-t1-v6
Session/profile: ('classroom-1014-s1-t1-v6', 'basic')

- Timing rows: 208; successful send records: 208; responses: 208
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 208}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 208
- Observed pair range: 1..524
- Successful sends per input receive-time second: 10.842

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 203 | 146.769 | 137.300 | 191.640 | 223.150 | 573.800 |
| edge.detect_ms.cam1 | 203 | 42.576 | 41.800 | 44.280 | 50.250 | 63.600 |
| edge.detect_ms.cam2 | 203 | 41.936 | 41.600 | 43.700 | 44.290 | 61.200 |
| edge.detect_ms.total | 203 | 84.513 | 83.400 | 87.900 | 93.190 | 108.900 |
| edge.pose_ms.cam1 | 203 | 21.337 | 21.100 | 22.400 | 22.990 | 32.700 |
| edge.pose_ms.cam2 | 203 | 21.237 | 21.100 | 22.100 | 22.870 | 26.600 |
| edge.pose_ms.total | 203 | 42.574 | 42.200 | 44.080 | 45.580 | 53.100 |
| edge.queue_ms | 203 | 4.377 | 0.100 | 19.080 | 32.070 | 75.300 |
| edge.rtt_ms | 203 | 55.851 | 43.600 | 102.520 | 117.960 | 156.800 |
| edge.wait_ms | 203 | 62.206 | 54.300 | 105.740 | 137.630 | 473.700 |
| edge.yolo_ms.cam1 | 203 | 21.215 | 20.600 | 22.160 | 24.260 | 38.700 |
| edge.yolo_ms.cam2 | 203 | 20.663 | 20.500 | 21.600 | 22.290 | 38.200 |
| edge.yolo_ms.total | 203 | 41.878 | 41.100 | 43.380 | 49.150 | 59.000 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s1-t2-v6

Folder: classroom-1014-s1-t2-v6
Session/profile: ('classroom-1014-s1-t2-v6', 'basic')

- Timing rows: 155; successful send records: 155; responses: 155
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 155}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 155
- Observed pair range: 1..401
- Successful sends per input receive-time second: 11.759

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 150 | 134.922 | 131.400 | 175.410 | 194.280 | 236.300 |
| edge.detect_ms.cam1 | 150 | 41.816 | 41.400 | 43.200 | 44.165 | 64.900 |
| edge.detect_ms.cam2 | 150 | 41.652 | 41.400 | 42.900 | 43.555 | 55.500 |
| edge.detect_ms.total | 150 | 83.468 | 82.900 | 85.510 | 87.275 | 107.700 |
| edge.pose_ms.cam1 | 150 | 21.292 | 21.000 | 22.200 | 22.655 | 32.800 |
| edge.pose_ms.cam2 | 150 | 21.026 | 20.850 | 22.010 | 22.455 | 23.900 |
| edge.pose_ms.total | 150 | 42.318 | 42.000 | 43.700 | 44.565 | 55.400 |
| edge.queue_ms | 150 | 5.022 | 0.100 | 26.780 | 38.365 | 46.900 |
| edge.rtt_ms | 150 | 54.983 | 42.450 | 108.120 | 119.550 | 127.800 |
| edge.wait_ms | 150 | 51.409 | 47.500 | 90.900 | 112.010 | 150.700 |
| edge.yolo_ms.cam1 | 150 | 20.493 | 20.200 | 21.300 | 22.100 | 32.100 |
| edge.yolo_ms.cam2 | 150 | 20.598 | 20.400 | 21.400 | 21.900 | 34.500 |
| edge.yolo_ms.total | 150 | 41.091 | 40.800 | 42.210 | 43.200 | 54.300 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s1-t3-v6

Folder: classroom-1014-s1-t3-v6
Session/profile: ('classroom-1014-s1-t3-v6', 'basic')

- Timing rows: 116; successful send records: 116; responses: 116
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 116}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 116
- Observed pair range: 1..333
- Successful sends per input receive-time second: 10.288

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 111 | 148.159 | 141.400 | 209.200 | 227.150 | 299.800 |
| edge.detect_ms.cam1 | 111 | 47.070 | 42.600 | 52.600 | 76.900 | 158.100 |
| edge.detect_ms.cam2 | 111 | 44.572 | 42.400 | 48.400 | 53.100 | 111.100 |
| edge.detect_ms.total | 111 | 91.642 | 84.700 | 98.100 | 128.150 | 208.300 |
| edge.pose_ms.cam1 | 111 | 23.586 | 21.400 | 25.400 | 40.250 | 68.700 |
| edge.pose_ms.cam2 | 111 | 22.459 | 21.500 | 24.600 | 25.900 | 55.700 |
| edge.pose_ms.total | 111 | 46.045 | 42.800 | 50.100 | 67.500 | 91.900 |
| edge.queue_ms | 111 | 4.953 | 0.100 | 26.100 | 33.750 | 63.600 |
| edge.rtt_ms | 111 | 55.557 | 41.000 | 112.400 | 120.800 | 148.400 |
| edge.wait_ms | 111 | 56.471 | 50.200 | 105.300 | 135.950 | 209.800 |
| edge.yolo_ms.cam1 | 111 | 23.450 | 20.900 | 27.300 | 32.950 | 105.100 |
| edge.yolo_ms.cam2 | 111 | 22.078 | 20.900 | 24.000 | 26.000 | 83.700 |
| edge.yolo_ms.total | 111 | 45.529 | 42.000 | 50.800 | 56.550 | 129.100 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s10-t1-v6

Folder: classroom-1014-s10-t1-v6
Session/profile: ('classroom-1014-s10-t1-v6', 'basic')

- Timing rows: 908; successful send records: 908; responses: 908
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 908}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 908
- Observed pair range: 1..2030
- Successful sends per input receive-time second: 10.723

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 903 | 146.014 | 138.300 | 194.560 | 216.310 | 639.900 |
| edge.detect_ms.cam1 | 903 | 44.154 | 43.300 | 46.500 | 50.080 | 102.200 |
| edge.detect_ms.cam2 | 903 | 43.635 | 43.100 | 45.600 | 47.890 | 64.600 |
| edge.detect_ms.total | 903 | 87.789 | 86.400 | 91.900 | 97.680 | 151.400 |
| edge.pose_ms.cam1 | 903 | 22.195 | 21.800 | 23.800 | 24.600 | 58.100 |
| edge.pose_ms.cam2 | 903 | 22.118 | 21.800 | 23.500 | 24.300 | 32.700 |
| edge.pose_ms.total | 903 | 44.312 | 43.800 | 46.600 | 48.690 | 83.100 |
| edge.queue_ms | 903 | 10.439 | 0.100 | 25.680 | 45.070 | 567.100 |
| edge.rtt_ms | 903 | 57.275 | 43.400 | 107.280 | 123.090 | 652.800 |
| edge.wait_ms | 903 | 58.176 | 50.700 | 104.240 | 128.230 | 537.600 |
| edge.yolo_ms.cam1 | 903 | 21.929 | 21.300 | 23.400 | 25.100 | 49.800 |
| edge.yolo_ms.cam2 | 903 | 21.488 | 21.200 | 22.800 | 23.800 | 40.400 |
| edge.yolo_ms.total | 903 | 43.417 | 42.500 | 45.580 | 49.000 | 76.800 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s2-t1-v6

Folder: classroom-1014-s2-t1-v6
Session/profile: ('classroom-1014-s2-t1-v6', 'basic')

- Timing rows: 122; successful send records: 122; responses: 122
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 122}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 122
- Observed pair range: 1..333
- Successful sends per input receive-time second: 10.861

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 117 | 142.404 | 139.600 | 181.500 | 198.980 | 256.500 |
| edge.detect_ms.cam1 | 117 | 45.783 | 43.400 | 51.840 | 57.200 | 93.000 |
| edge.detect_ms.cam2 | 117 | 45.472 | 43.400 | 51.860 | 58.680 | 85.500 |
| edge.detect_ms.total | 117 | 91.255 | 87.200 | 104.580 | 112.100 | 178.500 |
| edge.pose_ms.cam1 | 117 | 23.391 | 22.200 | 26.960 | 30.640 | 55.600 |
| edge.pose_ms.cam2 | 117 | 23.033 | 21.900 | 26.080 | 29.300 | 41.900 |
| edge.pose_ms.total | 117 | 46.425 | 44.200 | 54.860 | 59.260 | 97.500 |
| edge.queue_ms | 117 | 3.170 | 0.100 | 15.380 | 25.680 | 36.800 |
| edge.rtt_ms | 117 | 49.360 | 35.400 | 101.240 | 110.300 | 149.300 |
| edge.wait_ms | 117 | 51.121 | 48.700 | 87.340 | 100.160 | 146.200 |
| edge.yolo_ms.cam1 | 117 | 22.370 | 21.300 | 26.000 | 27.140 | 38.900 |
| edge.yolo_ms.cam2 | 117 | 22.404 | 21.300 | 25.700 | 29.460 | 43.500 |
| edge.yolo_ms.total | 117 | 44.774 | 42.600 | 51.220 | 54.520 | 80.800 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s3-t1-v6

Folder: classroom-1014-s3-t1-v6
Session/profile: ('classroom-1014-s3-t1-v6', 'basic')

- Timing rows: 136; successful send records: 136; responses: 136
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 136}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 136
- Observed pair range: 1..379
- Successful sends per input receive-time second: 10.406

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 131 | 151.631 | 143.700 | 212.600 | 228.350 | 300.700 |
| edge.detect_ms.cam1 | 131 | 46.234 | 44.300 | 51.300 | 59.900 | 106.100 |
| edge.detect_ms.cam2 | 131 | 45.753 | 44.000 | 48.000 | 54.350 | 120.900 |
| edge.detect_ms.total | 131 | 91.986 | 88.700 | 99.000 | 110.050 | 185.000 |
| edge.pose_ms.cam1 | 131 | 23.582 | 22.400 | 25.200 | 32.850 | 42.600 |
| edge.pose_ms.cam2 | 131 | 23.038 | 22.400 | 24.900 | 27.950 | 46.400 |
| edge.pose_ms.total | 131 | 46.621 | 45.000 | 51.000 | 59.350 | 86.000 |
| edge.queue_ms | 131 | 2.864 | 0.100 | 6.000 | 25.750 | 49.200 |
| edge.rtt_ms | 131 | 48.698 | 35.600 | 96.100 | 114.050 | 138.200 |
| edge.wait_ms | 131 | 59.606 | 54.100 | 115.500 | 128.850 | 182.600 |
| edge.yolo_ms.cam1 | 131 | 22.621 | 21.600 | 25.300 | 27.750 | 65.200 |
| edge.yolo_ms.cam2 | 131 | 22.692 | 21.500 | 23.900 | 26.400 | 94.600 |
| edge.yolo_ms.total | 131 | 45.314 | 43.400 | 50.000 | 52.100 | 116.000 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s4-t1-v6

Folder: classroom-1014-s4-t1-v6
Session/profile: ('classroom-1014-s4-t1-v6', 'basic')

- Timing rows: 165; successful send records: 165; responses: 165
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 165}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 165
- Observed pair range: 1..407
- Successful sends per input receive-time second: 9.762

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 160 | 155.719 | 144.850 | 206.590 | 242.340 | 325.300 |
| edge.detect_ms.cam1 | 160 | 46.058 | 44.300 | 50.720 | 56.935 | 71.600 |
| edge.detect_ms.cam2 | 160 | 45.333 | 44.350 | 49.710 | 51.725 | 85.400 |
| edge.detect_ms.total | 160 | 91.391 | 89.250 | 100.240 | 109.810 | 129.800 |
| edge.pose_ms.cam1 | 160 | 23.103 | 22.400 | 25.510 | 26.900 | 44.800 |
| edge.pose_ms.cam2 | 160 | 23.083 | 22.500 | 25.530 | 26.530 | 41.600 |
| edge.pose_ms.total | 160 | 46.186 | 45.000 | 50.910 | 52.105 | 71.900 |
| edge.queue_ms | 160 | 2.445 | 0.100 | 7.210 | 22.580 | 38.100 |
| edge.rtt_ms | 160 | 50.125 | 36.500 | 99.920 | 113.785 | 126.100 |
| edge.wait_ms | 160 | 64.272 | 54.700 | 116.590 | 140.870 | 235.600 |
| edge.yolo_ms.cam1 | 160 | 22.922 | 21.900 | 25.820 | 29.910 | 47.100 |
| edge.yolo_ms.cam2 | 160 | 22.228 | 21.700 | 24.300 | 25.155 | 43.800 |
| edge.yolo_ms.total | 160 | 45.150 | 43.750 | 50.600 | 56.070 | 71.300 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s4-t2-v6

Folder: classroom-1014-s4-t2-v6
Session/profile: ('classroom-1014-s4-t2-v6', 'basic')

- Timing rows: 110; successful send records: 110; responses: 110
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 110}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 110
- Observed pair range: 1..346
- Successful sends per input receive-time second: 9.968

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 105 | 154.810 | 146.400 | 194.700 | 220.080 | 428.100 |
| edge.detect_ms.cam1 | 105 | 47.544 | 44.300 | 50.780 | 56.140 | 213.000 |
| edge.detect_ms.cam2 | 105 | 49.555 | 44.400 | 50.200 | 57.860 | 262.000 |
| edge.detect_ms.total | 105 | 97.099 | 88.700 | 97.700 | 123.340 | 321.900 |
| edge.pose_ms.cam1 | 105 | 24.321 | 22.600 | 26.180 | 30.520 | 126.200 |
| edge.pose_ms.cam2 | 105 | 23.773 | 22.300 | 25.220 | 28.860 | 70.400 |
| edge.pose_ms.total | 105 | 48.094 | 45.100 | 51.080 | 55.160 | 155.600 |
| edge.queue_ms | 105 | 2.768 | 0.100 | 2.620 | 24.500 | 43.000 |
| edge.rtt_ms | 105 | 48.567 | 35.100 | 97.600 | 113.160 | 129.000 |
| edge.wait_ms | 105 | 57.664 | 53.100 | 100.620 | 109.480 | 158.800 |
| edge.yolo_ms.cam1 | 105 | 23.198 | 21.600 | 24.380 | 25.720 | 86.800 |
| edge.yolo_ms.cam2 | 105 | 25.761 | 21.600 | 24.320 | 33.560 | 191.600 |
| edge.yolo_ms.total | 105 | 48.959 | 43.500 | 48.560 | 68.040 | 217.000 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s5-t1-v6

Folder: classroom-1014-s5-t1-v6
Session/profile: ('classroom-1014-s5-t1-v6', 'basic')

- Timing rows: 129; successful send records: 129; responses: 129
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 129}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 129
- Observed pair range: 1..379
- Successful sends per input receive-time second: 10.745

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 124 | 143.948 | 139.700 | 191.270 | 212.100 | 329.500 |
| edge.detect_ms.cam1 | 124 | 45.720 | 43.150 | 47.440 | 50.665 | 128.800 |
| edge.detect_ms.cam2 | 124 | 46.237 | 43.400 | 46.400 | 51.580 | 190.100 |
| edge.detect_ms.total | 124 | 91.957 | 86.350 | 96.070 | 118.675 | 239.100 |
| edge.pose_ms.cam1 | 124 | 22.674 | 21.850 | 24.040 | 26.665 | 44.000 |
| edge.pose_ms.cam2 | 124 | 23.658 | 21.850 | 24.070 | 27.070 | 136.700 |
| edge.pose_ms.total | 124 | 46.332 | 43.750 | 49.040 | 57.975 | 158.600 |
| edge.queue_ms | 124 | 3.635 | 0.100 | 16.380 | 29.125 | 51.800 |
| edge.rtt_ms | 124 | 52.135 | 38.450 | 109.820 | 124.040 | 156.100 |
| edge.wait_ms | 124 | 51.944 | 50.500 | 94.300 | 109.755 | 160.000 |
| edge.yolo_ms.cam1 | 124 | 23.015 | 21.150 | 23.540 | 25.920 | 91.300 |
| edge.yolo_ms.cam2 | 124 | 22.552 | 21.100 | 23.540 | 24.055 | 143.400 |
| edge.yolo_ms.total | 124 | 45.568 | 42.350 | 46.620 | 51.780 | 165.500 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s5-t2-v6

Folder: classroom-1014-s5-t2-v6
Session/profile: ('classroom-1014-s5-t2-v6', 'basic')

- Timing rows: 162; successful send records: 162; responses: 162
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 162}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 162
- Observed pair range: 1..412
- Successful sends per input receive-time second: 10.468

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 157 | 152.290 | 139.000 | 203.020 | 235.080 | 604.400 |
| edge.detect_ms.cam1 | 157 | 44.997 | 43.000 | 47.920 | 51.040 | 114.100 |
| edge.detect_ms.cam2 | 157 | 44.094 | 42.900 | 47.300 | 51.320 | 85.700 |
| edge.detect_ms.total | 157 | 89.091 | 85.900 | 96.660 | 102.180 | 160.700 |
| edge.pose_ms.cam1 | 157 | 22.297 | 21.700 | 24.040 | 25.700 | 32.700 |
| edge.pose_ms.cam2 | 157 | 22.558 | 21.700 | 24.120 | 25.900 | 58.900 |
| edge.pose_ms.total | 157 | 44.855 | 43.700 | 48.300 | 51.640 | 81.400 |
| edge.queue_ms | 157 | 2.746 | 0.100 | 8.620 | 22.600 | 45.900 |
| edge.rtt_ms | 157 | 50.522 | 37.200 | 99.880 | 110.040 | 130.900 |
| edge.wait_ms | 157 | 63.161 | 52.000 | 108.620 | 145.680 | 472.500 |
| edge.yolo_ms.cam1 | 157 | 22.675 | 21.200 | 24.080 | 26.900 | 85.100 |
| edge.yolo_ms.cam2 | 157 | 21.504 | 21.000 | 23.500 | 24.280 | 33.000 |
| edge.yolo_ms.total | 157 | 44.179 | 42.200 | 47.840 | 50.920 | 108.100 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s6-t1-v6

Folder: classroom-1014-s6-t1-v6
Session/profile: ('classroom-1014-s6-t1-v6', 'basic')

- Timing rows: 50; successful send records: 50; responses: 50
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 50}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 50
- Observed pair range: 1..167
- Successful sends per input receive-time second: 11.699

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 45 | 142.069 | 139.500 | 177.120 | 199.960 | 256.300 |
| edge.detect_ms.cam1 | 45 | 41.482 | 41.200 | 42.900 | 43.180 | 46.300 |
| edge.detect_ms.cam2 | 45 | 41.640 | 41.500 | 42.960 | 43.580 | 44.500 |
| edge.detect_ms.total | 45 | 83.122 | 82.700 | 84.800 | 86.840 | 90.000 |
| edge.pose_ms.cam1 | 45 | 21.124 | 21.000 | 22.060 | 22.500 | 24.500 |
| edge.pose_ms.cam2 | 45 | 21.002 | 21.000 | 21.500 | 22.000 | 22.700 |
| edge.pose_ms.total | 45 | 42.127 | 42.000 | 43.120 | 44.100 | 45.900 |
| edge.queue_ms | 45 | 5.560 | 0.100 | 22.620 | 40.480 | 47.800 |
| edge.rtt_ms | 45 | 53.873 | 38.000 | 105.220 | 122.300 | 130.800 |
| edge.wait_ms | 45 | 58.896 | 55.400 | 93.180 | 117.240 | 167.500 |
| edge.yolo_ms.cam1 | 45 | 20.336 | 20.300 | 21.220 | 21.500 | 22.400 |
| edge.yolo_ms.cam2 | 45 | 20.607 | 20.500 | 21.800 | 21.880 | 22.200 |
| edge.yolo_ms.total | 45 | 40.942 | 40.700 | 42.360 | 43.060 | 44.200 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s7-t1-v6

Folder: classroom-1014-s7-t1-v6
Session/profile: ('classroom-1014-s7-t1-v6', 'basic')

- Timing rows: 126; successful send records: 126; responses: 126
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 126}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 126
- Observed pair range: 1..312
- Successful sends per input receive-time second: 9.988

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 121 | 156.564 | 145.200 | 212.500 | 251.800 | 330.500 |
| edge.detect_ms.cam1 | 121 | 45.090 | 43.900 | 48.500 | 50.500 | 81.000 |
| edge.detect_ms.cam2 | 121 | 44.293 | 43.300 | 46.900 | 50.800 | 103.900 |
| edge.detect_ms.total | 121 | 89.383 | 86.800 | 95.100 | 101.200 | 183.800 |
| edge.pose_ms.cam1 | 121 | 22.796 | 22.300 | 24.800 | 25.600 | 49.400 |
| edge.pose_ms.cam2 | 121 | 22.452 | 22.200 | 24.300 | 25.700 | 33.700 |
| edge.pose_ms.total | 121 | 45.248 | 44.200 | 48.500 | 51.900 | 83.100 |
| edge.queue_ms | 121 | 4.508 | 0.100 | 20.800 | 33.200 | 56.900 |
| edge.rtt_ms | 121 | 50.878 | 35.400 | 106.700 | 119.600 | 146.800 |
| edge.wait_ms | 121 | 67.152 | 57.800 | 123.200 | 159.700 | 216.400 |
| edge.yolo_ms.cam1 | 121 | 22.278 | 21.400 | 23.900 | 25.800 | 49.200 |
| edge.yolo_ms.cam2 | 121 | 21.826 | 21.200 | 22.900 | 24.100 | 70.200 |
| edge.yolo_ms.total | 121 | 44.103 | 42.600 | 46.800 | 48.800 | 100.700 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s7-t2-v6

Folder: classroom-1014-s7-t2-v6
Session/profile: ('classroom-1014-s7-t2-v6', 'basic')

- Timing rows: 94; successful send records: 94; responses: 94
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 94}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 94
- Observed pair range: 1..267
- Successful sends per input receive-time second: 10.179

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 89 | 147.428 | 135.000 | 202.420 | 222.780 | 402.500 |
| edge.detect_ms.cam1 | 89 | 47.990 | 42.700 | 53.400 | 62.500 | 319.700 |
| edge.detect_ms.cam2 | 89 | 45.269 | 42.400 | 48.640 | 53.020 | 159.300 |
| edge.detect_ms.total | 89 | 93.258 | 85.100 | 105.300 | 118.440 | 366.600 |
| edge.pose_ms.cam1 | 89 | 22.907 | 21.600 | 25.500 | 28.060 | 66.600 |
| edge.pose_ms.cam2 | 89 | 23.663 | 21.600 | 24.740 | 28.380 | 126.100 |
| edge.pose_ms.total | 89 | 46.570 | 43.200 | 50.660 | 57.700 | 158.900 |
| edge.queue_ms | 89 | 3.227 | 0.100 | 12.180 | 19.820 | 54.200 |
| edge.rtt_ms | 89 | 48.183 | 34.200 | 94.760 | 99.620 | 136.800 |
| edge.wait_ms | 89 | 54.139 | 47.000 | 106.200 | 118.940 | 244.000 |
| edge.yolo_ms.cam1 | 89 | 25.064 | 21.100 | 25.160 | 36.660 | 253.100 |
| edge.yolo_ms.cam2 | 89 | 21.581 | 20.600 | 24.460 | 26.020 | 41.300 |
| edge.yolo_ms.total | 89 | 46.645 | 41.700 | 52.800 | 62.280 | 277.500 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s8-t1-v6

Folder: classroom-1014-s8-t1-v6
Session/profile: ('classroom-1014-s8-t1-v6', 'basic')

- Timing rows: 171; successful send records: 171; responses: 171
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 171}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 171
- Observed pair range: 1..405
- Successful sends per input receive-time second: 11.161

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 166 | 146.787 | 136.950 | 206.950 | 224.600 | 287.800 |
| edge.detect_ms.cam1 | 166 | 43.235 | 42.150 | 47.700 | 50.075 | 66.900 |
| edge.detect_ms.cam2 | 166 | 43.151 | 41.900 | 46.600 | 49.775 | 102.200 |
| edge.detect_ms.total | 166 | 86.386 | 83.900 | 94.700 | 98.300 | 152.200 |
| edge.pose_ms.cam1 | 166 | 21.946 | 21.500 | 23.950 | 25.350 | 29.400 |
| edge.pose_ms.cam2 | 166 | 22.046 | 21.400 | 23.400 | 25.375 | 73.500 |
| edge.pose_ms.total | 166 | 43.992 | 42.800 | 47.650 | 49.650 | 100.300 |
| edge.queue_ms | 166 | 4.160 | 0.100 | 16.200 | 25.875 | 68.400 |
| edge.rtt_ms | 166 | 47.862 | 34.150 | 99.750 | 117.025 | 149.300 |
| edge.wait_ms | 166 | 60.370 | 52.650 | 111.100 | 131.600 | 190.700 |
| edge.yolo_ms.cam1 | 166 | 21.261 | 20.600 | 23.250 | 25.300 | 40.500 |
| edge.yolo_ms.cam2 | 166 | 21.082 | 20.700 | 22.950 | 24.100 | 28.700 |
| edge.yolo_ms.total | 166 | 42.343 | 41.250 | 46.250 | 48.900 | 64.500 |

Server stage timings: unavailable (expected before profiling deployment).

## classroom-1014-s9-t1-v6

Folder: classroom-1014-s9-t1-v6
Session/profile: ('classroom-1014-s9-t1-v6', 'basic')

- Timing rows: 232; successful send records: 232; responses: 232
- Detection failures: 0; by status: {}
- Timing status counts (all rows): {'201': 232}
- Warmup pairs excluded from latency statistics: 5 (requested 5)
- Successful sends without saved response: 0
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 232
- Observed pair range: 1..570
- Successful sends per input receive-time second: 10.937

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| edge.age_ms | 227 | 146.870 | 137.000 | 188.600 | 211.040 | 459.100 |
| edge.detect_ms.cam1 | 227 | 43.744 | 42.500 | 46.880 | 50.810 | 77.800 |
| edge.detect_ms.cam2 | 227 | 44.091 | 42.400 | 45.840 | 49.690 | 108.800 |
| edge.detect_ms.total | 227 | 87.836 | 84.900 | 93.200 | 103.830 | 150.400 |
| edge.pose_ms.cam1 | 227 | 22.086 | 21.600 | 23.800 | 24.840 | 39.000 |
| edge.pose_ms.cam2 | 227 | 22.239 | 21.600 | 23.120 | 24.740 | 66.100 |
| edge.pose_ms.total | 227 | 44.325 | 43.100 | 46.540 | 49.980 | 87.200 |
| edge.queue_ms | 227 | 4.722 | 0.100 | 17.620 | 30.970 | 69.700 |
| edge.rtt_ms | 227 | 51.903 | 38.400 | 103.380 | 115.100 | 155.300 |
| edge.wait_ms | 227 | 58.996 | 50.800 | 100.460 | 120.090 | 339.000 |
| edge.yolo_ms.cam1 | 227 | 21.637 | 20.800 | 23.300 | 25.210 | 46.600 |
| edge.yolo_ms.cam2 | 227 | 21.822 | 20.800 | 22.840 | 23.900 | 70.000 |
| edge.yolo_ms.total | 227 | 43.459 | 41.700 | 46.640 | 53.470 | 90.800 |

Server stage timings: unavailable (expected before profiling deployment).
