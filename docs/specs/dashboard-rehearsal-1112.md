# 11/12 서버 리허설 인계

추가 도구 포함 검증: backend 115개·edge 37개 통과. Bash 구문 검사와 저장 탐지 도구의 로컬 PostgreSQL HTTP 재생도 통과했다. [공유 가능한 검증 요약](../benchmarks/2026-11-12-rehearsal-readiness.json)에 실습 서버 확인과 로컬 검증을 구분했다. Linux 실행기의 서버 실구동은 아직 검증하지 않았다.

## 현재 확인한 실습 서버

실제 HTTP 조회 기준 API는 `http://121.182.60.2:32130`, 배포 커밋은 `ff68630`이다. `/health`와 `/health/db`는 200이다. baseline 위험 분석은 false이며 OpenAPI에는 dashboard, heartbeat, alerts/ack API가 없다. 따라서 이 주소를 **대시보드 데모 준비 완료 주소로 안내하면 안 된다**. 운영 위험 분석 기본값과 기존 실험 DB는 변경하지 않았다.

사용자 요청에 따라 `classroom-1014-s10-t1-v91`의 cam1·cam2 basic 캘리브레이션은 이 실습 서버에 실제 등록했고 각각 HTTP 200을 확인했다. 원본은 `ai/calibration/output/calib-classroom-1014-2x2b.json`, 해상도는 1920×1080이다. 실습 서버에는 탐지 데이터를 보내지 않았다. 위험 분석 false로 세션 처리 설정이 저장되면 이후 true 프로세스에서 같은 조건을 쓸 때 충돌할 수 있기 때문이다. 별도 데모 DB를 사용하면 그 DB에 캘리브레이션을 다시 등록한다.

GitHub에서 확인한 PR #83 HEAD는 `d06064a`, Draft다. #34와 현재 `deploy.yml`에 따르면 배포는 실습 서버의 self-hosted runner `cctv-server`에서 수행한다. SSH 방식은 접속 시간 초과 때문에 폐기했다. `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`는 Secret 이름만 확인할 수 있고 값은 읽을 수 없다. 이 PC에는 SSH 설정/키가 확인되지 않았고 runner 상세 API도 403이다. 임의의 계정·경로·포트를 추정해 접속하거나 workflow_dispatch·push·merge를 실행하지 않았다.

## 로컬에서 완료한 실제 입력 검증

| 항목 | 결과 | 범위 |
| --- | --- | --- |
| s10-t1 v7 저장 탐지 | 822/822 저장, 86.75초, 마지막 pair 2034 | basic/baseline, 현재 시각으로 동일 offset 보정 |
| s10-t1 거리·경고 | 최소 0.61594m, warning 531개 쌍 표본, danger 0 | 발생 건수나 정확도 지표가 아님 |
| sc10 메타데이터 호환성 | 130프레임, 객체 기록 520개 | 원본 ZIP 재검증 |
| sc10 GT에서 만든 API 입력 | 130/130 저장, 8.61초, 최소 0.38863m | **YOLO 탐지 아님**, bbox·발목 정답 픽셀 사용 |
| sc10 danger 확인 | danger 발생 건 2개 | 진행 중 ack → active 유지, 종료된 미확인 danger 유지, ack 후 목록 제거, 재확인 204 |
| heartbeat | 두 재생 모두 미전송 | online=null, receive_status=unknown 유지 |

검증 서버는 localhost의 별도 PostgreSQL DB와 위험 분석 true 프로세스다. 실행 중 `/health`의 commit 표시는 `32f3be0`이므로 현재 checkout `d06064a`와 구분한다. 운영 높이·거리 기본값은 바꾸지 않았다. sc10은 실제 영상 추론 환경(torch/ultralytics)이 이 PC에 없어 메타데이터 기반 서버 검증까지만 완료했다. 실제 팀 프론트 팝업·영상 탐지·엣지 heartbeat 종단 성공을 의미하지 않는다.

로컬 원본 증거는 Git 제외 경로 `.local-demo/s10-v91-report.json`, `s10-v91-responses.jsonl`, `sc10-gt-contract-report.json`, `sc10-ack-report.json`, `sc10-metadata-recheck.json`이다. 클래스 합계는 person 4,574, chair 2,537, suitcase 7로 공유값과 같다. s10 지도는 `classroom-diagnostic-xy`, -15~15m 임시 범위다. 실제 강의실 도면 정합으로 사용하지 않는다. sc10 지도는 기존 합의대로 `unity-world-xzy`, X 2.79~7.79, Y 1.785~6.785m를 사용했다.

## 준비된 실행 도구

저장 탐지 재생 도구는 기본 실행에서 파일 검증만 하고 서버를 변경하지 않는다. ZIP·JSONL·JSONL.GZ를 받으며 실제 전송은 `--send`로 명시한다. 원본은 수정하지 않고 모든 frame의 ts·recv_ms에 같은 offset을 더하며 pts_ms와 카메라 간 시차, pair 번호의 빈 간격은 유지한다. cam1 ts의 차이로 재생을 예약한다. 전송 중 HTTP 오류가 나면 멈추고 부분 보고서를 남긴다. 자동 재시도·세션 초기화·heartbeat 합성은 하지 않는다. 재시도는 새 세션을 사용한다.

저장소 루트에서:

```bash
python -m backend.tools.replay_capture /path/to/s10-t1-v7-detections.zip \
  --session classroom-1014-s10-t1-v92 \
  --calibration ai/calibration/output/calib-classroom-1014-2x2b.json \
  --configuration docs/specs/examples/classroom-s10-diagnostic-dashboard.json \
  --server http://127.0.0.1:8001 --out /path/to/new-report.json
```

위 명령은 offline 검증이다. 새 데모 DB/프로세스가 준비되면 `--send`를 추가한다. 서버에 dashboard/heartbeat/alerts API가 없거나 baseline risk_analysis가 false이면 등록·전송 전에 중단한다. 기존 지도 설정이나 snapshot을 덮어쓰지 않는다. 보고서와 응답 파일 이름도 새 이름을 사용한다. v91은 근찬의 직접 엣지 재생용으로 남겨 두고 파일 재생 리허설은 v92 이상 새 버전을 사용한다.

Linux에서는 별도 데모 DB의 `DATABASE_URL`을 프로세스 환경에 설정하고 다음을 실행한다. DB 연결 문자열은 Git·채팅·공유 로그에 넣지 않는다.

```bash
bash scripts/start-dashboard-demo.sh
```

Windows에서는 기존 `scripts/start-dashboard-demo.ps1`에 별도 DB 주소와 `-SessionId classroom-1014-s10-t1-v91`을 전달한다. Linux 도구도 basic/baseline과 데모 프로세스의 위험 분석 true만 사용하며 운영 기본값은 유지한다. migration은 head(0013)를 적용한다. listener 기본값은 localhost:8001이다. 사설망 접근 경로·허용 포트는 서버 담당 환경에서 확인하고 제공해야 한다. 기존 공개 실험 API를 바로 대체하거나 새 공개 포트를 임의로 열지 않는다.

## 실제 팀 리허설 순서와 완료 판정

1. 리뷰된 서버 코드로 별도 PostgreSQL 데모 DB·프로세스를 실행한다. `/health`의 baseline risk_analysis=true, `/health/db`, OpenAPI의 dashboard·heartbeat·alerts/ack를 확인한다. 이 과정의 push·merge·배포는 별도 컨펌 뒤 진행한다.
2. 실제 강의실 원점·bounds가 확인되면 지도와 빈 zones를 같은 coordinate_frame_id로 등록한다. 임시 진단 지도를 쓰면 실제 지도 검증 완료로 표시하지 않는다. 지정 파일에서 cam1·cam2 basic을 해당 DB의 v91 세션에 등록한다.
3. 근찬에게 **실제 접근이 확인된 데모 주소**와 v91/basic/baseline을 전달한다. 동시 송신자는 하나만 둔다. 엣지는 camera별 1초 heartbeat, source=folder로 재생한다. 최소 0.62m인 s10에서 warning을 확인하고 danger는 기대하지 않는다.
4. 성윤의 실제 HTTP adapter에서 snapshot/cameras/alerts를 500ms polling한다. 모든 요청에 동일 조건을 넣는다. snapshot 204는 body를 파싱하지 않으며 같은 seq로 stale 타이머를 갱신하지 않는다. heartbeat 없는 null을 offline으로 단정하지 않는다. Vite는 `/api`를 제거해 backend로 전달한다.
5. sc10 실제 엣지 탐지를 별도 Unity 세션으로 실행한다. danger 팝업에서 `/alerts/{alert_id}/ack`에 `{"action":null}`을 보내 204를 받고 `/alerts`를 재조회한다. ack 자체로 위험이 해제되지 않음을 확인한다. 종료됐지만 미확인인 danger는 남고 확인 후 사라져야 한다.
6. 실제 관제 화면·팝업을 캡처하고 재생 조건, 서버 commit, source, DB migration, 확인 결과를 명세서에 반영한다. 현재 팀 프론트 소스는 mock이므로 API 점검 화면 결과로 이 항목을 대체하지 않는다.

남은 외부 의존성은 실습 서버에서의 데모 프로세스 실행 경로/권한, 프론트 HTTP adapter 연결, 실제 엣지 재생과 지도 정합이다. 서버 주소만 확인됐다고 이 항목들을 완료로 표시하지 않는다. 팀 전달은 이 문서 준비까지이며 메시지·댓글은 자동 전송하지 않았다.

## 11/13 재확인: 엣지 인계와 sc10 원본

Git 원격 조회 결과 `develop`은 `ff68630`, `feat/server-week2-dashboard`와 PR #83 HEAD는 `496f54b`였다. 아래 결과는 해당 코드와 실행 중인 서버를 구분한 재확인이다.

- 공개 실습 API `http://121.182.60.2:32130`: `/health`, `/health/db` 응답 정상, commit `ff68630`, baseline risk_analysis=false. OpenAPI에 `/dashboard/cameras`, `/edge/heartbeat`, `/alerts`, `/alerts/{alert_id}/ack`가 모두 없다. 엣지 heartbeat 리허설용 주소로 전달하지 않는다.
- 로컬 API `http://127.0.0.1:8001`: health·DB 정상, 위 네 API 존재, baseline risk_analysis=true. 실행 프로세스의 commit 표시는 `32f3be0`으로 현재 checkout과 다르다. 외부 PC 접속을 확인한 주소가 아니다.
- 로컬 v91/basic/baseline 조회: cam1·cam2 등록과 기존 마지막 frame 2034를 확인했다. 두 카메라 모두 frame_status=stale, online=null, receive_status=unknown, heartbeat=null이다. 이 세션의 실제 엣지 heartbeat 리허설은 아직 수행하지 않았다.
- 현재 코드에서 `python -m pytest --confcutdir=backend/tests backend/tests/test_week2.py -q`: 19개 통과. heartbeat 시각·중복 요청·timeout·조건 격리 검증을 포함한다. 상위 `C:/conftest.py`의 별도 의존성을 피하도록 테스트 탐색 경계를 지정했다. pytest의 상위 cache 쓰기 권한 경고 2개가 있었으며 테스트는 통과했다.

### sc10 전달 자료

sc10 원본이 이 PC의 Git 제외 경로 `ai/runs/week1-prep/unity-grid-sc10.zip`에 존재한다. 메타데이터만 있는 상태가 아니므로 성윤에게 원본을 다시 요청할 필요는 없다.

- 기존 Unity 담당자 공유 출처: [이슈 #72](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/72)
- 팀 다운로드 링크: [unity-grid-sc10.zip](https://drive.google.com/file/d/1YUGeZL7-I1aA7zUTQXisRXhiP9FJH3ZZ/view?usp=sharing). 기존 공유 링크를 재전달하며, 이번에 Drive 접근 권한을 별도로 검증한 것은 아니다.
- ZIP 크기 137,397,212 bytes, CRC 전체 검사 통과.
- `unity-grid-sc10/cam1/`, `cam2/`에 JPG 각 130장, `cameras.json`, `frames.jsonl` 포함. frames.jsonl은 130행이다.
- SHA256: `17ece87b52f4e36644659d20440396e5b6586b322bb15fdef4ed9b06b4a91c95`

근찬의 s10 직접 재생은 `classroom-1014-s10-t1-v91` / basic / baseline, 카메라별 1초 heartbeat, source=folder를 유지한다. 실제 접근 가능한 데모 주소가 준비된 뒤 단일 송신자로 실행하고 재생 중 online=true·receive_status=recent, 마지막 heartbeat 수신 후 3000ms 이상에서 online=false를 확인한다. frame_status=recent는 성공 저장 프레임의 별도 상태다.

sc10은 위 원본으로 엣지 탐지를 수행한 `sent_detections.jsonl`과 실제 사용 session_id를 받는다. session_id는 엣지 담당자가 규칙에 맞춰 확정하며, 기존 GT 기반 세션과 구분한다. 원본 존재·압축 무결성 확인을 이미지 디코딩·YOLO 추론·실제 화면 리허설 완료로 해석하지 않는다.

남은 작업은 PR 리뷰 후 별도 데모 DB·프로세스 실행과 외부 접근 검증, 실제 s10 heartbeat 재생, sc10 탐지 결과 수신, 프론트 종단 검증이다. push·merge·배포는 별도 컨펌 전 수행하지 않는다.
