# SW 등록 스프린트 서버 체크 (11/14)

사용자가 전달한 11/12~11/15 계획을 기준으로 한다. 목표는 F1~F5의 영상 → 엣지 → 서버 → 관제 화면 연결 증거와 명세서 원고이며, 보호구 판별·추가 촬영·깊은 최적화/정확도 실험은 제외한다. 이번 스프린트만 목~토 기능 PR을 허용하고 일요일 main 병합 일정을 유지한다. 병합·배포 권한을 뜻하지 않는다.

| 항목 | 상태와 근거 | 남은 작업 |
| --- | --- | --- |
| 서버 push·PR·migration | #83, 0011~0013, PostgreSQL CI 성공 | 리뷰 승인·팀 병합 결정 |
| 데모 DB·위험 분석 | 전용 Compose·DB, 32132에서 risk_analysis=true | 기존 운영은 false 유지 |
| 강의실 실제 리허설 | s10 online/recent·위치·warning·offline 서버 증거 정리 | FE 영상 직접 검토·명세서 캡처 |
| sc10 실제 근접 리허설 | run1 캘리브레이션·지도·Unity 구역 등록, ZIP 130묶음 검증 | 근찬 재생, FE danger 팝업·확인, 서버 기록 |
| 위험구역 침입 | 서버 구현·자동 API 검증, Unity 검토 구역 등록 | 허용된 실제 장면에서 진입 증거 확보; sc10 GT는 모두 outside |
| 강의실 위험구역 | 좌표 미확정, 기존 진단 지도·빈 zones 보존 | 실제 캘리브레이션 원점·구역 꼭짓점 확정 |
| 백엔드 명세서 원고 | API 목록·F3/F4 설명·DB·실습 실행 환경과 s10 결과 반영 | sc10 및 침입 최종 결과·화면 증거 반영 |
| 통합 명세서·main | 근찬 통합, 해민·성윤 검토 예정 | 프로그램 이름·완성일·저작자·학교 양식·소스 제출 범위 확정 |

## sc10 시작 조건

- API: `http://121.182.60.2:32132`
- session_id: `unity-grid-sc10-run1`, calibration_profile: `basic`, algorithm: `baseline`
- 두 카메라 캘리브레이션은 근찬 ZIP의 sent_calibration.jsonl 원문(unity-gt)에서 등록했다.
- 지도: `unity-world-xzy`, X 2.79~7.79 / Y 1.785~6.785m. 구역은 기존 합의 X/Y 3~4m, 주의 거리 0.5m를 유지했다. 지도 왼쪽에서 주의 띠 일부가 잘리는 기존 표시 검토점은 유지한다.
- 근찬이 단일 송신자로 재생한다. ZIP 저장 시각을 재생한다면 ts와 recv_ms에 같은 offset을 더하고 카메라 간 시차·프레임 간격을 보존한다. 별도 서버 송신자는 동시에 실행하지 않는다.
- 성윤은 로컬 Vite의 VITE_SESSION_ID를 이 세션으로 바꾸고 profile/algorithm도 함께 지정한 뒤 개발 서버를 재시작한다. 빌드된 기존 nginx 프론트의 .env 변경으로 프록시가 바뀌지는 않는다.
- 사람–사람 collision danger와 팝업·확인 동작을 우선 관찰한다. 서버 객체 ID를 GT person 번호와 동일하다고 가정하지 않는다. baseline에서 의자가 양쪽에서 매칭되지 않을 수 있으므로 사람–의자 danger 성공을 전제하지 않는다.
- ack는 FE가 수행한다. 서버 담당의 선행 ack로 팝업 증거를 없애지 않는다. 확인은 위험 해제가 아니며 active 상태와 acknowledged를 따로 기록한다.

[sc10 준비 JSON](../benchmarks/2026-11-14-sc10-live-readiness.json) · [s10 실제 서버 관찰](../benchmarks/2026-11-13-s10-live-integration.md) · [백엔드 원고](sw-registration-backend.md)

## 이번 준비의 검증 범위

ZIP CRC·130묶음 스키마·pair_id 1~130·세션 일치, 두 캘리브레이션 스키마, 서버 health/DB, 캘리브레이션 PUT 200 두 건, 지도/구역 PUT 201·조회 일치, cameras 두 대의 heartbeat 미수신·snapshot 204를 확인했다. 실제 탐지·heartbeat·ack 송신은 없었다.

현재 코드의 `backend/tests/test_week2.py`에서 zone·detection_pair_reaches_dashboard_alert_and_ack·alert_ack_retention을 선택해 4개 통과(15개 제외)했다. 가상 입력의 intrusion 경고·ack·종료 보존·재발·조건 격리·구역 revision 정책 검증이며 sc10 실제 침입·팝업 검증을 대체하지 않는다. 테스트용 SQLite를 별도 경로에 사용했고 운영 DB에 테스트를 실행하지 않았다. pytest 상위 cache 권한 경고 두 건이 있었으며 실패는 없었다.

## 오늘 공유할 한 줄

오늘 된 것: sc10 run1 캘리브레이션·지도·합의 구역 등록과 s10 검증 결과의 백엔드 원고 반영. 남은 것: 근찬 재생·성윤 danger/ack 화면 검증, 허용 데이터의 실제 구역 진입 장면과 강의실 구역 좌표 확인.
