# 엣지 heartbeat 계약 (엣지 쪽)

2026-11-07 정리 · 서버 구현 `feat/server-week2-dashboard` `31eb71b` (push 전) · 관련 이슈 #71

탐지 결과와 별개로 엣지가 카메라 상태를 서버에 알린다. 2주 차에 전송 큐 최신성 정책(오래된 짝 버리기)을 넣으면 카메라가 정상이어도 탐지 결과가 끊길 수 있다. heartbeat로 카메라 연결 상태와 탐지 전송 상태를 구분한다.

## 보내는 방식

- 카메라마다 1초에 한 번 `POST /edge/heartbeat`. 서버 응답은 204.
- 탐지 전송 큐와 분리한 송신 스레드로 보낸다. 큐가 밀리거나 짝을 버려도 heartbeat는 늦어지지 않는다.
- 카메라마다 요청을 하나씩 순서대로 보낸다. 같은 session/camera에는 송신자를 하나만 둔다.
- 엣지를 다시 실행할 때는 이전 실행을 끝낸 뒤 새 `edge_run_id`로 시작한다.

## 필드

| 필드 | 값 | 설명 |
| --- | --- | --- |
| `session_id` | 문자열 | 탐지 메시지와 같은 값 |
| `camera_id` | 문자열 | 탐지 메시지와 같은 값 |
| `edge_run_id` | UUID | 엣지 실행마다 새로 만든다 |
| `source` | `"rtsp"` / `"folder"` | 실시간 카메라와 녹화 재생 구분 |
| `last_recv_ms` | 정수 또는 `null` | 엣지가 이 카메라 프레임을 마지막으로 받은 시각. 첫 프레임 전에는 `null` |
| `sent_at_ms` | 정수 | heartbeat를 보낸 시각 |
| `dropped_count` | 정수 | 최신성 정책으로 버린 짝 수 (실행 시작부터 누적) |
| `max_queue_age_ms` | 정수 | 직전 heartbeat 이후 전송 큐에서 가장 오래 기다린 시간 |

## 시각 규칙

- `last_recv_ms`와 `sent_at_ms`는 같은 엣지 시계로 만든다.
- 시스템 시계는 자동 보정으로 뒤로 갈 수 있다. 같은 실행 안에서 `sent_at_ms`가 뒤로 가면 서버가 무시해 `online=false`가 될 수 있다.
- 그래서 실행 시작 시 시각을 한 번 잡고, 그 뒤로는 monotonic 경과 시간을 더해 두 값을 만든다.
- 엣지와 서버의 절대 시각은 비교하지 않는다.

## 서버 판정 (서버 구현 기준)

| 상태 | 기준 |
| --- | --- |
| `online=true` | 서버가 마지막 heartbeat를 받은 지 3000ms 미만 |
| `online=false` | 3000ms 이상 |
| `online=null` | heartbeat 기록 없음 |
| 수신 `recent` | `(sent_at_ms - last_recv_ms)` + 서버 수신 후 경과 < 2000ms |
| 수신 `stale` | 위 값이 2000ms 이상 |
| 수신 `unknown` | 첫 프레임 전 (`last_recv_ms=null`) |

- 3초는 v7 무선 측정의 최대 왕복 지연(약 1.3초)을 기준으로 정했다. 2주 차 유선 재측정 후 다시 본다.
- `folder`의 `online`은 재생 프로세스가 살아 있는지를 뜻한다.
- 공개 배포 전에 인증·소유권 검토가 필요하다.

## 엣지 구현 (feat/edge-week2-freshness)

| 파일 | 내용 |
| --- | --- |
| `ai/edge/clock.py` | 시작 시각 + monotonic 경과 시간으로 만든 epoch ms. 시스템 시계가 뒤로 가도 뒤로 가지 않는다 |
| `ai/edge/heartbeat.py` | 1초마다 카메라를 하나씩 순서대로 보내는 스레드. 실행마다 새 `edge_run_id` |
| `ai/edge/server_client.py` | `post_now()`: 전송 큐를 거치지 않고 별도 HTTP 세션으로 바로 보낸다. 실패해도 실시간 전송을 멈추지 않는다 |
| `ai/edge/realtime.py` | `--send`이면 heartbeat를 함께 켠다. 전송을 모두 끝낸 뒤 멈춘다. `meta.json`에 `edge_run_id`와 보낸·실패 수를 남긴다 |

- `last_recv_ms`는 메인 루프가 카메라 큐에서 프레임을 꺼낸 순간의 `clock.now_ms()`다. 기존 탐지 메시지의 `recv_ms`(시스템 시계)와는 다른 값이다.
- `source`: 웹캠·RTSP는 `"rtsp"`, 녹화 폴더·영상 파일은 `"folder"`.
- 전송 큐는 두 카메라가 함께 쓰므로 `max_queue_age_ms`는 한 바퀴에 한 번 꺼내 두 카메라에 같은 값을 넣는다.
- 서버에 `/edge/heartbeat`가 아직 없으면 `--no-heartbeat`로 끈다. 켜 두면 매초 404를 세기만 하고 탐지 전송은 계속한다.
- dry-run이면 `runs/edge/<session_id>/sent_edge_heartbeat.jsonl`에 저장한다.

## 남은 확인

- 녹화 재생으로 `dropped_count`·`max_queue_age_ms` 값 확인 (`--max-age-ms` 600·800 비교)
- 서버 push 후 실제 송신으로 `online`·`receive_status` 연동 확인
