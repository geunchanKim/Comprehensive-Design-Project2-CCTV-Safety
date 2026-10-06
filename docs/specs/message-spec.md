# 엣지·Unity·서버 메시지 양식

> 작성: 2026-10-02 · 수정: 2026-10-05 (foot 필드, 높이 검사 제안, 클래스 추가 예정)
> 트랙 A(엣지) 기준. 바뀌면 이 문서부터 고친다.

## 1. 전체 흐름

```
Unity ──(폴더 저장)──▶ 엣지 ──① PUT 캘리브레이션 ──▶ 서버
                         ├──② POST /detections ──▶
                         └──③ POST /ground-truth ─▶
```

| # | 보내는 쪽 → 받는 쪽 | 주소 | 내용 | 담당 |
|---|---|---|---|---|
| ⓪ | Unity → 엣지 | 폴더 (`ai/runs/unity/<이름>/`) | 두 카메라 이미지, 정답 좌표, 카메라 설정 | 성윤 → 근찬 |
| ① | 엣지 → 서버 | `PUT /cameras/{camera_id}/calibration` | 이번 run의 cam1·cam2 캘리브레이션 (탐지보다 **먼저**) | 근찬 → 해민 |
| ② | 엣지 → 서버 | `POST /detections` | 두 카메라 탐지 결과 묶음 | 근찬 → 해민 |
| ③ | 엣지 → 서버 | `POST /ground-truth` | 물체의 정답 좌표 (Unity 실험만) | 근찬 → 해민 |

- Unity는 서버로 직접 보내지 않는다. 엣지가 폴더를 읽어 ①②③을 모두 보낸다.
- 실제 카메라 실험은 ⓪ 대신 카메라 영상을 쓰고, ①은 백엔드가 ChArUco·ArUco로 계산해 직접 등록한다 (엣지는 `--calib none`).

## 2. 공통 약속

| 항목 | 약속 |
|---|---|
| 월드 좌표 | 원점 = 방 바닥의 한 모서리, X = 가로, Y = 세로, Z = 위쪽, 단위 m |
| Unity 좌표 변환 | Unity는 Y가 위쪽인 왼손 좌표계 → **world = (unity.x, unity.z, unity.y)**. 변환은 엣지에서만 한다 |
| 같은 지도 | 정답 좌표(③)와 캘리브레이션 rvec·tvec(①)은 **같은 월드 좌표계**를 쓴다 |
| 이미지 좌표 | 픽셀, 원점 = 좌상단, x는 오른쪽, y는 아래쪽 |
| bbox | `[x1, y1, x2, y2]` 픽셀 절대좌표 (정규화 안 함) |
| 시간 `ts` | epoch ms. Unity는 시뮬레이션 시각(시작 + frame × 100ms), 실제 카메라는 엣지 수신 시각 |
| 클래스 | 서버 지원: `person`, `chair`, `cart`, `desk`, `suitcase`(카트 대신), `backpack`(통로 적치물) |
| camera_id | `cam1`, `cam2` |
| session_id | 폴더 이름 + `-runN`. 실행할 때마다 N이 1씩 늘어난다. 예: `unity-classroom-01-run3` |

## 3. ⓪ Unity → 엣지: 폴더

시나리오 1회 재생 = 폴더 1개. 자세한 요구사항은 Unity 요청 이슈(`[REQ] Unity 시뮬레이션 데이터 출력 형식`) 참고.

```
ai/runs/unity/unity-classroom-01/
├── cam1/000001.jpg ...    1920×1080 JPG, 초당 10프레임
├── cam2/000001.jpg ...    cam1과 같은 번호 = 같은 Unity 프레임
├── frames.jsonl           한 줄 = 한 프레임 {"frame", "ts", "objects": [...]}
└── cameras.json           두 카메라 설정 (Unity 원본 값 그대로)
```

| 파일 | 핵심 필드 |
|---|---|
| `cameras.json` | `camera_id`, `image_size`, `vertical_fov_deg`, `position`, `rotation_quat [x,y,z,w]` |
| `frames.jsonl` | `objects[].object_id`, `cls`, `world` (바닥 접점, Unity 좌표 그대로), `bbox` (카메라별, y는 위에서 아래) |

## 4. ① 엣지 → 서버: `PUT /cameras/{camera_id}/calibration`

캘리브레이션은 **session_id별로** 저장된다. 새 run을 시작하면 그 session_id로 cam1, cam2를 먼저 등록하고, 하나라도 실패하면 탐지를 보내지 않는다. 등록하지 않고 탐지를 보내면 404가 난다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 이번 run의 session_id |
| `method` | string | `unity-gt` (Unity 정답) 또는 `charuco-aruco` (실제 추정) |
| `image_size` | [int, int] | 캘리브레이션한 해상도. 탐지의 `image_size`와 같아야 함 |
| `K` | 3×3 | 내부 행렬 `[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]` |
| `dist` | [float ×5] | `[k1, k2, p1, p2, k3]`, Unity는 전부 0 |
| `rvec` | [float ×3] | 회전 벡터 (Rodrigues) |
| `tvec` | [float ×3] | 이동 벡터, 단위 m |
| `reproj_error_px` | float | 재투영 오차, Unity 정답이면 0 |

`rvec`, `tvec`은 **OpenCV 규약**이다: 월드 점 X를 카메라 좌표로 바꾸는 `X_cam = R·X + t` (R = Rodrigues(rvec)). 투영행렬은 `P = K [R | t]`.

Unity 값 계산 (`ai/edge/unity_calibration.py`)
- `fx = fy = (H/2) / tan(세로화각/2)`, `cx = W/2`, `cy = H/2`
- `R = F · R_unityᵀ · S`, `t = -R · (S · 카메라 위치)`
  - `S`: Unity ↔ 월드 (y, z 맞바꾸기), `F`: Unity 카메라 y위 → OpenCV y아래
- 검증: 정답 좌표 투영 → 삼각측량 왕복 오차 0mm (unity-classroom-01 샘플)

```json
{
  "session_id": "unity-classroom-01-run1",
  "method": "unity-gt",
  "image_size": [1920, 1080],
  "K": [[1247.866373, 0, 960], [0, 1247.866373, 540], [0, 0, 1]],
  "dist": [0, 0, 0, 0, 0],
  "rvec": [1.85068607, -0.89038869, 0.56736235],
  "tvec": [0.04712309, 1.99086126, 0.46287241],
  "reproj_error_px": 0.0
}
```

## 5. ② 엣지 → 서버: `POST /detections`

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | |
| `pair_id` | int | 묶음 번호 = Unity `frame` |
| `frames` | array | 카메라별 결과, 정확히 2개 (cam1, cam2) |
| `frames[].camera_id` | string | `cam1`, `cam2` |
| `frames[].frame_id` | int | Unity `frame` |
| `frames[].ts` | int | `frames.jsonl`의 ts. 두 카메라 차이 50ms 이하 |
| `frames[].image_size` | [int, int] | `[width, height]` |
| `frames[].detections` | array | 탐지 결과, 없으면 빈 배열 `[]` |
| `detections[].track_id` | int | **카메라별** 추적 번호, 0 이상 (cam1의 1과 cam2의 1은 다른 물체) |
| `detections[].cls` | string | 클래스 |
| `detections[].conf` | float | 0~1 |
| `detections[].bbox` | [float ×4] | `[x1, y1, x2, y2]`, 이미지 안, 폭·높이 > 0 |
| `detections[].foot` | [float ×2] | (선택) 좌표 계산에 쓸 발 위치 `[x, y]` 픽셀, 이미지 안 |
| `detections[].foot_src` | string | (선택) `ankle`: 두 발목 가운데 / `box`: 박스 아래 가운데 |

`foot` 정의 (엣지 `--foot ankle`)
- 사람: 포즈 모델(yolo11n-pose)의 두 발목(COCO 키포인트 15, 16) 신뢰도가 모두 0.5 이상이면 두 발목 가운데
- 발목이 안 보이거나 사람이 아니면: 박스 아래 가운데 `((x1+x2)/2, y2)`
- 두 발목 가운데는 바닥에서 약 15cm 위 (Unity 측정 7~25cm)
- Unity S1~S3 정답 비교: 위치 오차 평균 15.8cm(박스) → 5.8cm(발목)

엣지 전송 규칙
- 추론 실패(이미지 누락·손상, 모델 오류) 묶음은 보내지 않는다
- track_id가 아직 없는 탐지(처음 잡힌 순간)는 뺀다
- bbox, foot은 이미지 범위로 자르고, 1px 미만 박스는 뺀다
- 서버가 받는 클래스만 보낸다 (모르는 클래스가 하나라도 있으면 묶음 전체가 422)
- 같은 `(session_id, pair_id)`를 다시 보내면 409

```json
{
  "session_id": "unity-classroom-01-run1",
  "pair_id": 3,
  "frames": [
    {"camera_id": "cam1", "frame_id": 3, "ts": 1790900000300, "image_size": [1920, 1080],
     "detections": [{"track_id": 1, "cls": "person", "conf": 0.93, "bbox": [807.0, 47.0, 1026.0, 688.0],
                     "foot": [921.5, 676.0], "foot_src": "ankle"}]},
    {"camera_id": "cam2", "frame_id": 3, "ts": 1790900000300, "image_size": [1920, 1080],
     "detections": [{"track_id": 1, "cls": "person", "conf": 0.57, "bbox": [372.0, 10.0, 452.0, 331.0],
                     "foot": [412.0, 331.0], "foot_src": "box"}]}
  ]
}
```

서버가 할 일 (참고)
- 사람 짝짓기: 1차는 양쪽 발목끼리, 2차는 남은 사람의 양쪽 bbox 아래 가운데끼리 수행. `K`·`dist`로 왜곡 보정
- 화면 좌우 끝에서 잘린 bbox는 반대 카메라 bbox 폭을 깊이 비율로 환산해 중심 복원
- 두 카메라 사이 짝짓기: 같은 클래스 + 에피폴라 거리 + 높이(z) + 두 카메라 앞쪽 여부를 먼저 검사한 뒤 헝가리안 매칭
- 에피폴라 거리 기준 `MAX_EPIPOLAR_ERROR_PX`: 현재 50px
- 개선 매칭: `MATCHING_METHOD=ground-plane`이면 평면 교점 사이 XY 거리를 비용으로 사용 (`MAX_GROUND_DISTANCE_M`, 기본 1m)
- 높이 검사: 삼각측량 z가 범위를 벗어나는 쌍은 짝짓기에서 제외 (박스 아래: -35~20cm, 발목: -10~40cm)
  - S2(2명)에서 두 사람을 바꿔 짝지은 22건은 모두 z가 30cm 이상, 정상 매칭은 -8~8cm
- 발목 쌍의 최종 위치는 삼각측량 사용. bbox 쌍은 `BBOX_POSITION_METHOD`로 삼각측량(기본)과 Z=0cm 평면 교점 평균을 비교

## 6. ③ 엣지 → 서버: `POST /ground-truth`

엣지가 `frames.jsonl`을 읽어 **좌표를 월드로 변환한 뒤** 보낸다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | ②와 같은 session_id |
| `frame` | int | ②의 pair_id와 같은 값 |
| `ts` | int | ②와 같은 값 |
| `objects[].object_id` | string | Unity 오브젝트 이름. 예: `person_1` |
| `objects[].cls` | string | 클래스 |
| `objects[].world` | [float ×3] | 바닥 접점의 월드 좌표 (2장 규칙대로 변환) |
| `objects[].bbox` | object | 카메라별 정답 bbox `{"cam1": [...], "cam2": [...]}`, 화면 밖이면 생략 |

```json
{
  "session_id": "unity-classroom-01-run1",
  "frame": 1,
  "ts": 1790900000100,
  "objects": [
    {"object_id": "person_1", "cls": "person", "world": [2.8, 2.2, 0.0],
     "bbox": {"cam1": [717.2, 39.8, 1198.2, 877.3], "cam2": [262.1, 0.0, 517.2, 399.8]}}
  ]
}
```

- 같은 `(session_id, frame)`를 다시 보내면 409
- 정답 bbox로 탐지 오차를, 정답 좌표로 3D 오차를 나눠 측정한다

## 7. 결정된 것 / 정해야 할 것

| 항목 | 상태 |
|---|---|
| Unity → 엣지 전달 방식 | ✅ 폴더 (엣지가 읽음) |
| GT 전송 주체 | ✅ 엣지 (Unity 원본 값을 엣지가 변환) |
| Unity 캘리브레이션 등록 | ✅ 엣지가 run마다 등록 (`--calib auto`) |
| 실제 카메라 캘리브레이션 등록 | ✅ 백엔드 (ChArUco·ArUco) |
| 사람 정답 bbox | ✅ Unity에서 메시 꼭짓점 기준으로 수정 |
| 엣지 탐지 모델 | ✅ COCO 원본 (사람 64 → 97%, 의자 오차 85 → 4cm) |
| 발 위치 `foot` | ✅ 엣지 전송 및 서버 저장·삼각측량 지원 |
| 에피폴라 기준 + 높이 검사 | ✅ 50px + `foot_src`별 z 범위 검사 |
| `suitcase`, `backpack` 클래스 | ✅ 서버 `ObjectClass` 지원 |
