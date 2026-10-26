"""
조건 간 위치 오차 통계 검정: 논문 Ⅳ장의 p값을 다시 계산한다

무엇을 하나
  - run_experiment.py 가 만든 실측 실험 폴더(runs/experiments/<label>)의 position_errors.csv 를 읽는다
  - 두 조건에서 모두 위치를 찾은(status=ok) 같은 사람끼리 짝지어 오차 차이를 구한다
  - 차이마다 두 가지 검정을 한다
      Wilcoxon 부호순위 검정 (양측)   "오차가 달라졌나?"           p < 0.05 → 차이 있음
      TOST 동등성 검정 (짝지은 t검정)  "차이가 ±margin 안에 있나?"  p < 0.05 → 실질적으로 같음
  - 영상 내 위치별로도 나눠 본다. 정답 지점을 정밀(precise) 캘리브레이션으로 두 카메라 영상에 투영하고,
    주점에서 떨어진 거리를 영상 대각선 절반으로 나눈 값(0: 중심, 1: 모서리) 중 큰 값을 쓴다
      0.5 미만 = 가운데, 0.5 이상 0.7 미만 = 바깥쪽, 0.7 이상 = 가장자리

조건 이름 (폴더)
  기준 방법           <pack>/position_errors.csv
  렌즈 캘리브레이션    <pack>/precise-baseline/
  매칭 알고리즘        <pack>/basic-improved/
  두 방법 결합         <pack>/precise-improved/

명령 (ai/ 폴더에서)
  python eval/compare_conditions.py runs/experiments/real-2x2-v4
  python eval/compare_conditions.py runs/experiments/real-2x2-v4 --margin 2 --cls person
"""
import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy import stats

AI_DIR = Path(__file__).resolve().parents[1]
CONDITIONS = {"B": ".", "C": "precise-baseline", "A": "basic-improved", "CA": "precise-improved"}
LABELS = {"B": "기준 방법", "C": "렌즈 캘리브레이션", "A": "매칭 알고리즘", "CA": "두 방법 결합"}
PAIRS = [("B", "C"), ("B", "A"), ("A", "CA"), ("C", "CA")]
REGIONS = [("전체", None), ("가운데", (0.0, 0.5)), ("바깥쪽", (0.5, 0.7)), ("가장자리", (0.7, 9.9))]


def image_radius(calib, gt_x, gt_y):
    """정답 지점을 두 카메라에 투영해 정규화 거리(0: 중심, 1: 모서리) 중 큰 값을 돌려준다"""
    radii = []
    for cam in ("cam1", "cam2"):
        q = calib[cam]["precise"]
        w, h = q["image_size"]
        K = np.array(q["K"], dtype=float)
        pt, _ = cv2.projectPoints(np.array([[gt_x, gt_y, 0.0]]), np.array(q["rvec"], dtype=float),
                                  np.array(q["tvec"], dtype=float), K, np.array(q["dist"], dtype=float))
        x, y = pt.ravel()
        radii.append(math.hypot(x - K[0, 2], y - K[1, 2]) / math.hypot(w / 2, h / 2))
    return max(radii)


def load(exp_dir, cls):
    """조건별 {사람 키: 오차(cm)} 와 {사람 키: 정규화 거리} 를 만든다"""
    errors = {c: {} for c in CONDITIONS}
    radius = {}
    for pack_dir in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
        calib_path = AI_DIR / "eval" / "packs" / pack_dir.name / "calibration.json"
        calib = json.loads(calib_path.read_text(encoding="utf-8"))
        for cond, sub in CONDITIONS.items():
            path = pack_dir / sub / "position_errors.csv"
            if not path.exists():
                continue
            for r in csv.DictReader(path.open(encoding="utf-8")):
                if r["cls"] != cls or r["status"] not in ("ok", "missed"):
                    continue
                key = (pack_dir.name, r["frame"], r["object_id"])
                if key not in radius:
                    radius[key] = image_radius(calib, float(r["gt_x"]), float(r["gt_y"]))
                if r["status"] == "ok":
                    errors[cond][key] = float(r["floor_err_cm"])
    return errors, radius


def tost(diff, margin):
    """짝지은 t검정을 단측으로 두 번: 차이 > -margin, 차이 < +margin. 둘 중 큰 p"""
    p_low = stats.ttest_1samp(diff, -margin, alternative="greater").pvalue
    p_high = stats.ttest_1samp(diff, margin, alternative="less").pvalue
    return max(p_low, p_high)


def main():
    p = argparse.ArgumentParser(description="조건 간 위치 오차 통계 검정 (Wilcoxon·TOST)")
    p.add_argument("exp_dir", help="실험 결과 폴더 (예: runs/experiments/real-2x2-v4)")
    p.add_argument("--margin", type=float, default=2.0, help="TOST 동등성 범위 ±cm (기본 2)")
    p.add_argument("--cls", default="person", help="평가 대상 클래스 (기본 person)")
    args = p.parse_args()

    errors, radius = load(Path(args.exp_dir), args.cls)
    print(f"정답 {len(radius)}명 · 찾음: " + ", ".join(f"{LABELS[c]} {len(errors[c])}" for c in CONDITIONS))
    print(f"\n| 비교 | 구간 | 사람 | 평균 오차 (cm) | 좋아짐/나빠짐 | Wilcoxon p | TOST p (±{args.margin:g}cm) |")
    print("|---|---|---|---|---|---|---|")
    for a, b in PAIRS:
        for region, rng in REGIONS:
            keys = sorted(k for k in errors[a].keys() & errors[b].keys()
                          if rng is None or rng[0] <= radius[k] < rng[1])
            if len(keys) < 2:
                continue
            ea = np.array([errors[a][k] for k in keys])
            eb = np.array([errors[b][k] for k in keys])
            diff = eb - ea
            w_p = stats.wilcoxon(diff).pvalue if np.any(diff != 0) else 1.0
            better, worse = int((diff < 0).sum()), int((diff > 0).sum())
            print(f"| {LABELS[a]} → {LABELS[b]} | {region} | {len(keys)} | {ea.mean():.2f} → {eb.mean():.2f} "
                  f"| {better}/{worse} | {w_p:.3f} | {tost(diff, args.margin):.3f} |")


if __name__ == "__main__":
    main()
