# 촬영 당일 캘리브레이션 실행표

## 촬영 전 확인

- ArUco ID 0: A4, 검은 영역 18cm
- ArUco ID 1~7: A3, 검은 영역 27cm
- 카메라 위치·줌·초점·해상도를 고정하고 이후 움직이지 않기
- 백엔드 확인: `GET /health`, `GET /health/db`
- `/health`의 `algorithms.baseline`, `algorithms.improved` 실제 설정 확인

## 1. 장소 캘리브레이션 파일 생성

```powershell
cd ai/calibration
python build_calibration.py --run ../../runs/real/<촬영폴더> `
  --points grid_points.json `
  --cam1-intrinsics results/cam1_intrinsics.json `
  --cam2-intrinsics results/cam2_intrinsics.json `
  --output output/<장소명>.json --best 10
```

생성된 `<장소명>.report.json`에서 precise 검증점별 cm 오차를 확인한다.

## 2. 세션 목록에 캘리브레이션 등록

```powershell
python register_calibration.py --calib output/<장소명>.json `
  --sessions sessions/<세션목록>.txt `
  --backend-url http://<연구실-IP>:<포트>
```

## 3. 네 실험 조건 생성

```powershell
python recompute_sessions.py --sessions sessions/<세션목록>.txt `
  --backend-url http://<연구실-IP>:<포트>
```

생성 조건: `basic/baseline`, `basic/improved`, `precise/baseline`, `precise/improved`.
각 스크립트 결과표에 실패가 없는지 확인하고, 실패 시 다음 단계로 넘어가지 않는다.

## 팀에 전달할 값

```text
백엔드 주소: http://<연구실-IP>:<포트>
상태 확인: http://<연구실-IP>:<포트>/health
DB 확인: http://<연구실-IP>:<포트>/health/db
```
