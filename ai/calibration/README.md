# CCTV 카메라 캘리브레이션

이 도구는 `CCTV-Safety-backend`의 `PUT /cameras/{camera_id}` 입력 형식에 맞는
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

## 3. 공통 월드 좌표계의 R, t 계산

ID 0 마커를 두 카메라가 모두 볼 수 있는 바닥에 고정한다. 두 카메라의 촬영 사이에
마커를 움직이면 안 된다. 마커 중심이 월드 원점이며 마커 평면이 `Z=0`이다.
각 카메라에서 같은 고정 마커 사진을 3장 이상 저장한 뒤 실행한다.

```powershell
python capture_images.py --camera-id cam1 --marker-id 0
python capture_images.py --camera-id cam2 --marker-id 0
python detect_aruco.py --camera-id cam1 --intrinsics output/cam1_intrinsics.json --images captures/aruco/cam1
python detect_aruco.py --camera-id cam2 --intrinsics output/cam2_intrinsics.json --images captures/aruco/cam2
```

생성된 JSON은 백엔드가 요구하는 `camera_id`, `image_size`, `K`, `dist`, `R`, `t`만
포함한다. 외부 파라미터는 백엔드와 같은 `X_camera = R @ X_world + t` 규약이다.

백엔드가 실행 중이면 생성과 등록을 한 번에 할 수 있다.

```powershell
python detect_aruco.py --camera-id cam1 --intrinsics output/cam1_intrinsics.json --images captures/aruco/cam1 --backend-url http://localhost:8000
python detect_aruco.py --camera-id cam2 --intrinsics output/cam2_intrinsics.json --images captures/aruco/cam2 --backend-url http://localhost:8000
```

두 카메라의 JSON은 반드시 같은 위치와 방향으로 고정된 기준 마커에서 계산해야 한다.
카메라 또는 마커를 움직였다면 두 카메라 모두 다시 외부 캘리브레이션한다.
