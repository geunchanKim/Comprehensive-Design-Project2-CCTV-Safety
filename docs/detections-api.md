# Detection and triangulation API

FastAPI의 `/docs`에서 동일한 명세를 대화형으로 확인할 수 있다. 서버 시작 전 `alembic upgrade head`로 테이블을 생성한다.

## 세션 규칙

`session_id`는 한 번의 실험 실행을 식별한다. 같은 Unity 데이터를 다시 실행해 결과를 비교할 때는 `unity-classroom-01-run2`처럼 새로운 `session_id`를 사용한다. 카메라 캘리브레이션, 전역 객체 ID, detection bundle, ground truth가 모두 세션 단위로 저장되므로 새 세션에서는 캘리브레이션도 다시 등록해야 한다.

한 세션에서 `pair_id`는 실험 조건(`calibration_profile`, `algorithm`)마다 고유하다. 엣지의 최초 전송은 항상 `basic + baseline`으로 저장된다.

## 1. 카메라 캘리브레이션 등록

`PUT /cameras/{camera_id}/calibration`에 카메라별 내부 행렬 `K`, 왜곡 계수 `dist`, 회전 벡터 `rvec`, 이동 벡터 `tvec`를 등록한다. `rvec`와 `tvec`는 월드 좌표를 카메라 좌표로 변환하는 OpenCV 외부 파라미터이며, `image_size`는 `[width, height]`다.

```json
{
  "session_id": "unity-classroom-01-run1",
  "calibration_profile": "basic",
  "method": "unity-gt",
  "image_size": [1920, 1080],
  "K": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
  "dist": [0, 0, 0, 0, 0],
  "rvec": [0, 0, 0],
  "tvec": [0, 0, 0],
  "reproj_error_px": 0
}
```

`calibration_profile`은 `basic` 또는 `precise`이며 생략하면 `basic`이다. `basic`은 저장된 왜곡 계수와 관계없이 왜곡 보정을 적용하지 않고, `precise`는 ChArUco 내부 보정값을 적용한다. 동일한 `(session_id, camera_id, calibration_profile)`로 다시 요청하면 해당 캘리브레이션을 갱신한다.

`POST /cameras/{camera_id}/calibration/solve-pnp`는 화면 전체에 분산된 `grid_points` 6개 이상과 계산에 쓰지 않은 `validation_points`를 받는다. 격자점이 한 직선이면 HTTP 422를 반환하며, 계산 후 재투영 RMSE(px), 검증 위치 RMSE·최대 오차(cm), 검증점 수를 `precise` 프로필에 저장한다. 각 검증점은 자신의 `world.z` 높이 평면에서 오차를 계산하므로 원거리·다른 높이 점도 넣을 수 있다.

## 2. 프레임 묶음 전송

`POST /detections`는 최상위에 `session_id`, `pair_id`, 선택적인 `max_sync_delta_ms`와 서로 다른 카메라의 프레임을 정확히 2개 받는다. 각 프레임은 카메라 지연을 보정한 `ts`와 선택적인 카메라 PTS `pts_ms`, 엣지 수신 원본 epoch 시각 `recv_ms`를 받는다. 동기화 검사와 칼만 필터 시각에는 `ts`를 사용하고, `pts_ms`와 `recv_ms`는 기록·진단용으로만 사용한다. `max_sync_delta_ms`는 처음 요청할 때 세션의 실험 설정으로 고정되며 생략 시 서버 `MAX_SYNC_DELTA_MS`(기본 50ms)를 사용한다. 응답은 `pts_delta_ms`, `recv_delta_ms`, `sync_time_basis`, `max_sync_delta_ms`를 함께 제공한다.

```json
{
  "session_id": "unity-classroom-01-run1",
  "calibration_profile": "basic",
  "pair_id": 42,
  "frames": [
    {
      "camera_id": "cam1",
      "frame_id": 42,
      "ts": 1790866800000,
      "image_size": [1920, 1080],
      "detections": [
        {"track_id": 7, "cls": "person", "conf": 0.988, "bbox": [950, 400, 970, 540],
         "foot": [960, 532], "foot_src": "ankle"}
      ]
    },
    {
      "camera_id": "cam2",
      "frame_id": 42,
      "ts": 1790866800020,
      "image_size": [1920, 1080],
      "detections": [
        {"track_id": 9, "cls": "person", "conf": 0.941, "bbox": [850, 400, 870, 540],
         "foot": [860, 531], "foot_src": "ankle"}
      ]
    }
  ]
}
```

지원 클래스는 `person`, `chair`, `cart`, `desk`, `suitcase`, `backpack`이다. `bbox`는 좌상단 원점의 비정규화 픽셀 `[x1, y1, x2, y2]`다. `track_id`는 카메라 로컬 ID다.

`foot`과 `foot_src`는 선택 필드다. `foot`은 이미지 범위 안의 `[x, y]` 픽셀 좌표이며, `foot_src`는 `ankle` 또는 `box`다. `foot`이 없으면 기존 방식대로 bbox 하단 중앙을 사용하고 `foot_src`는 `box`로 저장한다.

사람 탐지는 선택적으로 `"ankles": {"left": [x, y, confidence], "right": [x, y, confidence]}`를 보낼 수 있다. 한쪽은 `null`일 수 있다. `ENABLE_ANKLE_PAIRING=true`(기본값)이면 서버가 왼발목끼리와 오른발목끼리를 각각 삼각측량한다. 두 쪽 모두 유효하면 두 3D 좌표의 평균(`mid`), 한쪽만 유효하면 해당 `left` 또는 `right`를 사용한다. 양 카메라 confidence가 `MIN_ANKLE_CONFIDENCE`(기본 0.6) 미만이거나 같은 쪽 대응이 없으면 기존 `foot`으로 fallback한다. 실제 선택은 각 `observations[].position_method`에서 확인할 수 있다.

엣지 추론 자체가 실패한 프레임은 전송하지 않는다. 정상적으로 추론했으나 탐지가 없을 때만 `detections: []`를 전송한다. 따라서 별도의 `analysis_status` 필드는 사용하지 않는다.

서버는 사람을 두 단계로 연결한다. 먼저 양쪽 카메라에서 모두 발목 좌표가 있는 사람끼리 연결하고, 남은 사람은 양쪽 모두 bbox 하단 중앙으로 다시 계산해 연결한다. `chair`와 `suitcase`는 화면 좌우 끝에서 bbox가 잘리면 반대 카메라의 bbox 폭과 깊이 비율로 원래 바닥 중심을 복원한다. `person`, `cart`, `desk`, `backpack`에는 이 복원을 적용하지 않는다.

각 단계는 에피폴라 오차, 삼각측량 높이, 두 카메라 앞쪽 여부를 헝가리안 알고리즘 실행 전에 검사한다. 기본 에피폴라 허용 오차는 50px이며 `MAX_EPIPOLAR_ERROR_PX`로 바꿀 수 있다. 연결된 로컬 track 쌍에는 세션 범위의 전역 `object_id`가 부여된다.

`algorithm=improved`는 각 카메라 광선과 기준 평면의 교점을 구하고 두 교점의 XY 거리로 헝가리안 매칭한다. `baseline`은 에피폴라 매칭을 사용한다. 발목은 `Z=0.1m`, bbox는 `Z=0m` 평면을 사용하며 기본 거리 기준은 `MAX_GROUND_DISTANCE_M=2.0`이다. S4 자동 실험에서 1.0m는 놓침이 증가했지만 2.0m는 정상 추적 95.4%, 놓침 4.6%, ID 변경 1회로 기존 에피폴라 방식(93.6%, 6.4%, 7회)보다 개선됐다. 응답의 `matching_method`와 `ground_distance_m`으로 실제 적용 방식을 확인할 수 있다.

`algorithm=improved`에서는 기본적으로 칼만 필터와 트랙 쌍 유지가 함께 적용된다. `ENABLE_KALMAN_FILTER=false`로 칼만 필터만 끌 수 있다. 활성화되면 객체별 `[x, y, z, vx, vy, vz]` 상태를 DB에 저장하고 다음 프레임에서 이어서 보정한다. 이때 `world`는 보정 위치, `raw_world`는 보정 전 위치, `velocity`는 초당 월드 좌표 속도다. `baseline`에서는 환경변수와 관계없이 적용하지 않는다.

트랙 쌍 유지는 `improved`에서 기본 활성화되며 `ENABLE_TRACK_PAIR_HOLD=false`로 이것만 끌 수 있다. 기존 카메라 간 트랙 쌍을 우선 유지하고, 새 상대의 비용이 기존 상대의 `TRACK_PAIR_IMPROVEMENT_RATIO` 배 이하인 상태가 `TRACK_PAIR_CONFIRM_FRAMES`번 연속되어야 교체를 허용한다. 기본값은 각각 `0.9`, `3`이다. 현재 상대와 도전자 연속 횟수는 `track_pair_states`에 저장된다.

세션이 처음 처리될 때 모든 실험 설정을 조건별 `session_settings`에 저장한다. `algorithm=baseline`은 epipolar, `algorithm=improved`는 ground-plane 매칭이다. `POST /sessions/{session_id}/recompute?profile=precise&algorithm=improved`는 최초 `basic + baseline` 요청의 원본 frame·bbox·foot을 대상 조건으로 다시 계산한다. 대상 조건의 기존 결과와 추적 상태는 교체된다.

`GET /health`의 `algorithms.baseline`과 `algorithms.improved`에서 각 알고리즘에 실제 적용되는 매칭, 칼만 필터, 트랙 쌍 유지, 발목 페어링 설정을 확인할 수 있다.

탐지 한 번으로 2×2 결과를 만들려면 다음 세 요청을 실행한다. 최초 결과까지 합쳐 `basic/ baseline`, `basic/improved`, `precise/baseline`, `precise/improved`가 된다.

```text
POST /sessions/{session_id}/recompute?profile=precise&algorithm=baseline
POST /sessions/{session_id}/recompute?profile=basic&algorithm=improved
POST /sessions/{session_id}/recompute?profile=precise&algorithm=improved
```

`GET /sessions/{session_id}/results.csv?profile=precise&algorithm=improved`로 조건별 결과를 받는다.

기능별 효과를 따로 재려면 `algorithm`에 기능 조합을 넣는다. `f-` 뒤에 기능 글자를 알파벳 순서로, 중복 없이 붙인다.

| 글자 | 기능 |
|---|---|
| `a` | 같은 쪽 발목끼리 삼각측량 |
| `g` | 바닥 위치로 짝짓기 (없으면 에피폴라) |
| `h` | 카메라 짝 유지 |
| `k` | 칼만 필터 |

예: `recompute?profile=basic&algorithm=f-g`(기존 + 바닥 짝짓기), `algorithm=f-gk`(기존 + 바닥 짝짓기 + 칼만). `baseline`은 기능 없음, `improved`는 서버 환경 변수로 켠 기능 전부다. 잘못된 이름(`f-gg`, `f-ga`, 모르는 글자)은 422로 거절한다. 결과 csv의 `settings.features`에 실제로 켠 기능이 남고, `/health`의 `feature_codes`에서 글자 목록을 확인할 수 있다. 두 query parameter의 기본값은 각각 `basic`, `baseline`이다.
위치 행에는 원본 묶음과 카메라 프레임을 추적할 수 있도록 `pair_id`, `frame_id`가 포함된다. 한 묶음의 위치 행은 대표 카메라의 `(camera_id, track_id)`를 기준으로 구분하므로, 잘못된 전역 `object_id` 충돌이 있더라도 서로 다른 사람의 행이 합쳐지지 않는다.

높이 범위는 환경변수로 바꿀 수 있다. 기본값은 `box`가 `BOX_FOOT_Z_MIN=-0.35`, `BOX_FOOT_Z_MAX=0.2`, `ankle`이 `ANKLE_FOOT_Z_MIN=-0.1`, `ANKLE_FOOT_Z_MAX=0.4`다.

응답의 `matches[].world`는 기본적으로 두 관측점의 삼각측량 월드 좌표다. 발목 쌍과 사람 bbox는 항상 삼각측량을 사용한다. `chair`, `suitcase`의 bbox만 `BBOX_POSITION_METHOD=triangulate|plane|weighted-plane`으로 비교할 수 있으며 기본값은 `triangulate`다. `plane`은 두 카메라 광선과 `Z=0m` 평면의 교점을 평균하고, `weighted-plane`은 멀거나 바닥과 평행에 가까운 광선의 가중치를 낮춘다. `observations`에는 실제 계산에 사용한 `foot_pixel`, `foot_src`가 들어가며, `unmatched`에는 매칭되지 않은 카메라별 track ID가 들어간다.

```json
{
  "bundle_id": 1,
  "session_id": "unity-classroom-01-run1",
  "pair_id": 42,
  "calibration_profile": "basic",
  "sync_delta_ms": 20,
  "status": "processed",
  "matches": [],
  "unmatched": {"cam1": [7], "cam2": [9]}
}
```

## 3. 정답 좌표 전송

엣지는 Unity 데이터 폴더에서 정답 좌표를 읽어 `POST /ground-truth`로 전송한다. `world`는 `[x, y, z]`이며 카메라별 정답 bbox가 없으면 `bbox`를 생략하거나 빈 객체로 보낼 수 있다.

```json
{
  "session_id": "unity-classroom-01-run1",
  "frame": 42,
  "ts": 1790866800000,
  "objects": [
    {
      "object_id": "person_1",
      "cls": "person",
      "world": [3.12, 4.05, 0],
      "bbox": {
        "cam1": [810, 298, 907, 612],
        "cam2": [400, 279, 482, 591]
      }
    }
  ]
}
```

같은 `(session_id, frame)`의 정답을 다시 전송하면 HTTP 409를 반환한다.
