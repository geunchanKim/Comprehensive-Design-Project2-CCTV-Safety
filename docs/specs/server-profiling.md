# 서버 단계별 처리 시간 측정

`/detections` 성공 응답의 `timings_ms`와 서버 로그의 `detection_timing` JSON으로 느린 구간을 비교한다. 재계산도 같은 함수를 사용하므로 조건별로 측정된다. 기존 위치 추정 기본값과 알고리즘 동작은 유지한다.

## 측정 구간

| 키 | 포함 작업 |
| --- | --- |
| `validation_ms` | 세션 설정·중복 조회, 동기화·캘리브레이션 존재·이미지 크기 검사 |
| `calibration_bundle_ms` | 캘리브레이션 행렬·기초행렬, bundle 생성과 첫 DB flush |
| `ingest_undistort_ms` | 탐지 레코드 구성·왜곡 보정 |
| `matching_position_tracking_ms` | 매칭 후보·삼각측량·평면 투영·객체 ID 연결·기존 추적. 현재 함수 구조상 함께 계측 |
| `floor_tracking_ms` | 바닥 추적과 한 카메라 폐색 보완 |
| `risk_ms` | 거리·TTC·경고 유지와 위험 레코드 구성 |
| `commit_ms` | 트랜잭션 커밋 |
| `response_prepare_ms` | 미매칭 목록과 커밋 이후 bundle ID 조회 |
| `total_ms` | 함수 시작부터 위 구간 완료까지의 단조 시계 경과 시간 |

DB autoflush·조회 시간은 실제 발생한 구간에 포함된다. `total_ms`는 HTTP 요청 파싱, 응답 모델 직렬화, 로그 출력, 네트워크·화면 지연을 포함하지 않는다. 비활성 단계도 분기 통과 시간 때문에 정확히 0이 아닐 수 있다. 실패 요청은 성공 시간 표에 포함되지 않는다.

## 기록과 요약

최신 코드로 서버를 실행하고 기존 엣지 전송 또는 재전송 도구로 동일한 입력을 보낸다. #71 회신에 따라 1주 차는 10/14 녹화 15개(약 4분)를 녹화 속도로 재생한다. 실제 카메라 10분 연속 실행과 구분하며 새 촬영은 마지막 주 검증에서 진행한다. 예열 구간을 별도 세션으로 나누고, 같은 입력·설정·하드웨어에서 반복한다. 실행 커밋은 `APP_COMMIT_SHA`로 전달한다.

```powershell
# 저장소 루트. 실행 중 서버 로그를 수집한 뒤 Ctrl+C로 종료
docker compose -f infra/docker-compose.yaml logs --no-color -f backend | Out-File -FilePath server-timing.log -Encoding utf8

# 세션·캘리브레이션·알고리즘·커밋별 평균, p50, p90, p95, 최대 시간
python -m backend.tools.timing_summary server-timing.log --out server-speed.md
```

측정 환경, DB 종류, 입력 사람 수, 실행 설정, 실행 시간, 에러 수를 표와 함께 기록한다. `APP_COMMIT_SHA=unknown`으로 서로 다른 실행을 한 파일에 모으지 않는다. 기존 엣지 측정은 `ai/eval/timing_summary.py`를 사용한다. 함수 시간의 역수는 실제 초당 처리 짝 수나 전체 지연이 아니므로 목표 달성 근거로 사용하지 않는다.

## 로컬 재현 측정

```powershell
$env:APP_COMMIT_SHA = git rev-parse HEAD
python -m backend.tools.benchmark_pack ai/eval/packs/s4 --pairs 100 --warmup 10 --out ai/runs/server-week1
```

기준 방법과 배포 기능 조합 `f-cdfg`에 각각 예열 10짝 뒤 100짝을 순서대로 처리한다. DB는 임시 SQLite로 강제 분리하며 기존 DB를 사용하지 않는다. 출력 폴더는 새 경로여야 하며, 로그와 속도 표에 실행 설정을 함께 남긴다. 이 명령은 함수 내부 시간을 비교하고 실제 전송 속도·HTTP 지연은 측정하지 않는다.

현재 개발 환경 검증은 로컬 SQLite·저장된 Unity 탐지 입력 기반이며 실제 교실 서버 속도와 구분한다. 운영 속도 표와 개선할 두 단계는 실측 로그 수집 후 결정한다.

## 엣지와 응답 기록 함께 확인

```powershell
python -m backend.tools.measurement_report ai/runs/edge/classroom-1014-s10-t1-v6 --out measurement-v6.md
```

`timings.jsonl`, `sent_detections.jsonl`, `responses_detections.jsonl`, `failed.jsonl`을 읽는다. 하나의 폴더에 세션·profile·알고리즘 조건이 섞이거나 pair_id/frame이 중복되면 거부한다. 세 로그에 모두 있는 pair 수, 저장된 응답 누락, HTTP/전송 실패 수와 구간별 시간을 출력한다. 성공 전송률은 입력 프레임 수신 시각 기준이며 서버 응답 완료율이 아니다.

#71 제안의 `yolo_ms`·`pose_ms`는 카메라별 dict, 기존 `detect_ms`는 포즈를 포함한 전체 탐지 시간이다. `rtt_ms`는 요청 송신~응답 수신이며 엣지 단조 시계 하나로 측정한다. 이 도구는 timings 행의 frame 번호 기준 값과 응답 행의 RTT를 각각 별도 항목으로 지원한다. 없는 값은 0으로 대체하지 않고 unavailable로 남긴다. 엣지 담당이 실제 필드와 저장 위치를 반영한 뒤 샘플로 최종 확인한다.

현재 서버로 보내는 v6 기록에는 server timings가 없을 수 있다. 계측 배포 후 동일 녹화를 새 v7 세션으로 보내 비교한다. 서버 미배포 상태를 배포된 것처럼 해석하거나 v6·v7을 합쳐 평균내지 않는다.
