# Detection and triangulation API

FastAPI의 `/docs`에서 동일한 명세를 대화형으로 확인할 수 있다. 서버 시작 전 `alembic upgrade head`로 테이블을 생성한다.

## 1. 카메라 캘리브레이션 등록

`PUT /cameras/{camera_id}`에 카메라별 내부 행렬 `K`, 왜곡 계수 `dist`, 월드 좌표에서 카메라 좌표로 변환하는 외부 파라미터 `R`, `t`를 등록한다. `image_size`는 `[width, height]`이며 기본값은 `[1920, 1080]`이다.

```json
{
  "camera_id": "cam1",
  "image_size": [1920, 1080],
  "K": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
  "dist": [0, 0, 0, 0, 0],
  "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "t": [0, 0, 0]
}
```

## 2. 프레임 묶음 전송

`POST /detections`는 서로 다른 카메라의 프레임을 정확히 2개 받는다. `ts`는 엣지가 프레임을 받은 epoch millisecond이며 차이가 50ms를 초과하면 HTTP 422를 반환한다. 임계값은 `MAX_SYNC_DELTA_MS` 환경변수로 바꿀 수 있다.

```json
{
  "frames": [
    {
      "camera_id": "cam1", "frame_id": 42, "ts": 1790866800000,
      "image_size": [1920, 1080],
      "detections": [
        {"track_id": 7, "cls": "person", "conf": 0.988, "bbox": [950, 400, 970, 540]}
      ]
    },
    {
      "camera_id": "cam2", "frame_id": 42, "ts": 1790866800020,
      "image_size": [1920, 1080],
      "detections": [
        {"track_id": 9, "cls": "person", "conf": 0.941, "bbox": [850, 400, 870, 540]}
      ]
    }
  ]
}
```

지원 클래스는 `person`, `chair`, `cart`, `desk`다. `bbox`는 좌상단 원점의 비정규화 픽셀 `[x1,y1,x2,y2]`다. `track_id`는 카메라 로컬 ID이며 카트·책상에 `+10000`을 적용하는 정책은 엣지가 담당한다.

서버는 bbox 하단 중앙을 발 위치로 삼아 카메라별 왜곡을 보정하고, 같은 클래스끼리 에피폴라 오차를 계산한 후 헝가리안 알고리즘으로 1:1 연결한다. 기본 허용 오차는 5px이며 `MAX_EPIPOLAR_ERROR_PX`로 바꿀 수 있다. 연결된 로컬 track 쌍에는 지속적인 전역 `object_id`가 부여된다.

응답의 `matches[].world`가 월드 좌표이며 `observations`에는 두 카메라의 원본 탐지 필드와 계산에 사용한 `foot_pixel`이 들어간다. 월드 좌표계를 바닥이 `Z=0`이 되도록 캘리브레이션했다면 정상적인 발 위치의 `z`도 0에 가까워야 한다. `unmatched`에는 매칭되지 않은 카메라별 track ID가 들어간다.
