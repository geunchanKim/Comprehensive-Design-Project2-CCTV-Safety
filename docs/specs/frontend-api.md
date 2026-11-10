# 관제 화면(frontend)이 서버에 필요한 것

2026-11-05 BE 후속: [2주 차 API](week2-dashboard.md)에 snapshot GET·SSE, 별도 cameras 조회, 구역 전체 교체를 구현했다. polling 합의는 아래 초기 제안의 1초에서 **500ms**로 갱신됐으며 AreaPage에 반영했다. cameras의 `online`은 heartbeat 합의 전 null이고 `frame_status`를 별도로 제공한다. FE는 현재 mock이며 adapter 연동이 남아 있다. 영속 alert/ack와 판정 대상 설정은 이번 구현에 포함되지 않는다.

관제 화면은 서버의 [대시보드 snapshot 계약](dashboard-stream.md)(`backend/dashboard.py`의 `DashboardSnapshot`, `feat/server-week1-observability` 기준)을 그대로 입력으로 쓴다. 이 문서는 그 계약 위에 **화면 때문에 더 필요한 것**만 적는다. 계약에 이미 있는 것은 다시 정의하지 않는다.

지금 프론트엔드는 mock 데이터(`frontend/src/api/mock/`)로 돌아가고, 서버가 준비되면 `frontend/src/api/source.ts`의 데이터 소스만 바꾼다.

## 1. 계약을 그대로 쓰는 부분 (서버 추가 작업 없음)

| 화면 요소 | snapshot에서 가져오는 것 |
| --- | --- |
| 평면도 범위·좌표 | `map.bounds`, `coordinate_frame_id`. 화면이 bounds를 평면도 크기로 변환한다 |
| 객체 위치·속도 | `objects[].world`의 x·y, `velocity` |
| 이동 궤적 | 서버에 요청하지 않는다. 화면이 최근 snapshot들의 위치를 쌓아 그린다 |
| 한 카메라만 본 객체 | `camera_tracks` 항목이 1개이면 점선 테두리로 구분 |
| 사람↔객체 충돌 | `risks[]`(`object1_id`, `object2_id`, `distance_m`, `ttc_s`, `level`) |
| 위험 구역 | `zones[]`의 `vertices` 다각형, `warning_distance_m`. 상태는 `objects[].zone_states` |
| PPE | `objects[].vest`(안전조끼). 화면 예시도 안전조끼 미착용 기준 |
| 판단 안 함 | `collision_evaluated` / `zone_evaluated` / `vest_evaluated`가 false이거나 상태가 `unknown`이면 "미판단"으로 보여 주고 안전으로 표시하지 않는다 |
| 갱신 지연 | `stale_after_ms` 이상 새 snapshot이 없으면 "갱신 지연", 연결이 끊기면 "연결 끊김" |

## 2. 서버에 요청하는 것

### 2.1 실시간 전달 엔드포인트

계약에는 아직 공개 엔드포인트가 없다. 화면은 WebSocket·SSE 어느 쪽이든 맞출 수 있다. 결정 전까지 쓸 수 있게 **최신 snapshot 한 개를 돌려주는 GET**이 있으면 1초 polling으로 먼저 붙인다.

- 예: `GET /dashboard/snapshot?session_id=&calibration_profile=&algorithm=`
- 관제 화면은 "지금 돌고 있는 조건" 하나만 본다. 조건을 생략하면 서버가 현재 운영 조건을 고르는 방식이면 좋다.

### 2.2 카메라 상태 (`cameras` 필드 추가)

평면도에 카메라 위치·시야를 그리고, 카메라가 끊기면 구역을 "감시 불가"로 표시해야 한다. snapshot에 다음을 추가해 달라.

```json
"cameras": [
  {"camera_id": "cam1", "position": {"x": 2.9, "y": 1.9}, "yaw_deg": 45, "fov_deg": 70,
   "online": true, "last_frame_at_ms": 1793577600080}
]
```

- `position`·`yaw_deg`·`fov_deg`: 캘리브레이션(`rvec`/`tvec`, `K`)에서 구한 바닥 평면 위 카메라 위치·방향·수평 시야. 좌표계는 `map`과 같고, `yaw_deg`는 +X에서 반시계 방향(+Y 쪽이 +90°)이다.
- `online`·`last_frame_at_ms`: 엣지에서 그 카메라 프레임을 마지막으로 받은 시각. 기준 시간 안에 프레임이 없으면 `online=false`.

### 2.3 경고 확인(ack)과 지속 시간

`danger`는 모든 화면 위에 팝업으로 뜨고 담당자가 **확인해야** 닫힌다. 새로고침하거나 다른 PC에서 봐도 같은 상태여야 하므로 확인 상태는 서버에 있어야 한다.

계약의 경고 식별 기준(충돌 = 객체 ID 쌍, 구역 = `object_id + zone_id`, 안전조끼 = `object_id`)을 그대로 쓰고, 각 경고에 다음을 붙여 달라.

| 필드 | 설명 |
| --- | --- |
| `alert_id` | 같은 위험이 이어지는 동안 바뀌지 않는 ID. 안전으로 돌아왔다가 다시 생기면 새 ID |
| `started_at_ms` | 이 경고가 시작된 시각 (화면의 "n초째", 상위 알림 카운트다운) |
| `acknowledged` | 확인 여부 |

- `warning` → `danger`로 올라가도 같은 `alert_id`를 유지한다.
- `POST /alerts/{alert_id}/ack`, body `{"action": "radio" | "dispatch" | "false-positive" | null}`, 응답 204. 확인 시각·조치를 이벤트 기록에 남긴다.
- 위험이 끝났어도 확인 안 된 `danger`는 확인될 때까지 내려 준다.

지금 `risks[]`는 객체 두 개와 거리가 필수라 구역·안전조끼 경고를 담을 수 없다. 세 종류를 한 목록으로 내려 줄지, 종류별 위치(`risks`, `zone_states`, `vest`)에 각각 붙일지는 서버에서 편한 쪽으로 정하면 화면이 맞춘다.

### 2.4 충돌 판정 대상 설정

시안은 **사람↔객체(카트·의자 등)를 기본으로** 판정하고, 사람↔사람은 설정에서 켜는 방식이다. 지금 서버는 아래와 같아서 이 조합을 만들 수 없다.

| `ENABLE_RISK_ANALYSIS` | F(경고 유지) | 판정 대상 |
| --- | --- | --- |
| false | 켜짐 | 사람↔사람만 |
| true | 무관 | 사람↔사람 + 사람↔모든 지원 객체 |
| false | 꺼짐 | 계산 안 함 |

대상 쌍(클래스 조합)별로 켜고 끄는 설정이 필요하다. 3주 차 예정인 종류별 거리 설정·활성화와 같이 진행하면 된다.

## 3. 다음 단계 (화면을 만들 때 다시 정리)

- **여러 구역**: 지금 계약은 조건 하나 = 지도 하나다. 사업장 전체 현황을 그리려면 구역 목록(이름, 사업장 지도 위 위치, 연결된 조건)이 필요하다. 처음에는 서버 설정 파일로 충분하다.
- **이벤트 기록**: 끝난 경고 목록(시작·종료 시각, 최고 단계, 최소 거리, 확인 정보)과 발생 순간 snapshot·카메라 캡처.
- **설정**: 위험 구역 편집, 도면 이미지 업로드(축척·원점), 판정 대상·거리 기준.

## 4. 같이 확인할 것

11/10 BE 로컬 구현: 공통 snapshot `alerts`와 `GET /alerts`, `POST /alerts/{alert_id}/ack`를 추가했다. 카메라는 별도 `GET /dashboard/cameras`다. ack 최신 상태는 `GET /alerts`를 별도로 조회하고 탐지 stale 타이머와 분리한다. 세 조건 쿼리, 상태 전이·오류·중복 확인 규칙은 [경고 계약](dashboard-stream.md#1110-경고-영속화확인-74)을 따른다. 아직 push·배포·FE adapter 연동 완료를 뜻하지 않는다. vest·클래스 쌍별 대상 설정은 후속이다.

- 충돌 거리는 두 객체 중심점 사이 거리라서, 카트처럼 긴 물체는 실제 외곽까지보다 멀게 계산된다. 지금은 그대로 두되 화면에 거리 기준을 "중심점 간"으로 표기한다.
- 경고 유지 여유 0.1m는 지금 사람↔사람에만 적용된다. 사람↔객체에도 같은 여유가 필요하다(팝업이 경계값에서 깜박이지 않게).
- 경고음 반복 규칙과 브라우저 오디오 활성화(첫 클릭)는 화면 쪽에서 처리한다.
