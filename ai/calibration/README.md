# CCTV 카메라 캘리브레이션

이 도구는 `CCTV-Safety-backend`의 `PUT /cameras/{camera_id}/calibration` 입력 형식에 맞는
`cam1.json`, `cam2.json`을 만든다. 길이 단위는 미터이며, 개별 ArUco 마커의
검은 정사각형 영역은 **18cm × 18cm**이다.

## 1. 보드와 마커 생성

```powershell
python generate_charuco_board.py
python generate_aruco_markers.py
```

인쇄 시 반드시 `실제 크기(100%)`를 선택한다. 인쇄 후 ArUco의 검은 영역이
180mm인지 자로 확인한다. 페이지 맞춤이나 여백 맞춤을 사용하면 좌표 스케일이 틀어진다.

## 2. 카메라별 내부 파라미터 계산

카메라 해상도를 실제 추론 해상도(기본 1920×1080)로 고정하고, 보드의 거리와
기울기 및 화면 내 위치를 바꾸어 10장 이상 촬영한다.

```powershell
python capture_charuco.py --camera-id cam1
python calibrate_camera.py --camera-id cam1 --images captures/cam1
python capture_charuco.py --camera-id cam2
python calibrate_camera.py --camera-id cam2 --images captures/cam2
```

결과는 각각 `output/cam1_intrinsics.json`, `output/cam2_intrinsics.json`에 저장된다.

## 3. 공통 월드 좌표계의 rvec, tvec 계산

ID 0 마커를 두 카메라가 모두 볼 수 있는 바닥에 고정한다. 두 카메라의 촬영 사이에
마커를 움직이면 안 된다. 마커 중심이 월드 원점이며 마커 평면이 `Z=0`이다.
각 카메라에서 같은 고정 마커 사진을 3장 이상 저장한 뒤 실행한다.

```powershell
python capture_images.py --camera-id cam1 --marker-id 0
python capture_images.py --camera-id cam2 --marker-id 0
python detect_aruco.py --camera-id cam1 --session-id cctv-classroom-01-run1 --intrinsics output/cam1_intrinsics.json --images captures/aruco/cam1
python detect_aruco.py --camera-id cam2 --session-id cctv-classroom-01-run1 --intrinsics output/cam2_intrinsics.json --images captures/aruco/cam2
```

생성된 JSON은 백엔드가 요구하는 `session_id`, `method`, `image_size`, `K`, `dist`,
`rvec`, `tvec`, `reproj_error_px`를 포함한다. `method`는 `charuco-aruco`이며,
외부 파라미터는 백엔드와 같은 `X_camera = R @ X_world + t` 규약이다.

백엔드가 실행 중이면 생성과 등록을 한 번에 할 수 있다.

```powershell
python detect_aruco.py --camera-id cam1 --session-id cctv-classroom-01-run1 --intrinsics output/cam1_intrinsics.json --images captures/aruco/cam1 --backend-url http://localhost:8000
python detect_aruco.py --camera-id cam2 --session-id cctv-classroom-01-run1 --intrinsics output/cam2_intrinsics.json --images captures/aruco/cam2 --backend-url http://localhost:8000
```

두 카메라의 JSON은 반드시 같은 위치와 방향으로 고정된 기준 마커에서 계산해야 한다.
카메라 또는 마커를 움직였다면 두 카메라 모두 다시 외부 캘리브레이션한다.

## 4. 권장 방식: 다점 ArUco 격자 PnP와 독립 검증

단일 마커 자세는 원거리 오차가 커질 수 있으므로 실제 실험에서는 이 방식을 사용한다.
ID 0~5는 화면 전체에 퍼진 바닥 계산점, ID 6은 계산에 쓰지 않는 원거리 바닥 검증점,
ID 7은 계산에 쓰지 않는 다른 높이 검증점으로 배치한다. 모든 좌표 단위는 미터다.

`grid_points.template.json`을 복사해 각 마커 **중심**의 실측 월드 좌표를 기록한다.
ID 0 중심을 `(0, 0, 0)`으로 두는 것을 권장하며 두 카메라에 같은 좌표 파일을 사용한다.

```powershell
Copy-Item grid_points.template.json grid_points.json
python capture_grid.py --camera-id cam1 --camera-ip <CAM1_IP>
python capture_grid.py --camera-id cam2 --camera-ip <CAM2_IP>
```

각 카메라에서 마커들이 선명한 프레임을 5~10장 저장한다. 카메라·마커·줌·초점을
촬영 사이에 움직이지 않는다. 그다음 내부 파라미터와 같은 해상도인지 검사하면서 계산한다.

```powershell
python calibrate_grid.py --camera-id cam1 --session-id <SESSION_ID> --intrinsics results/cam1_intrinsics.json --images captures/grid/cam1 --points grid_points.json
python calibrate_grid.py --camera-id cam2 --session-id <SESSION_ID> --intrinsics results/cam2_intrinsics.json --images captures/grid/cam2 --points grid_points.json
```

결과는 `output/cam1_precise.json`, `output/cam2_precise.json`이며 백엔드의 `precise`
프로필에 바로 등록할 수 있다. 같은 이름의 `.report.json`에는 마커별 검출 횟수·중심 픽셀,
검증점별 추정 좌표와 cm 오차가 저장된다. 실행기는 다음 조건을 만족하지 않으면 중단한다.

- PnP 계산점 6개 이상, 한 직선 배치 금지
- 이미지 너비와 높이 각각 25% 이상 분포
- 계산에 쓰지 않은 검증점 2개 이상
- 검증점 중 최소 1개는 계산점과 다른 높이
- 검증점 중 최소 1개는 모든 계산점보다 카메라에서 먼 위치

백엔드 실행 중이면 명령 끝에 `--backend-url http://localhost:8000`을 추가해 계산과 등록을
한 번에 수행할 수 있다. 기존 단일 마커 방식은 빠른 설치 확인용 보조 수단으로만 사용한다.
