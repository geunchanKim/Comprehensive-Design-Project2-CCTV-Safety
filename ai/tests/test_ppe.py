import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ppe"))

from ppe_common import crop_labels, decide_state, expand_box, person_truth  # noqa: E402


def test_expand_box_adds_more_room_on_top_and_stays_inside_image():
    assert expand_box((100, 100, 200, 300), 1000, 1000) == (90, 70, 210, 310)
    assert expand_box((0, 10, 50, 100), 60, 100) == (0, 0, 55, 100)


def test_crop_labels_keeps_mostly_visible_boxes_and_clips_them():
    crop = (100, 100, 300, 500)
    labels = crop_labels(crop, [
        (0, (150, 100, 250, 150)),   # 안전모: 전부 보임
        (2, (280, 200, 380, 400)),   # 옆 사람 조끼: 20%만 보임 → 뺀다
        (3, (90, 300, 290, 400)),    # 조끼 없음: 95% 보임 → 영역 안으로 자른다
    ])
    assert [label[0] for label in labels] == [0, 3]
    cls, cx, cy, w, h = labels[1]
    assert (round(cx, 3), round(cy, 3), round(w, 3), round(h, 3)) == (0.475, 0.625, 0.95, 0.25)


def test_person_truth_gives_each_ppe_box_to_the_most_overlapping_person():
    left, right = (0, 0, 100, 300), (80, 0, 200, 300)
    ppe = [(0, (20, 0, 60, 40)),        # 왼쪽 사람 안전모
           (3, (85, 100, 195, 200)),    # 오른쪽 사람 조끼 없음 (왼쪽과 조금 겹침)
           (2, (10, 100, 90, 200))]     # 왼쪽 사람 조끼
    assert person_truth(0, [left, right], ppe) == {"helmet": "wearing", "vest": "wearing"}
    assert person_truth(1, [left, right], ppe) == {"helmet": "unknown", "vest": "not_wearing"}


def test_person_truth_is_unknown_when_both_states_are_labelled():
    person = (0, 0, 100, 300)
    ppe = [(2, (10, 100, 90, 150)), (3, (10, 150, 90, 200))]
    assert person_truth(0, [person], ppe)["vest"] == "unknown"


def test_decide_state_uses_best_confident_box_and_ignores_edges_and_low_helmets():
    detections = [
        (0, 0.55, 0.5, 0.1, 0.2, 0.1),    # 안전모
        (1, 0.80, 0.5, 0.7, 0.2, 0.1),    # 아래쪽 "안전모 없음" → 머리 위치가 아니라서 무시
        (3, 0.90, 0.95, 0.5, 0.2, 0.3),   # 가장자리 → 옆 사람 것으로 보고 무시
        (2, 0.70, 0.5, 0.5, 0.6, 0.4),    # 조끼
        (3, 0.60, 0.5, 0.5, 0.6, 0.4),
    ]
    state = decide_state(detections)
    assert state["helmet"] == {"status": "wearing", "confidence": 0.55}
    assert state["vest"] == {"status": "wearing", "confidence": 0.7}


def test_decide_state_is_unknown_without_confident_box():
    state = decide_state([(1, 0.2, 0.5, 0.1, 0.2, 0.1)])
    assert state == {"helmet": {"status": "unknown", "confidence": None},
                     "vest": {"status": "unknown", "confidence": None}}
