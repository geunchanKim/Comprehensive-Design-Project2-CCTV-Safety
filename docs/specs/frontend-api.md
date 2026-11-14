# 프론트엔드 백엔드 API 요청

## 현재 구현과 후속 요청 (11/14 통합)

아래 본문에는 초기 요청과 후속 제안이 포함되어 있다. 현재 구현 계약은 [2주 차 API](week2-dashboard.md)와 [경고 계약](dashboard-stream.md#1110-경고-영속화확인-74)을 우선한다.

- snapshot GET·SSE, 별도 cameras 조회, 구역 전체 교체, 영속 alerts 조회·ack를 구현했다. 프론트 HTTP adapter가 연결되었으며 실제 서버 화면 종단 검증은 남아 있다.
- snapshot/cameras/alerts 및 ack는 동일한 `session_id`, `calibration_profile`, `algorithm` 세 조건을 함께 전달한다. 모두 생략하면 서버 운영 조건을 사용하며 미설정 시 503이다. polling은 500ms이며 snapshot 204 중에도 cameras와 alerts를 별도로 조회한다.
- 카메라 실제 응답은 `world`, `horizontal_fov_deg`, `last_frame.server_observed_at_ms`다. 아래 `position`, `fov_deg`, `last_frame_at_ms` 예시는 초기 요청 형식이다. `online=null`은 heartbeat 기록이 없어 상태 미확인이다.
- `/dashboard/areas` 및 `area_id`별 필터는 아직 구현하지 않았다. 프론트는 조건 하나를 기본 구역 A로 표시한다. 아래 다중 구역 목록·필터는 후속 요청이다.
- warning→danger 승격은 같은 alert_id를 유지하면서 재확인을 요구한다. ack 204 뒤 `/alerts`를 재조회하며 종료된 미확인 danger도 확인할 때까지 유지한다.
- 위험구역·안전조끼 경고 및 클래스 쌍별 판정 설정은 후속이다. 현재 영속 경고는 근접 판정 대상이며 운영 `ENABLE_RISK_ANALYSIS=false`를 유지한다.
- 충돌 거리는 객체 중심점 간 거리다. 경고음 반복과 브라우저 오디오 활성화는 화면에서 처리한다.

프론트엔드 대시보드에서 필요한 백엔드 API를 정리한다.
snapshot 데이터 형식은 [dashboard-stream.md](dashboard-stream.md)의 계약을 따른다.

## 1. 최신 대시보드 데이터

### `GET /dashboard/snapshot`

현재 운영 중인 조건의 최신 snapshot을 반환한다.

Query:

```text
area_id
```

- `area_id`는 특정 구역 화면에서 조회할 때 지정한다.
- 조건 선택은 프론트에서 하지 않고, 서버의 현재 운영 조건을 사용한다.
- 조건에 해당하는 snapshot이 없으면 `204 No Content`를 반환한다.
- 운영 조건이 설정되지 않았으면 `503`을 반환한다.

응답에는 기존 `DashboardSnapshot` 필드와 함께 아래 데이터가 필요하다.

- `stream_id`, `seq`
- `map`, `stale_after_ms`
- `objects`
- `risks`, `zones`
- `collision_evaluated`, `zone_evaluated`, `vest_evaluated`
- `captured_at_ms`, `emitted_at_ms`
`seq`는 같은 `stream_id` 안에서 증가해야 한다. 프론트엔드는 이전에 적용한
`seq` 이하의 응답을 새 데이터로 처리하지 않는다.

### `GET /dashboard/stream` (후속)

최신 snapshot을 SSE로 전달한다. 조건은 GET API와 동일하게 서버의 현재 운영
조건을 사용한다.

- GET snapshot과 동일한 query와 응답 데이터를 사용한다.
- `data`는 snapshot JSON이며 event 이름은 `snapshot`으로 한다.
- 재접속하면 현재 snapshot부터 전달한다.
- heartbeat는 snapshot 갱신으로 처리하지 않는다.

## 2. 카메라 정보

### `GET /dashboard/cameras`

snapshot과 같은 운영 조건의 카메라 정보를 반환한다. `area_id`를 지정하면
해당 구역의 카메라만 반환한다.

```json
{
  "camera_id": "cam1",
  "position": {"x": 2.9, "y": 1.9},
  "yaw_deg": 45,
  "fov_deg": 70,
  "online": true,
  "last_frame_at_ms": 1793577600080
}
```

- 위치와 방향은 `map`과 같은 좌표계다.
- `online`은 객체 검출 여부가 아니라 카메라 프레임 수신 상태다.
- `online: null`은 상태 미확인을 의미한다.
- 카메라가 끊기면 해당 구역을 `offline`으로 표시할 수 있어야 한다.

## 3. 전체 활성 경고

### `GET /alerts`

snapshot과 같은 운영 조건의 모든 구역 현재 활성 경고를 반환한다.
전체 화면의 위험 팝업은 이 API의 응답을 사용한다.

- `danger` 경고는 확인 전까지 반환한다.
- 응답의 각 항목은 snapshot의 `alerts`와 같은 형식을 사용한다.
- snapshot·cameras와 같은 운영 조건으로 500ms polling할 수 있어야 한다.
- `session_id`, `calibration_profile`, `algorithm`을 사용하는 경우 세 값을 모두
  같은 query로 전달한다.

## 4. 경고 확인

### `POST /alerts/{alert_id}/ack`

위험 팝업의 확인 결과를 저장한다.

Request:

```json
{"action": "radio"}
```

`action`은 `radio`, `dispatch`, `false-positive`, `null` 중 하나다.

Response:

- 성공: `204 No Content`
- 존재하지 않는 경고: `404`
- 이미 확인한 경고: 멱등하게 `204`

경고에는 다음 필드가 필요하다.

- `alert_id`
- `started_at_ms`
- `acknowledged`
- `action`

같은 위험이 지속되는 동안 `alert_id`를 유지한다.
`warning`에서 `danger`로 바뀌어도 ID를 바꾸지 않는다.
확인하지 않은 `danger`는 위험이 끝난 뒤에도 계속 조회되어야 한다.

경고 식별 기준:

- 충돌: 객체 ID 쌍
- 위험구역: `object_id + zone_id`
- 안전조끼: `object_id`

## 5. 구역 목록

### `GET /dashboard/areas`

사이드바와 전체 현황에 사용할 구역 목록을 반환한다.

구역별 필드:

```json
{
  "area_id": "A",
  "name": "작업장 1",
  "status": "danger",
  "people": 3,
  "cameras": {"online": 2, "total": 2},
  "updated_at_ms": 1793577600100
}
```

- `status`: `ok | warning | danger | offline`
- 인원 수를 알 수 없으면 `people: null`
- 여러 구역을 한 번에 반환한다.
