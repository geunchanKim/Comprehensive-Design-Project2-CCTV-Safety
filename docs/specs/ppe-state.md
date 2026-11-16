# 사람 ID별 안전조끼·안전모 상태 (서버)

2026-11-16. 기준 코드: develop `d3079a2`, 모델 규칙 참고: `feat/ppe-model-v1`의 `afac91d`. 모델·엣지 브랜치를 병합하지 않고 서버 수신·상태 유지 계약을 추가한다. 엣지의 실제 전송 연동은 별도 확인이 필요하다.

## 탐지 입력

`POST /detections`의 사람 탐지에 선택 필드 `vest`, `helmet`을 추가한다. 기존 입력은 그대로 받으며 상태는 unknown이다. 예:

```json
{
  "track_id": 7,
  "cls": "person",
  "conf": 0.95,
  "bbox": [950, 400, 970, 540],
  "vest": {"status": "wearing", "confidence": 0.87, "observed_at_ms": 1000},
  "helmet": {"status": "not_wearing", "confidence": 0.91, "observed_at_ms": 1000}
}
```

- 상태는 `wearing`, `not_wearing`, `unknown`. confidence는 유한한 0~1이며 알려진 상태에는 필수다. unknown에는 null을 허용한다.
- `observed_at_ms`는 **해당 보호구를 실제 추론한 시각**이다. 프레임의 `ts`와 같은 시계를 쓰고 `ts` 이하여야 한다. 재생에서 서버 현재 시각으로 대체하지 않는다.
- 보호구를 판별하지 않은 프레임은 필드 생략/null을 사용한다. 캐시 결과를 반복 전송한다면 원래 추론 시각을 유지한다. 매 프레임 시각으로 바꾸면 새 판별로 잘못 센다.
- 추론했지만 판단이 어려웠으면 명시적 unknown을 전송한다. 비사람 보호구 입력, 미래 시각, NaN·무한 신뢰도는 422다.
- 객체 매칭이 성공한 사람의 `camera_tracks`만 서버 object_id에 연결한다. 위치 매칭에 실패한 사람의 보호구를 다른 사람에게 붙이지 않는다.

## 상태 유지

각 object_id의 조끼·안전모를 독립적으로 관리하고 DB에 저장한다. 세션·캘리브레이션 프로필·알고리즘별 객체가 다르므로 상태가 섞이지 않는다. 새 object_id는 unknown에서 시작한다.

| 상황 | 처리 |
| --- | --- |
| 신뢰도 0.4 이상, 두 카메라 유효 상태 일치 또는 한 카메라만 관측 | 새 판별 묶음당 1회 누적, 3회 연속 같으면 확정 |
| 같은 추론 시각의 캐시 반복 | 누적·만료 시각 갱신 안 함 |
| 반대 상태 첫 관측 | 즉시 unknown으로 전환, 새 상태 3회 일치 후 확정 |
| 카메라 간 상충, 명시적 unknown, 신뢰도 부족 | unknown, 연속 횟수 초기화 |
| 보호구 필드 생략 | 마지막 추론 후 3초까지 기존 상태 유지 |
| 마지막 추론 후 3초 초과 | unknown, 이전 연속 횟수 폐기 |
| 이전 시각으로 늦게 도착 | 저장 상태를 되돌리지 않고 해당 응답은 unknown |

시간은 입력 프레임 `ts` 기준이다. 탐지 자체가 끊겨 새 snapshot이 없으면 기존 snapshot은 그대로이므로 화면은 기존 `stale_after_ms`로 오래된 데이터를 미판단 처리한다. 서버가 끊긴 영상의 상태를 안전으로 확정하지 않는다.

설정은 `PPE_CONFIRM_SAMPLES=3`, `PPE_MIN_CONFIDENCE=0.4`, `PPE_MAX_AGE_MS=3000`. 환경변수 override가 우선한다. Compose·환경변수 예시에 전달하며 `/health`의 `ppe`에서 실행값을 확인한다. 운영 위험 분석 활성화 설정과 독립적이다.

설정값이 바뀌면 해당 사람의 이전 보호구 확정 상태·누적 횟수를 초기화하고 새 설정으로 다시 판별한다.

## 응답과 저장

탐지 응답 `matches[]`와 snapshot `objects[]`에 동일 형식의 `vest`, `helmet`을 제공한다. 출력은 `status`, `confidence`, `observed_at_ms`이며, 미확정·상충·만료는 confidence=null이다. snapshot의 `vest_evaluated`·`helmet_evaluated`는 해당 항목에 **현재 알려진 상태를 가진 사람이 한 명 이상** 있으면 true다. true여도 다른 사람은 unknown일 수 있으므로 각 사람의 status를 반드시 확인한다.

원본 입력은 기존 `frame_bundles.source_frames`에 함께 저장하고, 확정 상태와 연속 횟수는 `global_objects.ppe_state` JSON에 저장한다. 탐지·상태·snapshot이 같은 트랜잭션으로 저장되므로 중복·실패 입력은 횟수를 증가시키지 않는다. 재계산은 대상 객체를 지우고 원본 관측 순서로 다시 구축한다. DB 변경은 `0014`이며 실행 전에 backend에서 `python -m alembic upgrade head`가 필요하다.

이번 범위는 상태 수신·유지·snapshot 제공이다. 미착용 `/alerts` 등록은 다음 서버 작업이며, 실제 모델 추론·엣지 전송·대시보드 착용 표시는 각 담당 연동 후 검증한다. 초당 10짝 유지나 CCTV 각도 정확도는 자동 테스트 결과로 대신하지 않는다. 서버 단계 계측에는 `ppe_ms`를 추가한다.
