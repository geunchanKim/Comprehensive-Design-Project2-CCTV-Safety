# 11/12 로컬 PostgreSQL 관제 API 검증

검증 코드: `75276bf`. [기계 판독 결과](2026-11-12-local-dashboard-validation.json).

## 실행 환경

- Windows x64, Python 3.12, PostgreSQL 16.15, Node.js 22.23.5.
- PostgreSQL은 공식 EDB Windows 바이너리로 설치하고 별도 데모 DB를 생성했다. Node.js는 공식 배포 ZIP과 공식 SHA256의 일치를 확인했다.
- 설치 파일·DB·접속 설정·실행 로그·로컬 점검 도구는 Git에서 제외한 `.local-demo/`에 둔다. DB는 비밀번호 인증을 사용하고 `127.0.0.1:55432`에서만 수신한다.
- 데모 API는 `127.0.0.1:8001`, 로컬 API 점검 페이지는 `127.0.0.1:8002`다. 다른 PC에서 접속할 주소는 아직 제공하지 않는다.
- 데모 프로세스에서만 `ENABLE_RISK_ANALYSIS=true`를 사용했다. 저장소 운영 기본값은 false를 유지한다.

## 확인한 결과

1. 빈 PostgreSQL 데모 DB에 Alembic 전체 이력을 0013까지 적용했다. `alembic check`는 추가 변경 없음으로 통과했다.
2. 실행 중인 API의 `/health`, `/health/db`가 모두 ok를 반환했다. 점검 페이지는 HTTP 200을 반환했다.
3. 기존 강의실 `real-s1-t1` 저장 탐지 pack을 실제 HTTP로 전송했다. 조건은 `basic/baseline`, 빈 위험구역이며 운영 높이·거리 기본값을 변경하지 않았다.
4. 536개 입력 모두 저장됐으며 각 입력과 같은 pair_id의 위치 snapshot을 확인했다. 위치가 있는 snapshot은 536개, collision 경고 발생 ID는 9개였다.
5. 경고 1건의 ack API 성공 후 PostgreSQL의 확인 시각 저장을 검증했다.
6. 저장 탐지 pack 송신 프로세스가 카메라별 folder heartbeat를 보냈다. 카메라 조회의 online=true를 확인했고 송신 종료 후 3.2초 대기 뒤 모두 offline으로 바뀌는 것을 확인했다.

## 해석과 남은 일

- 이 검증 범위는 **저장 탐지 입력 → 실제 PostgreSQL 서버 API**다. 원본 영상의 탐지 재실행과 실제 카메라 heartbeat 검증이 아니다. heartbeat는 pack 재생 송신 프로세스의 응답 상태다.
- 입력 전송은 가속 재생했다. 보고된 26.75초는 이 검증 스크립트의 전체 실행 시간이며 실시간 처리 성능·카메라 지연 측정값으로 사용하지 않는다.
- 지도 bounds는 진단용이고 실제 도면 정합을 검증하지 않았다. 경고 9건은 발생 ID 개수이며 정답 기반 정확도 평가가 아니다.
- 점검 페이지는 팀 프론트와 별도다. 브라우저 자동화가 현재 URL을 확인하지 못해 중단됐으므로 시각적 표시·클릭 검증은 미완료다. HTTP 200을 화면 정상 동작의 근거로 사용하지 않는다.
- 팀 프론트 연결, 외부 PC 접속, 실제 영상·heartbeat 종단 리허설, Unity sc10, 실제 관제 화면 캡처와 리뷰·배포는 남아 있다.

이 결과는 CI PostgreSQL 검증과 별개로 이 PC에서 직접 실행한 기록이다. PR 생성·push는 develop 병합이나 실습 서버 배포 완료를 의미하지 않는다.

## 구성된 PC에서 시작·종료

저장소 루트의 PowerShell에서 실행한다. 이미 설치·초기화된 `.local-demo/`와 그 안의 설정·점검 도구를 사용하는 관리 스크립트이며 다른 PC의 설치를 자동화하지 않는다. 비밀번호를 명령행에 입력하거나 출력하지 않는다.

```powershell
./scripts/manage-local-dashboard-demo.ps1 -Action status
./scripts/manage-local-dashboard-demo.ps1 -Action stop
./scripts/manage-local-dashboard-demo.ps1 -Action start
```

start는 PostgreSQL·API·점검 페이지를 숨김 프로세스로 실행하고 준비 응답을 확인한다. 실행 중인 관리 프로세스는 다시 시작하지 않는다. stop은 저장한 PID의 실행 파일·명령행을 검사한 뒤 해당 데모 Python 프로세스와 전용 DB만 종료하고 DB 파일은 보존한다. PID가 다른 프로세스에 재사용됐으면 종료를 거부한다. DB 인증 정보·프로세스 기록은 계속 Git에서 제외한다.

실제로 stop → start 후 snapshot seq 536, 저장 입력 536개, 경고 9개, ack 1개의 보존을 확인했다. start를 다시 호출해 기존 서비스가 유지되는 것도 확인했다. API DB health와 점검 페이지는 각각 HTTP 200을 반환했다. 이 확인은 브라우저 시각 검증을 대신하지 않는다.

프론트 연결은 현재 `.local-demo/condition.json`의 session_id·calibration_profile·algorithm을 세 쿼리로 모두 전달한다. 재생 스크립트가 새 세션을 만들면 이 파일의 값도 바뀐다. 서버 프로세스 시작 시의 기본 세션과 새 재생 세션이 다를 수 있으므로 조회 조건을 생략하지 않는다. 재생이 끝나면 오래된 위치와 offline이 남는 것이 정상이며 현재 실시간 카메라 관측으로 해석하지 않는다.
