"""
Unity cameras.json → 서버용 캘리브레이션 (method: unity-gt)

Unity 카메라는 렌즈 왜곡이 없고 위치·방향을 정확히 알기 때문에,
체커보드 촬영 없이 cameras.json 값만으로 캘리브레이션 정답을 계산할 수 있다.

만드는 값 (OpenCV 규칙, 서버 PUT /cameras/{camera_id}/calibration 형식)
  K     3x3  fx = fy = (H/2) / tan(세로화각/2), cx = W/2, cy = H/2
  dist  [0, 0, 0, 0, 0]
  rvec, tvec   X_cam = R · X_world + t  (R = Rodrigues(rvec))

좌표계 (정답 좌표와 반드시 같은 지도)
  월드 = unity_reader.unity_to_world 와 같은 규칙: Unity (x, y=위, z) → 월드 (x, z, y)
  OpenCV 카메라 = x 오른쪽, y 아래, z 앞 / Unity 카메라 = x 오른쪽, y 위, z 앞
  → R = F · R_unity^T · S,  t = -R · (S · 카메라 위치)
     S: y·z 맞바꾸기, F: y 뒤집기

자체 검증 (--check)
  frames.jsonl 정답 좌표를 두 카메라로 투영 → 다시 삼각측량 → 원래 좌표와 비교 (오차 ≈ 0 이어야 함)
  정답 bbox 아래 가운데와 투영점의 거리도 보여준다 (bbox가 대충 맞는지 확인용)

실행 (ai/ 폴더에서)
  python edge/unity_calibration.py runs/unity/unity-classroom-01 --check
  → <폴더>/calibration.json 저장
"""

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

S = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=float)   # Unity ↔ 월드 (y, z 맞바꾸기)
F = np.diag([1.0, -1.0, 1.0])                                   # Unity 카메라 y위 → OpenCV y아래


def unity_to_world(p):
    """unity_reader.unity_to_world 와 같은 규칙"""
    x, y, z = p
    return [float(x), float(z), float(y)]


def quat_to_matrix(q):
    """Unity rotation_quat [x, y, z, w] → 3x3 회전 행렬 (카메라 → Unity 월드)"""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def camera_calibration(cam: dict, session_id: str | None = None) -> dict:
    """cameras.json 의 카메라 하나 → 서버 캘리브레이션 payload"""
    w, h = cam["image_size"]
    f = (h / 2) / math.tan(math.radians(cam["vertical_fov_deg"]) / 2)
    K = [[f, 0.0, w / 2], [0.0, f, h / 2], [0.0, 0.0, 1.0]]

    R = F @ quat_to_matrix(cam["rotation_quat"]).T @ S
    t = -R @ (S @ np.array(cam["position"], dtype=float))
    rvec, _ = cv2.Rodrigues(R)

    payload = {
        "camera_id": cam["camera_id"],
        "method": "unity-gt",
        "image_size": [int(w), int(h)],
        "K": [[round(v, 6) for v in row] for row in K],
        "dist": [0.0, 0.0, 0.0, 0.0, 0.0],
        "rvec": [round(float(v), 8) for v in rvec.ravel()],
        "tvec": [round(float(v), 8) for v in t.ravel()],
        "reproj_error_px": 0.0,
    }
    if session_id:
        payload["session_id"] = session_id
    return payload


def load_calibrations(folder: Path, session_id: str | None = None) -> dict:
    """폴더의 cameras.json → {camera_id: payload}"""
    data = json.loads((folder / "cameras.json").read_text(encoding="utf-8"))
    return {c["camera_id"]: camera_calibration(c, session_id) for c in data["cameras"]}


def projection(c: dict):
    K = np.array(c["K"])
    R, _ = cv2.Rodrigues(np.array(c["rvec"]))
    return K @ np.hstack([R, np.array(c["tvec"]).reshape(3, 1)])


def project(P, X):
    x = P @ np.append(X, 1.0)
    return x[:2] / x[2], x[2]          # 픽셀, 깊이(카메라 앞이면 +)


def check(folder: Path, calibs: dict):
    """정답 좌표 → 투영 → 삼각측량 왕복 오차, 정답 bbox 아래 가운데와의 거리"""
    cams = list(calibs)[:2]
    P = {c: projection(calibs[c]) for c in cams}
    rows = [json.loads(l) for l in (folder / "frames.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    worst_tri, bbox_gaps = 0.0, []
    for row in rows:
        for o in row["objects"]:
            X = np.array(unity_to_world(o["world"]))
            pts, ok = {}, True
            for c in cams:
                uv, depth = project(P[c], X)
                pts[c] = uv
                ok &= depth > 0
                bb = o.get("bbox", {}).get(c)
                if bb and depth > 0:
                    foot = np.array([(bb[0] + bb[2]) / 2, bb[3]])
                    bbox_gaps.append((row["frame"], o["object_id"], c, uv, foot, float(np.linalg.norm(uv - foot))))
            if not ok:
                print(f"  [주의] frame {row['frame']} {o['object_id']}: 카메라 뒤쪽에 있음")
                continue
            Xh = cv2.triangulatePoints(P[cams[0]], P[cams[1]],
                                       pts[cams[0]].reshape(2, 1), pts[cams[1]].reshape(2, 1))
            Xt = (Xh[:3] / Xh[3]).ravel()
            worst_tri = max(worst_tri, float(np.linalg.norm(Xt - X)))

    print(f"삼각측량 왕복 오차 (최대): {worst_tri * 1000:.4f} mm  → {'통과' if worst_tri < 1e-4 else '실패'}")
    if bbox_gaps:
        print("\n정답 bbox 아래 가운데 vs 정답 좌표 투영점 (frame 1, 물체별)")
        print(f"  {'물체':<10} {'카메라':<6} {'투영점':>18} {'bbox 아래 가운데':>20} {'거리px':>8}")
        for fr, oid, c, uv, foot, d in bbox_gaps:
            if fr == rows[0]["frame"]:
                print(f"  {oid:<10} {c:<6} ({uv[0]:7.1f}, {uv[1]:7.1f}) ({foot[0]:7.1f}, {foot[1]:7.1f})   {d:7.1f}")
        print(f"  전체 평균 거리: {np.mean([g[-1] for g in bbox_gaps]):.1f} px")


def draw_check(folder: Path, calibs: dict, frame: int, out_dir: Path):
    """정답 좌표 투영점(초록 점)과 정답 bbox(파랑)를 이미지에 그려 저장"""
    row = next(json.loads(l) for l in (folder / "frames.jsonl").read_text(encoding="utf-8").splitlines()
               if l.strip() and json.loads(l)["frame"] == frame)
    out_dir.mkdir(parents=True, exist_ok=True)
    for c, calib in calibs.items():
        img = cv2.imread(str(folder / c / f"{frame:06d}.jpg"))
        if img is None:
            continue
        P = projection(calib)
        for o in row["objects"]:
            bb = o.get("bbox", {}).get(c)
            if bb:
                cv2.rectangle(img, (int(bb[0]), int(bb[1])), (int(bb[2]), int(bb[3])), (255, 0, 0), 2)
            uv, depth = project(P, np.array(unity_to_world(o["world"])))
            if depth > 0:
                cv2.circle(img, (int(uv[0]), int(uv[1])), 10, (0, 255, 0), -1)
                cv2.putText(img, o["object_id"], (int(uv[0]) + 12, int(uv[1])), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imwrite(str(out_dir / f"check_{frame:06d}_{c}.jpg"), img)
    print(f"확인용 이미지: {out_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Unity 출력 폴더 (cameras.json, frames.jsonl)")
    parser.add_argument("--check", action="store_true", help="삼각측량 왕복 검증 + 확인용 이미지 저장")
    parser.add_argument("--frame", type=int, default=1, help="확인용 이미지로 그릴 프레임")
    args = parser.parse_args()

    folder = Path(args.folder)
    calibs = load_calibrations(folder)
    out = folder / "calibration.json"
    out.write_text(json.dumps(calibs, indent=2), encoding="utf-8")
    for c, v in calibs.items():
        print(f"{c}: fx={v['K'][0][0]:.1f}  rvec={v['rvec']}  tvec={v['tvec']}")
    print(f"저장: {out}\n")

    if args.check:
        check(folder, calibs)
        draw_check(folder, calibs, args.frame, folder / "calib_check")


if __name__ == "__main__":
    main()
