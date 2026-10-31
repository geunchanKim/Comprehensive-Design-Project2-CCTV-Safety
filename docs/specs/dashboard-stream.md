# 대시보드 실시간 메시지 초안

1주 차 서버 결과물. 성윤은 이 형식으로 화면 입력을 준비하고, 근찬은 안전복 결과 형식을 검토한다. WebSocket 또는 SSE 선택은 1주 차 리뷰에서 결정한다. 현재 공개된 실시간 엔드포인트는 없으며, `backend/dashboard.py`에 검증 스키마와 기존 결과 변환 함수가 있다.

## 좌표와 메시지 범위

- 월드 좌표는 m 단위 `[X,Y,Z]`, Z는 높이. 지도에는 X와 Y를 사용한다. Unity `(x,y,z)` → 서버 `(x,z,y)` 변환은 엣지에서 한 번 수행한다.
- 메시지는 한 `session_id / calibration_profile / algorithm`의 완전한 snapshot이다. 다른 조건의 ID·경고를 섞지 않는다. `object_id`는 해당 조건 안에서 식별한다.
- 수신자는 같은 조건에서 가장 큰 `pair_id`만 적용하고 늦게 온 과거 메시지는 무시한다. 다음 snapshot에 없는 객체·경고는 현재 화면에서 제거한다. 경고 이력 저장은 별도다.
- 재접속 시 현재 snapshot을 받는 방식과 느린 수신자에게 최신 snapshot만 유지하는 방식은 2주 차 API 구현에서 적용한다.
- 새 메시지가 1초 넘게 없으면 화면을 갱신 지연 상태로 표시한다. 연결 중단·미판단 상태를 안전으로 표시하지 않는다.

## 메시지 필드

| 필드 | 의미 |
| --- | --- |
| `schema_version` / `event` | `1.0` / `snapshot` |
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

`build_snapshot`은 호출자가 알고 있는 algorithm과 원본 프레임 시각, 서버 생성 시각, 구역 정의를 받는다. 안전복·구역 판단을 새로 실행하거나 DB에 저장하지 않는다. 예시: [dashboard-snapshot.example.json](examples/dashboard-snapshot.example.json).

## 지연과 경고 표시

카메라–엣지–서버–브라우저 시계가 동기화된 경우 화면 시각에서 `captured_at_ms`를 빼 전체 지연을 구한다. 동기화 여부를 확인하기 전에는 전체 지연을 확정 수치로 보고하지 않는다. 서버 구간 시간은 별도 `timings_ms`로 측정한다.

충돌은 객체 ID 쌍, 위험구역은 `object_id + zone_id`, 안전복은 `object_id`로 경고 항목을 식별한다. `unknown`은 미판단 표시를 사용한다. 침입·위험 단계 경고음의 화면 디자인과 반복 규칙은 성윤과 리뷰하며 브라우저 오디오 활성화를 위한 사용자 클릭을 고려한다.

## 주말 리뷰 결정 사항

- WebSocket 또는 SSE 선택, 접근 권한과 구독 조건, 재접속 동작.
- 안전복 상태 이름·신뢰도·마지막 관측 시각, 상태 변경에 필요한 연속 프레임 수.
- 실제 교실 구역 좌표와 주의 거리. 현재 예시를 실제 교실에 그대로 적용하지 않는다.
