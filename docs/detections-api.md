# Detection and triangulation API

FastAPI의 `/docs`에서 동일한 명세를 대화형으로 확인할 수 있다. 서버 시작 전 `alembic upgrade head`로 테이블을 생성한다.

## 세션 규칙

`session_id`는 한 번의 실험 실행을 식별한다. 같은 Unity 데이터를 다시 실행해 결과를 비교할 때는 `unity-classroom-01-run2`처럼 새로운 `session_id`를 사용한다. 카메라 캘리브레이션, 전역 객체 ID, detection bundle, ground truth가 모두 세션 단위로 저장되므로 새 세션에서는 캘리브레이션도 다시 등록해야 한다.

한 세션에서 `pair_id`는 프레임 묶음마다 고유해야 한다. 이미 저장된 `(session_id, pair_id)`를 다시 전송하면 HTTP 409를 반환한다.

## 1. 카메라 캘리브레이션 등록

`PUT /cameras/{camera_id}/calibration`에 카메라별 내부 행렬 `K`, 왜곡 계수 `dist`, 회전 벡터 `rvec`, 이동 벡터 `tvec`를 등록한다. `rvec`와 `tvec`는 월드 좌표를 카메라 좌표로 변환하는 OpenCV 외부 파라미터이며, `image_size`는 `[width, height]`다.

```json
{
  "session_id": "unity-classroom-01-run1",
  "method": "unity-gt",
  "image_size": [1920, 1080],
  "K": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
  "dist": [0, 0, 0, 0, 0],
  "rvec": [0, 0, 0],
  "tvec": [0, 0, 0],
  "reproj_error_px": 0
}
```

`method`는 `unity-gt` 또는 `charuco-aruco`를 사용한다. 동일한 `(session_id, camera_id)`로 다시 요청하면 해당 캘리브레이션을 갱신한다.

## 2. 프레임 묶음 전송

`POST /detections`는 최상위에 `session_id`, `pair_id`와 서로 다른 카메라의 프레임을 정확히 2개 받는다. `ts`는 epoch millisecond이며 두 프레임의 차이가 50ms를 초과하면 HTTP 422를 반환한다. 임계값은 `MAX_SYNC_DELTA_MS` 환경변수로 바꿀 수 있다.

```json
{
  "session_id": "unity-classroom-01-run1",
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

엣지 추론 자체가 실패한 프레임은 전송하지 않는다. 정상적으로 추론했으나 탐지가 없을 때만 `detections: []`를 전송한다. 따라서 별도의 `analysis_status` 필드는 사용하지 않는다.

서버는 사람을 두 단계로 연결한다. 먼저 양쪽 카메라에서 모두 발목 좌표가 있는 사람끼리 연결하고, 남은 사람은 양쪽 모두 bbox 하단 중앙으로 다시 계산해 연결한다. 화면 좌우 끝에서 잘린 bbox는 반대 카메라의 bbox 폭과 깊이 비율로 원래 중심을 복원한다. 그 밖의 클래스는 bbox 하단 중앙을 사용한다.

각 단계는 에피폴라 오차, 삼각측량 높이, 두 카메라 앞쪽 여부를 헝가리안 알고리즘 실행 전에 검사한다. 기본 에피폴라 허용 오차는 50px이며 `MAX_EPIPOLAR_ERROR_PX`로 바꿀 수 있다. 연결된 로컬 track 쌍에는 세션 범위의 전역 `object_id`가 부여된다.

개선 알고리즘은 `MATCHING_METHOD=ground-plane`으로 켠다. 이 모드에서는 각 카메라 광선과 기준 평면의 교점을 구하고 두 교점의 XY 거리로 헝가리안 매칭한다. 발목은 `Z=0.1m`, bbox는 `Z=0m` 평면을 사용하며 기본 거리 기준은 `MAX_GROUND_DISTANCE_M=1.0`이다. 기본 `MATCHING_METHOD=epipolar`은 기존 방법 비교를 위해 유지한다. 응답의 `matching_method`와 `ground_distance_m`으로 실제 적용 방식을 확인할 수 있다.

`ENABLE_KALMAN_FILTER=true`로 설정하면 객체별 `[x, y, z, vx, vy, vz]` 상태를 DB에 저장하고 다음 프레임에서 이어서 보정한다. 이때 `world`는 보정 위치, `raw_world`는 보정 전 위치, `velocity`는 초당 월드 좌표 속도다. 기본값은 `false`로 기존 방법의 출력에 영향을 주지 않는다.

`ENABLE_TRACK_PAIR_HOLD=true`로 설정하면 기존 카메라 간 트랙 쌍을 우선 유지한다. 새 상대의 비용이 기존 상대의 `TRACK_PAIR_IMPROVEMENT_RATIO` 배 이하인 상태가 `TRACK_PAIR_CONFIRM_FRAMES`번 연속되어야 교체를 허용한다. 기본값은 각각 `0.9`, `3`이며 기능 자체의 기본값은 `false`다. 현재 상대와 도전자 연속 횟수는 `track_pair_states`에 저장된다.

높이 범위는 환경변수로 바꿀 수 있다. 기본값은 `box`가 `BOX_FOOT_Z_MIN=-0.35`, `BOX_FOOT_Z_MAX=0.2`, `ankle`이 `ANKLE_FOOT_Z_MIN=-0.1`, `ANKLE_FOOT_Z_MAX=0.4`다.

응답의 `matches[].world`는 기본적으로 두 관측점의 삼각측량 월드 좌표다. Unity S1~S4 검증에서 발목 삼각측량이 고정 높이 평면보다 정확했으므로 발목 쌍은 항상 삼각측량을 사용한다. bbox 쌍은 `BBOX_POSITION_METHOD=triangulate|plane|weighted-plane`으로 비교할 수 있으며 기본값은 `triangulate`다. `plane`은 두 카메라 광선과 `Z=0m` 평면의 교점을 평균하고, `weighted-plane`은 멀거나 바닥과 평행에 가까운 광선의 가중치를 낮춘다. `observations`에는 실제 계산에 사용한 `foot_pixel`, `foot_src`가 들어가며, `unmatched`에는 매칭되지 않은 카메라별 track ID가 들어간다.

```json
{
  "bundle_id": 1,
  "session_id": "unity-classroom-01-run1",
  "pair_id": 42,
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
