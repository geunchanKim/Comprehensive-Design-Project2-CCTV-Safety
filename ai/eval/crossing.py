"""
교차 구간 지표: 두 사람이 가까워질 때 추적·위치·경고가 버티는지 본다 (계획표 P1-6)

평균 오차는 대부분의 "멀리 떨어진" 프레임이 정한다. 위험 판단이 필요한 건 사람이 가까울 때라서,
정답에서 두 사람 사이 바닥 거리가 가까운 프레임만 따로 모아 센다.

입력
  rows: eval_position.evaluate 결과 (status = ok 인 줄에 정답 object_id 와 서버 위치·object_id 가 있음)
  gt:   Unity frames.jsonl 정답 {frame: {"objects": [...]}}

지표 (사람 두 명 짝마다, 정답 거리 기준)
  near_1m / near_06m   정답 거리가 1m / 0.6m 미만인 (프레임, 두 사람) 수
  both_1m / both_06m   그중 두 사람 모두 "맞음"으로 추적된 비율
  dist_err_cm          둘 다 추적된 경우 |서버 거리 - 정답 거리| 평균 (1m 미만 구간)
  id_switches_near     1m 미만 구간 프레임에서 생긴 ID 바뀜 수
  warn_tp / warn_fn / warn_fp
                       1m 경고 채점. 정답이 1m 미만인데 서버도 경고면 맞음(tp),
                       서버가 경고가 아니거나 한 명이라도 놓치면 놓침(fn),
                       정답은 1m 이상인데 서버가 경고면 오경보(fp)
                       서버 경고 = 서버가 준 경고 단계(risk 줄, F 경고 유지)가 있으면 그것, 없으면 서버 위치 거리 < 1m
  warn_fn_band / warn_fp_band
                       채점 여유 구간: 정답 거리가 0.9~1.1m인 프레임은 빼고 센 놓침·오경보
                       (1m 경계에서 몇 cm 차이로 갈리는 경우를 따로 보기 위함)
"""

import itertools
import math

WARN_M = 1.0
CLOSE_M = 0.6
BAND_M = (0.9, 1.1)
COLUMNS = ["pack", "cond", "near_1m", "both_1m", "near_06m", "both_06m", "dist_err_cm",
           "id_switches_near", "warn_tp", "warn_fn", "warn_fp", "warn_fn_band", "warn_fp_band"]


def _floor(o):
    """Unity (x, y, z) → 바닥 (x, z)"""
    return o["world"][0], o["world"][2]


def risk_levels(responses: list[dict]) -> dict:
    """응답의 risks → {(프레임, frozenset(서버 사람 번호 두 개)): 경고 단계}. 서버가 경고를 안 줬으면 빈 dict"""
    out = {}
    for resp in responses:
        for r in resp.get("risks") or []:
            out[(resp["pair_id"], frozenset((str(r["object1_id"]), str(r["object2_id"]))))] = r["level"]
    return out


def crossing_metrics(rows: list[dict], gt: dict, risks: dict | None = None) -> dict | None:
    """사람이 두 명 이상 나오는 데이터만 계산한다. 아니면 None
    risks: risk_levels() 결과. 주면 서버 경고 단계로 경고를 채점한다"""
    est = {(r["frame"], r["object_id"]): r for r in rows if r["status"] == "ok" and r["cls"] == "person"}
    near1 = near06 = both1 = both06 = tp = fn = fp = fn_band = fp_band = 0
    dist_errs, near_frames = [], {}
    any_pair = False
    for frame, g in gt.items():
        people = [o for o in g.get("objects", []) if o["cls"] == "person"]
        for a, b in itertools.combinations(people, 2):
            any_pair = True
            d_gt = math.dist(_floor(a), _floor(b))
            ea, eb = est.get((frame, a["object_id"])), est.get((frame, b["object_id"]))
            both = ea is not None and eb is not None
            d_est = math.dist((ea["est_x"], ea["est_y"]), (eb["est_x"], eb["est_y"])) if both else None
            warn = both and d_est < WARN_M
            if both and risks:
                level = risks.get((frame, frozenset((str(ea["server_object_id"]), str(eb["server_object_id"])))))
                if level is not None:
                    warn = level != "safe"
            in_band = BAND_M[0] <= d_gt < BAND_M[1]
            if d_gt < WARN_M:
                near1 += 1
                both1 += both
                near_frames.setdefault(frame, set()).update((a["object_id"], b["object_id"]))
                if both:
                    dist_errs.append(abs(d_est - d_gt) * 100)
                if warn:
                    tp += 1
                else:
                    fn += 1
                    fn_band += not in_band
                if d_gt < CLOSE_M:
                    near06 += 1
                    both06 += both
            elif warn:
                fp += 1
                fp_band += not in_band
    if not any_pair:
        return None

    # 가까운 구간 프레임에서 생긴 ID 바뀜 (같은 정답 사람에 붙은 서버 object_id 가 직전 "맞음" 프레임과 다름)
    switches, last = 0, {}
    for (frame, oid), r in sorted(est.items()):
        prev = last.get(oid)
        if prev is not None and prev != r["server_object_id"] and oid in near_frames.get(frame, ()):
            switches += 1
        last[oid] = r["server_object_id"]

    rate = lambda hit, n: round(hit / n, 4) if n else None
    return {"near_1m": near1, "both_1m": rate(both1, near1), "near_06m": near06, "both_06m": rate(both06, near06),
            "dist_err_cm": round(sum(dist_errs) / len(dist_errs), 1) if dist_errs else None,
            "id_switches_near": switches, "warn_tp": tp, "warn_fn": fn, "warn_fp": fp,
            "warn_fn_band": fn_band, "warn_fp_band": fp_band}


def markdown(rows: list[dict]) -> str:
    """교차 구간 표 (사람 두 명 이상인 pack 만)"""
    if not rows:
        return ""
    pct = lambda v: "-" if v is None else f"{v * 100:.0f}%"
    lines = ["", "#### 교차 구간 (정답에서 두 사람이 가까운 프레임)", "",
             "| pack | 조건 | 1m 안 | 둘 다 추적 | 0.6m 안 | 둘 다 추적 | 거리 오차(cm) | ID 바뀜 | 1m 경고 맞음 / 놓침 / 오경보 | 여유 구간(0.9~1.1m) 빼고 놓침 / 오경보 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        err = "-" if r["dist_err_cm"] is None else f"{r['dist_err_cm']:.1f}"
        lines.append(f"| {r['pack']} | {r['cond']} | {r['near_1m']} | {pct(r['both_1m'])} | {r['near_06m']} | "
                     f"{pct(r['both_06m'])} | {err} | {r['id_switches_near']} | "
                     f"{r['warn_tp']} / {r['warn_fn']} / {r['warn_fp']} | "
                     f"{r.get('warn_fn_band', '-')} / {r.get('warn_fp_band', '-')} |")
    return "\n".join(lines) + "\n"
