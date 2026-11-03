# 1주 차 리뷰 후속과 이슈 정리

2026-11-04 확인 기준. 원격 develop은 PR #75 병합 커밋 `2e1d2c3`이며 현재 코드와 `982062e`의 파일 차이는 없다. #71·#72·#74와 #75 최신 댓글을 확인했다.

## 배포 확인과 v7 준비

공개 `/health`를 직접 조회해 아래 유효값을 확인했고 `/health/db`는 connected였다. 서버 `.env` 파일을 직접 열어 본 것은 아니므로 명시 override의 존재 여부까지 단정하지 않는다.

| 항목 | 확인값 |
| --- | --- |
| 배포 커밋 | `2e1d2c3` |
| 발목 높이 범위 | -0.1~0.15m |
| 상자 하단 높이 범위 | -0.35~0.2m |
| 매칭 거리 | 1.5m |
| ground / single-camera 발목 투영 높이 | 0.08 / 0.08m |
| floor track gate | 0.8m |
| 동기화 / epipolar | 50ms / 50px |
| improved 기능 | floor·fallback·hysteresis·ground (`cdfg`) |
| 전체 위험 분석 | false |

v7 목록과 `calib-classroom-1014-2x2b.json`으로 15세션 × 2카메라 × 2profile = 60개 payload 사전 검증을 통과했다. 기존 준비 파일을 보존하고 `ai/runs/week1-prep/registration-plan-v7-20261103.json`에 생성했다(로컬 실행 자료). 11/3 사용자 명시 승인 후 실습 서버에 실제 등록했으며 **60건 모두 HTTP 200**으로 성공했다. 등록 전 배포 `2e1d2c3`와 위 유효 설정·DB connected를 다시 확인했다. 등록기 종료 코드는 0이다.

실제 등록에 사용한 명령이다. 이미 완료했으므로 재생 준비를 위해 다시 실행할 필요는 없다.

```powershell
python ai/calibration/register_calibration.py --calib ai/calibration/output/calib-classroom-1014-2x2b.json --sessions ai/calibration/sessions/classroom-1014-v7.txt --backend-url http://<실습서버>:32130
```

v7 재생을 위한 캘리브레이션 등록은 완료됐다. AI가 같은 녹화를 같은 장비·모델 설정으로 재생하고, 실행 커밋·시작/종료 시각·health 설정·원본 로그를 함께 공유하면 BE가 `session/profile/algorithm + frame=pair_id`로 RTT와 서버 단계를 연결한다. 세션별 예열 5짝을 동일하게 제외한다. v6는 0.4m/2.0m, v7은 0.15m/1.5m 설정이므로 시간 차이를 계측 도입 효과 하나로 귀속하지 않는다. 서버 실측을 받은 뒤 최적화 두 단계를 선정한다.

## 이슈별 완료와 잔여 범위

| 이슈 | 확인 완료 | 남은 작업 / 종료 조건 |
| --- | --- | --- |
| [#71 AI·엣지](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/71) | 시간 필드·frame 연결·좌표·vest 계약, v6 등록 및 15세션 로그 검증, 계측 배포·합의 설정 확인, v7 60건 등록 | v7 로그 검증·서버 단계 비교 완료. 후속 cdfg 측정·함수 밖 지연 조사, 조끼 데이터셋 원문/버전/라이선스·교실 사진 날짜·조끼 준비 현황. 열어 둠 |
| [#72 Unity·대시보드](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/72) | 데이터/버전/샘플·5개 장면 대응표·world 좌표/지도 범위·검토용 구역·GT 이벤트 산출, #74 mock 화면/추가 요구 공유 | SSE/GET·지도 경계 표시 합의 및 GET 세부 규칙 회신 완료. 추가 API 구현은 #74에서 관리하며 이슈를 중복 생성하지 않음 |
| [#74 관제 추가 요구](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/74) | 요청 접수·현 코드 대조 | 공개 snapshot GET·cameras·영속 alert/ack·판정 대상 설정 모두 미구현. 아래 일정으로 진행하며 완료 체크는 구현·검증 후 수행 |

## #74 구현 순서와 리뷰 결정

1주 차 완료 조건·SSE/지도 표시 제안과 v7 로그 인수 절차는 [마무리 검토안](week1-closeout.md)에 정리했다. #76 `4e31f45` 수정 재검토·엣지 36개 통과(EOF 뒤 늦은 실패 종료 처리 추가 요청), v7 3,020건 검증·2,945표본 서버 시간 표 작성과 #72 FE 합의를 완료했다. [v6/v7 비교](../benchmarks/2026-11-04-v6-v7-comparison.md)에서 baseline 서버 개선 후보 commit·validation을 선정했다.

1주 차에는 계약과 범위를 확정한다. 2주 차에는 최신 snapshot GET과 카메라 상태부터 구현한다. `GET /dashboard/snapshot`은 FE 제안이며 현재 공개 경로가 아니다. 조건 생략 시 운영 조건은 명시적 서버 설정으로 선택하고, DB에서 마지막으로 쓰인 임의 실험을 고르지 않는 방향으로 검토한다. 데이터 없음·조건 미설정 응답, 저장 시점·seq·재시작 기준을 API 구현 전에 확정한다. GET polling에서도 같은 seq 재수신을 새 데이터로 보아 stale 타이머를 연장하지 않는 기준이 필요하다. SSE 우선·GET 선연결은 FE 동의로 확정했고, 500ms polling·성공 저장 시 생성·204 응답·GET stream 변경 처리는 snapshot 명세에 반영했다.

`cameras`의 위치·yaw·수평 fov는 map과 같은 좌표계로 계산한다. K의 초점거리만으로 평면 시야를 단정하지 않고 카메라 자세·영상 크기를 함께 사용한다. 현재 캘리브레이션 API에는 엣지 연결 상태가 없다. 탐지 객체 없음과 프레임 미수신을 구분할 수 있는 heartbeat/프레임 관측 계약, 기준 시계·수신 시각·timeout을 AI와 먼저 맞춘다. `online`을 보정 등록 여부나 오래된 영상의 캡처 시각만으로 만들지 않는다.

경고 ack는 DB 모델·마이그레이션과 함께 별도 구현한다. 충돌/구역/vest를 표현하는 통합 alerts 목록을 검토하고 현재 `risks`의 거리·객체 쌍 계약은 유지한다. 같은 위험의 warning→danger는 같은 ID, 종료 후 재발은 새 ID를 사용한다. 종료된 미확인 danger는 현재 위험 판정과 분리해 남겨야 하며 객체가 snapshot에서 사라져도 ack할 수 있어야 한다. 확인 시각·조치 영속화, 중복 ack, 재시작·다중 화면 동작을 검증한다. 이는 구현 전 검토안이며 현재 스키마를 변경한 것은 아니다.

3주 차에는 클래스 쌍별 판정 대상·거리 설정과 사람–객체 경고 유지, 안전조끼 연결을 진행한다. FE의 사람–객체 기본·사람–사람 선택 요구를 반영할 때 F만 켠 기존 경로도 같은 설정을 따르게 검토한다. 현재 `ENABLE_RISK_ANALYSIS=false`를 유지하며 기본 활성화는 별도 결정한다. 중심점 간 거리 기준을 표시하고 긴 물체 외곽 거리 변경은 별도 평가한다.

여러 구역 목록·종료 이벤트 조회·캡처·도면 업로드는 #74의 다음 단계 제안으로 보존하며 이번 1주 차 작업의 완료 조건에 추가하지 않는다.
