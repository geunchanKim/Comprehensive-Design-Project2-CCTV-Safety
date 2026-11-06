# 2주 차 서버 구현

2026-11-05, `origin/develop`의 `61a69c7`에서 시작한 로컬 구현이다. 배포·FE 실연동 완료를 뜻하지 않는다. 1주 차 계약을 유지하고 snapshot 전달·위험구역 판정을 추가했다. 전체 위험 분석 기본값 false와 안전조끼 unknown은 유지한다.

## 준비와 운영 조건

백엔드 디렉터리에서 `python -m alembic upgrade head`로 `0011`을 적용한다. PostgreSQL의 `dashboard_states`에 조건별 지도·구역·최신 snapshot·seq·stream ID·프레임 관측을 저장한다. 탐지와 snapshot은 같은 트랜잭션에서 커밋된다. 실패·중복 요청은 발행하지 않는다. PostgreSQL 행 잠금으로 같은 조건의 발행과 구역 수정을 직렬화한다. SQLite 검증은 단일 쓰기 기준이며 PostgreSQL 동시 실행 실측은 별도로 수행한다.

모든 경로는 `session_id`, `calibration_profile`, `algorithm` 세 쿼리 값을 함께 받는다. 부분 지정은 422다. 모두 생략하면 `DASHBOARD_SESSION_ID`, `DASHBOARD_CALIBRATION_PROFILE`, `DASHBOARD_ALGORITHM`을 사용한다. 하나라도 미설정이면 계약대로 503이다. 임의의 최신 실험을 선택하지 않는다. Compose와 `.env.example` 기본값은 비어 있다.

`PUT /dashboard/configuration`에 `{"map": DashboardMap, "zones": ZoneSet}`을 전달해 조건을 명시적으로 초기화한다. frame ID가 다르면 422, 기존 조건이면 409, 성공하면 201과 ETag `"1"`이다. 예시 구역은 자동 등록하지 않는다. 지도 원점·bounds는 실제 캘리브레이션과 맞춘 뒤 설정한다. 지도 변경은 새 세션을 사용한다.

## 읽기와 실시간 전달

- `GET /dashboard/snapshot`: 최신 성공 저장 결과를 반환한다. snapshot이 없으면 body 없는 204다. 같은 결과를 조회해도 stream ID·seq·생성 시각은 바뀌지 않는다. 응답은 `Cache-Control: no-store`다.
- `GET /dashboard/events`: SSE `event: snapshot`, `id: stream_id:seq`, `data: snapshot JSON`을 보낸다. 접속 시 현재 결과부터 시작하며 `Last-Event-ID` 이력을 재생하지 않는다. 250ms마다 DB의 최신 한 건을 읽고, 변화가 없으면 15초마다 주석 keepalive를 보낸다. 클라이언트별 과거 snapshot 큐는 없다. 재접속·느린 수신자에게 중간 seq가 생략될 수 있다.
- FE polling 합의값은 500ms이며 AreaPage의 주기를 맞췄다. 현재 FE 데이터 소스는 여전히 mock이다. HTTP adapter·화면 연동은 FE 후속이다. 같은 seq나 keepalive로 stale 1000ms 타이머를 갱신하지 않는다.
- stream ID·seq는 DB에 저장하므로 프로세스 재시작만으로 초기화하지 않는다. 재계산은 이전 ID·판정이 섞이지 않도록 해당 조건의 snapshot을 비우고 새 stream ID로 시작한다.

## 구역 저장과 판정

`GET /dashboard/zones`는 ZoneSet과 ETag를 반환한다. `PUT /dashboard/zones`는 전체 교체이며 현재 ETag를 `If-Match: "1"`처럼 전달한다. 헤더 누락 428, 오래된 버전 412, 잘못된 다각형·frame 불일치 422, 미등록 조건 404다. 저장 시 revision을 올리고 이전 snapshot을 무효화한다. 새 탐지가 없으면 snapshot GET은 204이며 화면은 기존 stale 기준을 유지한다.

새 탐지부터 활성 구역별로 사람의 월드 XY를 판정한다. 내부·경계는 intrusion/0m, 외부에서 경계 최단 거리 ≤ 주의 거리는 warning, 그 밖은 outside다. 오목 다각형·시계/반시계·겹친 구역을 지원하며 disabled 구역과 비사람 객체는 판정하지 않는다. 지도 밖 좌표도 원래 좌표로 판단하고 snapshot에 남긴다. 빈 프레임에서는 객체·이전 침입을 반복하지 않는다. 이 API로 생성한 snapshot은 `zone_evaluated=true`, `vest_evaluated=false`다. 기존 변환 함수 단독 호출은 명시적으로 판정을 켜기 전까지 unknown을 유지한다.

## 카메라 조회

`GET /dashboard/cameras`는 설정된 조건의 카메라를 반환한다. `world=-Rᵀt`, yaw는 월드 +X 기준 반시계 각도다. 영상 중앙과 좌우 끝 광선을 카메라 자세로 월드에 돌려 XY 시야각을 계산한다. precise는 렌즈 왜곡을 보정하고 basic은 기존 알고리즘처럼 raw K를 사용한다. 수직 광축처럼 평면 방향이 정의되지 않으면 yaw/fov는 null이다. 도면상의 시야각은 지면 가시영역 전체를 뜻하지 않는다.

`last_frame`은 `frame_id`, `captured_at_ms`, `server_observed_at_ms`, `detection_count`다. server 관측 시각은 snapshot을 구성한 서버 시각이며 카메라 노출·엣지 수신 시각이 아니다. 성공 저장된 빈 프레임도 기록한다. 이 시각으로 `frame_status=recent/stale`(1000ms)를 표시하고 기록이 없으면 unknown이다. `online=null`은 heartbeat 기록이 없다는 뜻이다. 11/6 추가한 연결 판정은 아래 heartbeat 계약을 따른다. 프레임 상태만으로 실제 카메라 연결을 확정하지 않는다.

## 남은 연동·검증

로컬 검증: backend/edge 합계 **138개 테스트 통과**. 다각형 경계·주의 거리·오목/역방향, 조건 분리·204/422/503, 중복/커밋 실패 시 발행 금지, seq 유지, 빈 프레임·카메라 unknown/stale, 구역 버전 충돌·무효화, SSE 현재 snapshot·재접속·대기 취소를 포함한다. 임시 SQLite의 기존 0010 모델에서 0011 upgrade → alembic check → downgrade → upgrade를 통과했다. 빈 SQLite에 전체 과거 이력을 적용하는 검사는 기존 0007의 ALTER 제약조건 미지원으로 실패했다. PostgreSQL 전체 이력 적용 성공으로 보고하지 않는다. FE 의존성이 설치되지 않아 빌드는 실행하지 않았다.

기존 서버와 동일하게 인증이 추가되지 않은 로컬 API다. 공개 배포 전에 접근 권한·수정 권한·구독 조건을 확정한다. 자동 배포하지 않았다. 카메라 heartbeat 계약·timeout은 AI와, 실제 마커 원점 지도·FE adapter와 SSE 재접속 화면은 담당자와 확인한다. PostgreSQL 다중 worker·동시 구역 수정, reverse proxy SSE buffering, 실제 v8/cdfg 성능·큐 최신성 정책은 실습 환경 검증이 남는다. 영속 alert/ack는 별도 후속이며 이 구현에 포함하지 않는다.


## 11/6 heartbeat 후속 (#71)

`POST /edge/heartbeat`는 탐지 큐·지도 설정과 독립적으로 아래 JSON을 저장하고 204를 반환한다. session/camera 단위이며 calibration/algorithm과 무관하다. 백엔드에서 `python -m alembic upgrade head`로 0012까지 적용한다.

```json
{"session_id":"demo","camera_id":"cam1","edge_run_id":"unique-per-run","source":"rtsp","last_recv_ms":8000,"sent_at_ms":8100,"dropped_count":0,"max_queue_age_ms":0}
```

엣지는 카메라마다 1초 주기로 탐지 큐와 분리해 보낸다. `source`는 rtsp/folder이며 folder의 online은 재생 프로세스 응답 상태다. 최초 프레임 전 `last_recv_ms=null`을 허용한다. 시각·통계는 음수가 아니며 last_recv는 sent_at 이하이다. 같은 run에서 sent_at이 같거나 과거인 요청은 204로 무시하며 서버 수신 시각을 갱신하지 않는다. 새 run은 시계와 통계를 초기화할 수 있다. 카메라마다 송신 요청을 직렬화하고 이전 run의 송신을 종료한 뒤 새 run을 시작해야 한다. 서로 다른 run의 지연 요청 순서는 서버가 판별하지 않으므로 동시에 여러 송신자가 같은 session/camera를 쓰면 안 된다.

`GET /dashboard/cameras`의 online은 서버 수신 후 3000ms 미만이면 true, 이후 false, 기록이 없으면 null이다. `receive_status`는 `(sent_at_ms-last_recv_ms) + 서버 수신 이후 경과`가 2000ms 미만이면 recent, 이후 stale, 최초 프레임 전이면 unknown이다. 엣지·서버 절대 시각은 서로 빼지 않는다. 네트워크 편도 지연은 이 계산에 포함되지 않으므로 실제 노출 최신성을 보장하지 않는다. 원본 heartbeat와 `server_received_at_ms`도 반환한다. 성공 탐지 기반 frame_status와 별개이며 snapshot seq를 갱신하지 않는다. source/drop/queue 통계는 그대로 제공한다.

1주 차 릴리스 #80에는 이 2주 차 기능을 포함하지 않는다. 3초/2초 기준은 AI 제안값이며 유선 실측 뒤 재검토한다. 공개 배포 전 인증·카메라 소유권 확인은 여전히 필요하다.

11/6 검증: backend 102개·edge 37개 통과. 임시 SQLite의 0011 모델에서 0012 upgrade → check → downgrade → upgrade → check를 통과했다. PostgreSQL 실제 동시 실행과 엣지 송신 연동은 검증하지 않았다. pytest 캐시 경로 권한 경고 2개가 각 실행에 있었으며 테스트 실패는 없었다.
