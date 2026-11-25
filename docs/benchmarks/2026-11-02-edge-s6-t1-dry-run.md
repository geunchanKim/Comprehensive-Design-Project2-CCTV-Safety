# Edge and server measurement report

Folder: classroom-1014-s6-t1-v6
Session/profile: ('classroom-1014-s6-t1-v6', 'basic')

- Timing rows: 49; successful send records: 49; responses: 0
- Detection failures: 0; by status: {}
- Successful sends without saved response: 49
- Saved responses without successful-send record: 0
- Pairs present in all three logs: 0
- Observed pair range: 1..167
- Successful sends per input receive-time second: 7.283

This rate uses successful input frame times, not server response completion times.
Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.

| Metric | Samples | Mean ms | p50 ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- | --- |
| edge.age_ms | 49 | 187.100 | 133.900 | 200.200 | 2636.700 |
| edge.detect_ms.cam1 | 49 | 89.157 | 40.500 | 60.920 | 2309.800 |
| edge.detect_ms.cam2 | 49 | 47.096 | 40.700 | 54.880 | 325.500 |
| edge.pose_ms.cam1 | 49 | 25.869 | 20.600 | 36.860 | 225.400 |
| edge.pose_ms.cam2 | 49 | 23.380 | 20.700 | 23.240 | 157.800 |
| edge.wait_ms | 49 | 50.806 | 45.700 | 101.220 | 155.600 |
| edge.yolo_ms.cam1 | 49 | 63.271 | 20.200 | 28.520 | 2084.300 |
| edge.yolo_ms.cam2 | 49 | 23.688 | 19.900 | 24.900 | 167.700 |

rtt_ms: unavailable

Server stage timings: unavailable (expected before profiling deployment).
