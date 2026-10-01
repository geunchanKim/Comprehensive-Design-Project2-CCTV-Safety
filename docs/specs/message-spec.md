# 엣지·Unity·서버 메시지 양식

> 작성: 2026-10-02 · 트랙 A(엣지) 기준 초안. 바뀌면 이 문서부터 고친다.

## 1. 전체 흐름

| # | 보내는 쪽 → 받는 쪽 | 주소 | 내용 | 담당 |
|---|---|---|---|---|
| ① | Unity → 엣지 | `POST http://<엣지 IP>:8100/frames` | 같은 순간의 cam1·cam2 이미지 | 성윤 → 근찬 |
| ② | 엣지 → 서버 | `POST /detections` | 두 카메라 탐지 결과 묶음 | 근찬 → 해민 |
| ③ | 엣지 → 서버 | `PUT /cameras/{camera_id}/calibration` | 카메라 캘리브레이션 값 | 근찬 → 해민 |
| ④ | Unity → 서버 | `POST /ground-truth` | 물체의 정답 좌표 (Unity 실험만) | 성윤 → 해민 |

## 2. 공통 약속

| 항목 | 약속 |
|---|---|
| 월드 좌표 | 원점 = 방 바닥의 한 모서리, X = 가로, Y = 세로, Z = 위쪽, 단위 m |
| Unity 좌표 변환 | Unity는 Y가 위쪽인 왼손 좌표계 → **world = (unity.x, unity.z, unity.y)** |
| 이미지 좌표 | 픽셀, 원점 = 좌상단, x는 오른쪽, y는 아래쪽 |
| bbox | `[x1, y1, x2, y2]` 픽셀 절대좌표 (정규화 안 함) |
| 시간 `ts` | epoch ms. Unity는 렌더링 시각, 실제 카메라는 엣지 수신 시각 |
| 클래스 | `person`, `chair`, `cart`, `desk` |
| camera_id | `cam1`, `cam2` |
| session_id | 실험 단위 이름. 예: `unity-classroom-01`, `unity-diy-01`, `real-classroom-01` |

## 3. ① Unity → 엣지: `POST /frames`

`multipart/form-data` 한 요청에 **같은 Unity 프레임에서 렌더링한 두 카메라 이미지**를 같이 보낸다.

| 필드 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `meta` | JSON 문자열 | `{"session_id": "unity-classroom-01", "frame": 1532, "ts": 1790774606123}` | frame = Unity 프레임 번호 |
| `cam1` | JPEG 파일 | | 필드 이름 = camera_id |
| `cam2` | JPEG 파일 | | |

- 보내는 간격: 초당 약 10번
- 해상도: 1920×1080 (Tapo C200과 동일)
- 응답 예시: `{"ok": true, "pair_id": 1532, "counts": {"cam1": 3, "cam2": 2}, "ms": 41}`

## 4. ② 엣지 → 서버: `POST /detections`

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | |
| `pair_id` | int | 묶음 번호 (Unity 프레임 번호) |
| `frames` | array | 카메라별 결과, camera_id 순서 |
| `frames[].camera_id` | string | `cam1`, `cam2` |
| `frames[].frame_id` | int | 카메라별 프레임 번호 |
| `frames[].ts` | int | epoch ms |
| `frames[].image_size` | [int, int] | `[width, height]` |
| `frames[].detections` | array | 탐지 결과, 없으면 빈 배열 |
| `detections[].track_id` | int | **카메라별** 추적 번호 (cam1의 7과 cam2의 7은 다른 물체) |
| `detections[].cls` | string | 클래스 |
| `detections[].conf` | float | 0~1, 소수점 3자리 |
| `detections[].bbox` | [float ×4] | `[x1, y1, x2, y2]`, 소수점 1자리 |

```json
{
  "session_id": "unity-classroom-01",
  "pair_id": 1532,
  "frames": [
    {"camera_id": "cam1", "frame_id": 1532, "ts": 1790774606123, "image_size": [1920, 1080],
     "detections": [{"track_id": 7, "cls": "person", "conf": 0.91, "bbox": [812.4, 300.2, 905.1, 610.8]}]},
    {"camera_id": "cam2", "frame_id": 1532, "ts": 1790774606123, "image_size": [1920, 1080],
     "detections": [{"track_id": 3, "cls": "person", "conf": 0.88, "bbox": [402.0, 280.5, 480.7, 590.2]}]}
  ]
}
```

서버가 할 일 (참고)
- 두 카메라 사이의 같은 물체 짝짓기: 같은 클래스 + 에피폴라 거리 + 헝가리안 매칭
- 삼각측량할 점: bbox 하단 중심 `((x1+x2)/2, y2)`. 계산 전에 `K`, `dist`로 왜곡 보정
- 결과 Z가 0에서 크게 벗어나면 짝짓기나 캘리브레이션 오류로 표시
- 실제 카메라는 두 `ts` 차이가 50ms를 넘으면 표시 또는 제외 (Unity는 항상 같음)

## 5. ③ 엣지 → 서버: `PUT /cameras/{camera_id}/calibration`

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 설치가 바뀌면 다시 등록하므로 세션별로 저장 |
| `method` | string | `unity-gt` (Unity 정답) 또는 `charuco-aruco` (실제 추정) |
| `image_size` | [int, int] | 캘리브레이션한 해상도 |
| `K` | 3×3 | 내부 행렬 `[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]` |
| `dist` | [float ×5] | `[k1, k2, p1, p2, k3]`, Unity는 전부 0 |
| `rvec` | [float ×3] | 회전 벡터 (Rodrigues) |
| `tvec` | [float ×3] | 이동 벡터, 단위 m |
| `reproj_error_px` | float | 재투영 오차, Unity 정답이면 0 |

`rvec`, `tvec`은 **OpenCV 규약**이다: 월드 점 X를 카메라 좌표로 바꾸는 `X_cam = R·X + t` (R = Rodrigues(rvec)). 투영행렬은 `P = K [R | t]`.

```json
{
  "session_id": "unity-classroom-01",
  "method": "unity-gt",
  "image_size": [1920, 1080],
  "K": [[1246.6, 0, 960], [0, 1246.6, 540], [0, 0, 1]],
  "dist": [0, 0, 0, 0, 0],
  "rvec": [1.92, 0.31, -0.27],
  "tvec": [-0.85, 1.12, 3.40],
  "reproj_error_px": 0.0
}
```

## 6. ④ Unity → 서버: `POST /ground-truth`

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | |
| `frame` | int | ①의 Unity 프레임 번호와 같은 값 (pair_id와 연결) |
| `ts` | int | ①과 같은 값 |
| `objects[].object_id` | string | Unity 오브젝트 이름. 예: `person_1` |
| `objects[].cls` | string | 클래스 |
| `objects[].world` | [float ×3] | 발 위치(바닥 접점)의 월드 좌표, 2장 규칙대로 변환해서 보냄 |
| `objects[].bbox` | object | 카메라별 정답 bbox `{"cam1": [x1,y1,x2,y2], "cam2": [...]}`, 화면 밖이면 생략 |

```json
{
  "session_id": "unity-classroom-01",
  "frame": 1532,
  "ts": 1790774606123,
  "objects": [
    {"object_id": "person_1", "cls": "person", "world": [3.12, 4.05, 0.0],
     "bbox": {"cam1": [810.0, 298.0, 907.0, 612.0], "cam2": [400.0, 279.0, 482.0, 591.0]}}
  ]
}
```

정답 bbox까지 보내면 **탐지 없이 좌표 계산만** 검증할 수 있어서, 오차가 탐지 때문인지 좌표 계산 때문인지 나눠 볼 수 있다.

## 7. 정해야 할 것

| 항목 | 현재 안 |
|---|---|
| ③을 엣지가 보낼지, 캘리브레이션 결과 파일을 서버에 직접 올릴지 | 엣지가 API로 전송 |
| Unity 프레임 송출 간격 | 초당 10번 |
| 서버 응답에 월드 좌표를 돌려줄지 | 돌려줌 (엣지 화면 확인용) |