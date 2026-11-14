# 대시보드 실시간 메시지 초안

1주 차 서버 결과물. 성윤은 이 형식으로 화면 입력을 준비하고, 근찬은 안전복 결과 형식을 검토한다. 11/3 #72 FE 회신으로 SSE 우선·GET 선연결과 지도 경계 표시안을 합의했다. 현재 공개된 실시간 엔드포인트는 없으며, `backend/dashboard.py`에 검증 스키마와 기존 결과 변환 함수가 있다. 아래 GET 규칙은 2주 차 구현을 위한 BE 계약 결정이며 아직 동작하는 API가 아니다.

## 좌표와 메시지 범위

- 월드 좌표는 m 단위 `[X,Y,Z]`, Z는 높이. 지도에는 X와 Y를 사용한다. Unity `(x,y,z)` → 서버 `(x,z,y)` 변환은 엣지에서 한 번 수행한다.
- 메시지는 한 `session_id / calibration_profile / algorithm`의 완전한 snapshot이다. 다른 조건의 ID·경고를 섞지 않는다. `object_id`는 해당 조건 안에서 식별한다.
- 수신자는 같은 조건·`stream_id`에서 마지막 적용한 `seq`보다 큰 메시지만 적용한다. `seq`는 snapshot 발행 순서이며 입력의 `pair_id`와 별개다. 중복·역순은 무시하고 seq 간격은 누락 진단에 사용한다. 다음 snapshot에 없는 객체·경고는 현재 화면에서 제거한다. 경고 이력 저장은 별도다.
- `stream_id`는 서버의 해당 조건 발행 수명 동안 유지하고, 재접속만으로 바꾸지 않는다. 서버 재시작 등으로 새 스트림이 생기면 구독 시작 snapshot에서 ID와 seq 기준을 초기화한다. 이전 연결의 메시지를 새 연결에 적용하지 않는다. 발행 카운터와 재접속 처리는 2주 차 API에서 구현하며 지금은 계약과 변환 함수만 제공한다.
- 재접속 시 현재 snapshot을 받는 방식과 느린 수신자에게 최신 snapshot만 유지하는 방식은 2주 차 API 구현에서 적용한다.
- 새로 적용할 snapshot이 `stale_after_ms`(기본 1000ms) 이상 없으면 화면을 갱신 지연 상태로 표시한다. 브라우저 단조 시계로 마지막 유효 수신 이후 시간을 재며, 무시한 과거 메시지는 타이머를 갱신하지 않는다. 연결 종료는 즉시 연결 끊김으로 표시한다. 연결 중단·미판단 상태를 안전으로 표시하지 않는다.

## 메시지 필드

| 필드 | 의미 |
| --- | --- |
| `schema_version` / `event` | `1.0` / `snapshot` |
| `stream_id` / `seq` | 발행 스트림 ID / 해당 스트림에서 단조 증가하는 snapshot 순서 |
| `map` | `coordinate_system=world_xy_m`, `coordinate_frame_id`, `bounds={x_min,x_max,y_min,y_max}` |
| `stale_after_ms` | 유효 snapshot이 없을 때 stale 표시 기준, 기본 1000ms |
| `supported_classes` | person, chair, cart, desk, suitcase, backpack. `objects[].cls`도 이 값만 사용 |
| `session_id`, `calibration_profile`, `algorithm`, `pair_id` | 기존 서버 처리 조건 및 프레임 쌍 번호 |
| `captured_at_ms` | 두 입력 프레임 `ts`의 최댓값, epoch ms |
| `emitted_at_ms` | 서버가 메시지를 만든 시각, epoch ms |
| `objects` | 이번 짝에서 위치가 산출된 사람·물체. ID, 클래스, `world`, 속도, 카메라 track ID 포함 |
| `objects[].vest` | `status`: `wearing / not_wearing / unknown`; 신뢰도 0~1 또는 null, 마지막 판별 시각 또는 null |
| `objects[].zone_states` | 활성 구역별 `zone_id`, `outside / warning / intrusion / unknown`, 구역까지 거리 m 또는 null. 사람만 대상 |
| `collision_evaluated` | 이번 조건에서 충돌 판단이 실행되는지. false이면 빈 risks를 안전 판정으로 해석하지 않음 |
| `risks` | 기존 `RiskResult`: 객체 ID 쌍, 거리 m, TTC 초 또는 null, `safe / warning / danger` |
| `zones` | [위험구역 형식](risk-zones.md)의 정의 |
| `zone_evaluated` / `vest_evaluated` | 현재 false. 해당 판단이 붙기 전에는 상태 unknown |

현재 `cdfg`의 `f`는 사람–사람 경고 유지를 포함하므로, `ENABLE_RISK_ANALYSIS=false`여도 사람–사람 경고 계산이 실행될 수 있다. 전체 위험 판단 플래그와 실제 조건별 계산 여부를 구분한다. 사람–사람 거리 기본값은 주의 1.0m, 위험 0.5m를 유지한다.

`build_snapshot`은 호출자가 알고 있는 algorithm과 원본 프레임 시각, 서버 생성 시각, 구역·지도 정의, stream_id와 seq를 받는다. 지도와 구역의 `coordinate_frame_id`가 다르면 거부한다. 안전복·구역 판단을 새로 실행하거나 DB에 저장하지 않는다. 예시: [dashboard-snapshot.example.json](examples/dashboard-snapshot.example.json).

Unity 평가 지도는 `coordinate_frame_id=unity-world-xzy`, X 2.79~7.79m, Y 1.785~6.785m이다. 4m 격자에 0.5m 여유를 둔 범위이며 방 전체의 축소 지도가 아니다. 다른 위치의 물체도 snapshot에서 삭제하지 않고, 표시 범위 밖 처리는 프론트가 결정한다. 실측 마커 원점 좌표는 이 지도와 다른 frame ID·bounds를 사용해야 한다.

## 지연과 경고 표시

카메라–엣지–서버–브라우저 시계가 동기화된 경우 화면 시각에서 `captured_at_ms`를 빼 전체 지연을 구한다. 동기화 여부를 확인하기 전에는 전체 지연을 확정 수치로 보고하지 않는다. 서버 구간 시간은 별도 `timings_ms`로 측정한다.

엣지와 브라우저를 같은 노트북에서 실행하고 `captured_at_ms`가 그 노트북의 프레임 수신 시각에서 나온 경우에는 같은 시계로 비교할 수 있다. 녹화 원본의 과거 시각을 화면 현재 시각과 빼지는 않는다. RTT는 요청 전송부터 응답 수신까지의 시간으로 별도 표기한다.

안전복을 매 프레임 판별하지 않으면 직전 원시 결과를 재전송하되 `observed_at_ms`는 실제 판별 시각 그대로 유지한다. 향후 서버의 연속 프레임 판단에서는 같은 관측 시각의 반복 결과를 새 독립 판별로 중복 집계하지 않는다. 두 카메라 결합·신선도 만료·연속 판별 횟수는 3주 차에 결정한다.

충돌은 객체 ID 쌍, 위험구역은 `object_id + zone_id`, 안전복은 `object_id`로 경고 항목을 식별한다. `unknown`은 미판단 표시를 사용한다. 침입·위험 단계 경고음의 화면 디자인과 반복 규칙은 성윤과 리뷰하며 브라우저 오디오 활성화를 위한 사용자 클릭을 고려한다.

## 주말 리뷰 결정 사항

- SSE 우선, 최신 snapshot GET 선연결로 확정. 접근 권한·구독 조건·실제 재접속 처리는 2주 차 구현에서 검증한다.
- 안전복 상태 이름·신뢰도·마지막 관측 시각, 상태 변경에 필요한 연속 프레임 수.
- 실제 교실 구역 좌표와 주의 거리. 현재 예시를 실제 교실에 그대로 적용하지 않는다.

## 11/4 FE 회신 반영: 전달·지도 규칙

출처는 #72의 11/3 FE 회신이다. 화면의 경고 ack·구역 설정 저장은 REST로 충분하므로 snapshot 스트림에 SSE를 사용한다. GET polling은 FE가 **500ms** 주기로 시작하며 stale 1000ms는 유지한다. polling 주기를 줄여도 입력이 끊기면 stale이 되는 것이 정상이다.

`GET /dashboard/snapshot`의 2주 차 구현 계약은 다음과 같다.

| 상황 | 계약 |
| --- | --- |
| 새 snapshot 생성 | 선택된 session/profile/algorithm의 탐지 결과가 성공 저장될 때 생성·발행. 고정 타이머가 아니므로 주기 보장은 없음 |
| 조회 주기 | FE 500ms로 시작. 같은 stream_id/seq는 생성 시각·seq를 바꾸지 않고 반환 |
| 선택 조건에 snapshot 없음 | 204 No Content, body 없음. FE는 대기/미수신으로 표시하며 기존 화면이 있으면 stale 기준 유지 |
| 조건 생략·운영 조건 미설정 | 503, JSON `{"detail":"dashboard operating condition is not configured"}`. 임의의 최신 실험 조건을 선택하지 않음 |
| 조건 명시 | session_id/calibration_profile/algorithm 세 값을 함께 지정. 부분 지정은 422. 세 값 모두 생략하면 명시적 운영 조건 사용 |
| stream_id 변경 | GET도 SSE와 동일하게 새 스트림으로 seq 기준 초기화. 같은 stream_id이면 seq가 큰 경우만 새 데이터로 적용 |

고정 snapshot 생성 주기(ms)는 없다. 실측 baseline의 약 85ms 탐지 시간은 생성 주기 보장값이 아니다. 새 탐지 없이 GET 요청이나 연결 유지 신호만으로 seq를 올리지 않는다. GET은 한 번에 하나씩 조회하거나 요청 세대 번호로 이전 응답을 무시해 오래된 요청이 늦게 도착해 stream 기준을 되돌리지 않도록 한다.

지도는 기존 bounds/frame ID를 유지한다. 지도 밖 객체는 서버 snapshot에 남기고 FE가 `지도 밖 n`으로 알린다. 경고 목록은 필터링하지 않으며 해당 항목·위험 팝업에 `지도 밖` 배지를 붙인다. 구역/주의 띠는 원래 좌표로 판정하고 그리기만 클리핑하며 잘리는 길이(현재 왼쪽 0.29m)를 표식으로 알린다. 좌표나 주의 거리를 표시 때문에 바꾸지 않는다.

구역 저장 API는 #74의 2주 차 후속으로, ZoneSet 전체 검증에 맞춘 전체 교체 PUT을 우선 검토한다. 아직 경로·검증 오류 코드·동시 수정 정책을 확정하거나 구현하지 않았다. FE의 400 요구와 FastAPI 검증 422 일관성을 해당 API 설계에서 맞춘다.
