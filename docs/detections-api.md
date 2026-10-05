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
        {"track_id": 7, "cls": "person", "conf": 0.988, "bbox": [950, 400, 970, 540]}
      ]
    },
    {
      "camera_id": "cam2",
      "frame_id": 42,
      "ts": 1790866800020,
      "image_size": [1920, 1080],
      "detections": [
        {"track_id": 9, "cls": "person", "conf": 0.941, "bbox": [850, 400, 870, 540]}
      ]
    }
  ]
}
```

지원 클래스는 `person`, `chair`, `cart`, `desk`, `suitcase`, `backpack`이다. `bbox`는 좌상단 원점의 비정규화 픽셀 `[x1, y1, x2, y2]`다. `track_id`는 카메라 로컬 ID다.

엣지 추론 자체가 실패한 프레임은 전송하지 않는다. 정상적으로 추론했으나 탐지가 없을 때만 `detections: []`를 전송한다. 따라서 별도의 `analysis_status` 필드는 사용하지 않는다.

서버는 bbox 하단 중앙을 발 위치로 삼아 카메라별 왜곡을 보정하고, 같은 클래스끼리 에피폴라 오차를 계산한 후 헝가리안 알고리즘으로 1:1 연결한다. 기본 허용 오차는 50px이며 `MAX_EPIPOLAR_ERROR_PX`로 바꿀 수 있다. 연결된 로컬 track 쌍에는 세션 범위의 전역 `object_id`가 부여된다.

응답의 `matches[].world`가 월드 좌표이며 `observations`에는 두 카메라의 원본 탐지 필드와 계산에 사용한 `foot_pixel`이 들어간다. `unmatched`에는 매칭되지 않은 카메라별 track ID가 들어간다.

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
