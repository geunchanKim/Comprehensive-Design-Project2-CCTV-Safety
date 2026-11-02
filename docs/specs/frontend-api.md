# 관제 화면(frontend)용 API 명세

관제 화면이 백엔드에서 읽어 가는 API다. 지금 프론트엔드는 이 명세와 같은 모양의 mock 데이터(`frontend/src/api/mock/`)로 돌아가고, 아래 API가 생기면 `frontend/src/api/source.ts`의 데이터 소스만 HTTP로 바꾼다. 화면 쪽 타입 정의는 `frontend/src/api/types.ts`이고, 응답 JSON은 백엔드 관례대로 snake_case로 보내면 프론트에서 camelCase로 바꾼다.

## 1. 기본 개념

```
사업장(site) ─ 구역(area) 여러 개 ─ 구역마다 카메라 2대, 객체, 경고
```

- **구역(area)**: 카메라 한 쌍이 함께 보는 공간. 지금 백엔드의 `session_id` 하나가 구역 하나에 해당한다고 보면 된다. 구역 ↔ 카메라 ↔ 현재 세션의 대응은 서버 설정에 둔다(§5).
- **좌표**: 모두 미터. 구역 평면도의 원점은 **좌상단**, x는 오른쪽, y는 아래쪽이다. 서버의 월드 좌표(바닥 평면)를 구역 원점 기준으로 옮겨서 보낸다.
- **구역 상태**: 그 구역에서 진행 중인 경고 중 가장 심각한 것(`danger` > `warning` > `ok`). 카메라가 하나라도 끊기면 `offline`(감시 불가)이다.
- **시각**: epoch 밀리초(`*_ms`).

### 경고 종류

| `kind` | 의미 | 단계 |
|---|---|---|
| `collision` | 사람 ↔ 객체(카트 등) 충돌 위험 | 거리·TTC 기준 `warning` / `danger` |
| `zone` | 사람의 위험 구역 접근·진입 | 접근 `warning`, 진입 `danger` |
| `ppe` | 안전모·조끼 미착용 | `warning` |
| `system` | 카메라 끊김 등 감시 불가 | `warning` |

`danger`는 화면 전체에 팝업으로 뜨고, 담당자가 **확인(ack)** 해야 닫힌다. 그래서 경고에는 `acknowledged`와 확인 API가 필요하다.

> 현재 백엔드(`backend/api.py`)는 `ENABLE_RISK_ANALYSIS`(기본 `false`)나 경고 유지(F, `warning_hysteresis`)가 켜져 있을 때만 위험을 계산한다. 경고 유지만 켜면 사람 ↔ 사람 쌍만 보고, 사람 ↔ 객체 쌍은 `ENABLE_RISK_ANALYSIS=true`일 때만 본다. 관제 화면이 보여 줄 기본 위험은 사람 ↔ 객체이므로 이 조합을 기본으로 계산해야 한다.

## 2. 우선 필요한 API (구역 관제 화면)

화면은 1초마다 다시 불러온다(polling). 나중에 SSE로 바꾸더라도 응답 모양은 같게 유지한다.

### 2.1 `GET /areas` — 구역 목록·상태

사이드바와 전체 현황 지도에 쓴다. 5초마다 호출한다.

```json
[
  {
    "area_id": "A",
    "name": "작업장 1",
    "rect": {"x": 2, "y": 2, "w": 18, "h": 14},
    "status": "danger",
    "people": 3,
    "cameras": {"online": 2, "total": 2}
  },
  {
    "area_id": "E",
    "name": "검사실",
    "rect": {"x": 42, "y": 20, "w": 16, "h": 14},
    "status": "offline",
    "people": null,
    "cameras": {"online": 1, "total": 2}
  }
]
```

- `rect`: 사업장 전체 지도에서 구역이 놓인 블록 위치(미터).
- `people`: 감시 불가면 `null`.

### 2.2 `GET /areas/{area_id}/snapshot` — 구역의 현재 상태

구역 관제 화면의 평면도와 패널에 들어가는 모든 것이다. 1초마다 호출한다.

```json
{
  "config": {
    "area_id": "A",
    "name": "작업장 1",
    "size": {"w": 9, "h": 7},
    "background": {"kind": "blocks"},
    "zones": [
      {"zone_id": "z1", "kind": "restricted", "label": "위험 구역",
       "rect": {"x": 5.8, "y": 5.6, "w": 2.6, "h": 1.4}}
    ]
  },
  "cameras": [
    {"camera_id": "cam1", "position": {"x": 0.4, "y": 0.4}, "yaw_deg": 45, "fov_deg": 70,
     "online": true, "fps": 30}
  ],
  "classes": [
    {"cls": "person", "label": "사람", "shape": "circle", "protected": true},
    {"cls": "cart", "label": "카트", "shape": "wide"}
  ],
  "objects": [
    {"object_id": 3, "cls": "person", "world": {"x": 3.2, "y": 3.4},
     "velocity": {"x": 0.9, "y": 0.1}, "matching_method": "epipolar",
     "trail": [{"x": 2.1, "y": 3.3}, {"x": 2.6, "y": 3.35}],
     "ppe": {"helmet": true, "vest": true}}
  ],
  "alerts": [ /* 2.3과 같은 모양, 이 구역 것만 */ ],
  "captured_at_ms": 1793500000000
}
```

| 필드 | 설명 |
|---|---|
| `config.background` | 지금은 `{"kind": "blocks"}`. 실제 도면을 쓸 때는 `{"kind": "image", "url": ..., "meters_per_pixel": 0.01, "origin": {"x": 0, "y": 0}}` |
| `cameras[].position`, `yaw_deg`, `fov_deg` | 평면도에 카메라와 시야를 그린다. 캘리브레이션의 `rvec`/`tvec`에서 구할 수 있다. `yaw_deg`는 +x에서 시계 방향 |
| `cameras[].fps` | 끊긴 카메라는 `null` |
| `classes` | 이 구역에서 추적하는 클래스와 그리는 모양(`circle` / `wide` / `square`). `protected`는 보호 대상(사람) |
| `objects[].world` | 칼만 필터 위치. `ObjectMotionState` / `FloorTrack`의 `mean` |
| `objects[].velocity` | 칼만 속도(m/s). 아직 없으면 `null` |
| `objects[].matching_method` | `epipolar` / `ground-plane` / `single-camera`. 한 카메라로만 잡힌 객체는 화면에서 점선 테두리로 구분한다 |
| `objects[].trail` | 최근 위치 몇 개(오래된 것부터). 약 3초 분량이면 충분하다 |
| `objects[].ppe` | PPE 판정을 하는 사람만. 판정이 없으면 필드를 생략 |

### 2.3 `GET /alerts?active=true` — 진행 중인 경고 (전 구역)

어느 화면에 있든 위험 팝업을 띄우기 위해 1초마다 호출한다. 진행 중이거나, 끝났지만 아직 확인되지 않은 `danger`를 돌려준다.

```json
[
  {
    "alert_id": "a-412",
    "area_id": "A",
    "kind": "collision",
    "level": "danger",
    "object1_id": 3,
    "object2_id": 21,
    "distance_m": 0.76,
    "ttc_s": 1.1,
    "contact": {"x": 3.62, "y": 3.25},
    "started_at_ms": 1793499998800,
    "acknowledged": false
  },
  {
    "alert_id": "a-411", "area_id": "A", "kind": "zone", "level": "warning",
    "object1_id": 5, "zone_id": "z1", "distance_m": 0.65, "ttc_s": 1.9,
    "started_at_ms": 1793499996000, "acknowledged": false
  },
  {
    "alert_id": "a-410", "area_id": "A", "kind": "ppe", "level": "warning",
    "object1_id": 9, "message": "안전모 미착용",
    "started_at_ms": 1793499990000, "acknowledged": false
  },
  {
    "alert_id": "e-sys-1", "area_id": "E", "kind": "system", "level": "warning",
    "message": "CAM2 연결 끊김 · 감시 불가",
    "started_at_ms": 1793499900000, "acknowledged": false
  }
]
```

- `alert_id`는 **같은 위험이 이어지는 동안 바뀌지 않아야** 한다. 매 프레임 새 id를 주면 팝업이 계속 새로 뜬다. 지금의 `RiskPairState`(쌍별 직전 단계)를 기준으로 쌍이 경고에 들어갈 때 id를 만들고, 안전으로 돌아오면 닫는 방식을 제안한다.
- `warning`에서 `danger`로 올라가면 같은 id로 `level`만 바꾼다. 확인한 뒤 다시 `danger`로 올라오면 새 id를 준다.
- `distance_m`, `ttc_s`, `contact`, `object2_id`, `zone_id`, `message`는 종류에 따라 생략한다.
- `contact`는 예상 접촉 지점(평면도 좌표). 없으면 생략한다.

### 2.4 `POST /alerts/{alert_id}/ack` — 위험 확인

```json
{"action": "dispatch"}
```

- `action`: `radio`(현장 무전) / `dispatch`(담당자 출동) / `false-positive`(오탐) / `null`(선택 안 함).
- 응답은 `204 No Content`. 없는 id는 `404`.
- 확인한 사람과 시각, 조치를 이벤트 기록에 남긴다. 로그인이 없는 동안에는 사람 정보를 비워 둔다.
- 30초 안에 확인되지 않은 `danger`는 안전관리자에게 상위 알림을 보낸다(화면은 남은 시간만 보여 준다). 알림 채널은 나중에 정한다.

## 3. 다음 단계 API (전체 현황·이벤트 기록·설정 화면)

화면을 만들 때 다시 다듬는다. 지금은 필요한 것만 적어 둔다.

| API | 쓰는 곳 | 내용 |
|---|---|---|
| `GET /site` | 전체 현황 | 사업장 이름, 전체 크기(m), 배경(`blocks` / `image`) |
| `GET /events?from_ms=&to_ms=&area_id=&kind=&level=` | 이벤트 기록 | 끝난 경고 목록. 2.3 필드 + `ended_at_ms`, `max_level`, `min_distance_m`, 확인 정보(`acknowledged_at_ms`, `action`). 페이지 나눔 |
| `GET /events/{alert_id}` | 이벤트 상세 | 발생 순간의 snapshot(2.2 모양)과 카메라 캡처 이미지 URL |
| `PUT /areas/{area_id}/config` | 설정 | 구역 이름, 크기, 위험 구역(`zones`), 카메라 배정 |
| `POST /areas/{area_id}/background` | 설정 | 도면 이미지 업로드(`multipart`). 축척·원점은 config에 저장 |
| `GET` / `PUT /settings/risk` | 설정 | 충돌 거리·TTC 기준, 위험 구역 접근 거리, 추적 클래스, PPE 판정 켜기·끄기 |

## 4. 오류

FastAPI 기본 모양(`{"detail": "..."}`)을 쓴다. 화면은 첫 로드 실패만 오류로 보여 주고, 그 뒤 실패는 마지막 데이터를 유지한다.

## 5. 정해야 할 것

- 구역 설정(이름, 블록 위치, 크기, 위험 구역, 카메라 배정)을 어디에 둘지: DB 테이블 vs 서버 설정 파일(JSON). 처음에는 설정 파일로 충분하다.
- 구역과 지금의 `session_id` / `calibration_profile` / `algorithm` 조합을 어떻게 연결할지: 관제 화면은 "지금 돌고 있는 세션" 하나만 본다.
- 월드 좌표 → 구역 평면도 좌표 변환(원점 이동, 축 방향).
- PPE 판정을 엣지에서 할지 서버에서 할지, 어떤 모델로 할지.
- 경고음과 상위 알림을 서버에서 보낼지 화면에서 낼지.
