# 11/13 s10 실제 엣지·데모 서버 연동 관찰

근찬의 folder 재생을 별도 데모 API에서 읽기 전용 관찰했다. 조건은 `classroom-1014-s10-t1-v91` / basic / baseline, 서버 commit `348f5ff`다. 운영 서버 병합·배포나 저장 탐지 파일의 재전송은 수행하지 않았다.

## 서버 확인 결과

- 관찰 구간: 2026-11-13 **17:33:12~17:35:01 KST**, HTTP polling 191표본. 각 반복에서 cameras → snapshot → alerts를 순차 조회하고 0.5초 대기했다. 세 응답은 원자적 동시 snapshot이 아니다.
- HTTP 응답: 200 543건, snapshot 대기 응답 204 30건. 관찰 요청 오류 없음. 엣지의 전체 전송 성공률을 뜻하지 않는다.
- 두 카메라 모두 heartbeat 미수신(online=null) → online=true → receive_status=recent → 성공 저장 프레임 recent를 확인했다. 최초 heartbeat의 last_recv_ms=null도 수신했다.
- 위치 snapshot 갱신: 처음 관측 seq 4 / pair 68 → 마지막 seq **949 / pair 2043**. 중간 조회에서 여러 seq가 건너뛰므로 polling 횟수를 탐지 묶음 수로 해석하지 않는다.
- 조회 표본에서 warning alert ID 51개를 관찰했다. snapshot의 위험 쌍 표본은 safe 571 / warning 101이며 danger는 관측하지 않았다. 표본 최소 거리는 **0.583609m**다. 전체 이벤트 수·전체 최소 거리·정확도 지표가 아니다.
- 종료 시 두 카메라 모두 frame_status=stale, receive_status=stale, online=false. 첫 offline 조회는 마지막 heartbeat 서버 수신 후 cam1 **3300ms**, cam2 **3273ms**였다. 3000ms timeout과 일치하는 관찰이며 정확한 전환 시점을 측정한 값은 아니다.
- 마지막 프레임 ID는 두 카메라 모두 2043. 마지막 heartbeat가 보고한 dropped_count=1, max_queue_age_ms=48은 각 카메라 payload 값이며 원인·전체 버림 수를 독립 검증하지 않았다.
- 관찰 종료 시 `/alerts`는 빈 목록이다. polling에서 본 warning이 종료 후 목록에 남지 않는 것을 확인했다.

## 증거와 해석 범위

[기계 판독 요약](2026-11-13-s10-live-integration.json)에 상태 전환 시각, HTTP 결과와 원본 로그 SHA256을 기록했다. 원본 HTTP 응답 로그는 Git 제외 `.local-demo/live-s10-20261113T083311Z.jsonl`에 보관했다. 이 파일은 서버 ingress 원본 로그가 아니라 외부 관찰자가 저장한 API 응답 표본이다.

이번 실행은 실제 엣지 folder 재생의 수신·서버 상태·경고 API 검증이다. 이전 저장 탐지 재생 결과인 822쌍·최소 0.61594m와 입력 경로·관측 범위가 다르므로 같은 측정 결과로 합치지 않는다. 재시도·별도 실행 전체를 포괄한다고 주장하지 않는다.

프론트 수신은 팀 대화에서 성윤이 확인했으나 서버 관찰자가 영상·렌더링을 직접 검토하지 않았다. 프론트 영상 편집·화면 검증은 FE 자료로 별도 첨부한다. folder heartbeat는 재생 프로세스의 상태이며 물리 카메라 연결 검증이 아니다. 진단 지도는 실제 도면 정합으로 사용하지 않는다. sc10 실제 탐지 재생과 danger 팝업·ack 검증도 이번 결과에 포함하지 않는다.
