"""
발 위치 계산: 사람 탐지에 발 위치(foot)와 좌우 발목(ankles)을 붙인다.

YOLO·torch 없이 계산만 하는 부분이라 detector.py에서 떼어 냈다 (CI에서 테스트 가능).

foot (기존, 서버가 지금 쓰는 값)
  두 발목 신뢰도가 모두 ankle_conf 이상이면 두 발목 가운데 (foot_src="ankle"), 아니면 박스 아래 가운데 (foot_src="box")

ankles (멘토 피드백 1: 같은 쪽 발목끼리 대응)
  {"left": [x, y, conf] | null, "right": [x, y, conf] | null}
  - 왼쪽·오른쪽은 사람 기준 (COCO 키포인트 15 = 왼발목, 16 = 오른발목). 화면 왼쪽·오른쪽이 아니다
  - 신뢰도가 ankle_conf 미만인 쪽은 null
  - 포즈 결과와 짝지어지지 않았거나 두 발목이 다 안 보이면 ankles를 붙이지 않는다
  - 서버는 왼발목끼리, 오른발목끼리 따로 삼각측량해서 한쪽이 가려져도 같은 점을 쓸 수 있다
"""

LEFT_ANKLE, RIGHT_ANKLE = 15, 16                       # COCO 키포인트 번호 (사람 기준 왼쪽·오른쪽)


def box_foot(bbox) -> list:
    """박스 아래 가운데"""
    x1, _, x2, y2 = bbox
    return [round((x1 + x2) / 2, 1), round(y2, 1)]


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _ankle(kp, ankle_conf: float):
    x, y, c = kp
    return [round(x, 1), round(y, 1), round(c, 3)] if c >= ankle_conf else None


def attach_feet(detections: list[dict], people: list[tuple], ankle_conf: float = 0.5, min_iou: float = 0.5):
    """탐지마다 foot, foot_src를 붙이고, 사람이면 보이는 발목을 ankles로 붙인다.
    people: 포즈 모델 결과 [(박스, [(x, y, conf) × 17]), ...]
    사람 탐지는 박스가 가장 많이 겹치는 포즈 결과(IoU ≥ min_iou)와 짝짓는다."""
    for d in detections:
        d["foot"], d["foot_src"] = box_foot(d["bbox"]), "box"
        d.pop("ankles", None)
        if d["cls"] != "person" or not people:
            continue
        score, best = max(((iou(d["bbox"], box), kps) for box, kps in people), key=lambda t: t[0])
        if score < min_iou:
            continue
        left, right = _ankle(best[LEFT_ANKLE], ankle_conf), _ankle(best[RIGHT_ANKLE], ankle_conf)
        if left or right:
            d["ankles"] = {"left": left, "right": right}
        if left and right:
            d["foot"] = [round((left[0] + right[0]) / 2, 1), round((left[1] + right[1]) / 2, 1)]
            d["foot_src"] = "ankle"
    return detections
