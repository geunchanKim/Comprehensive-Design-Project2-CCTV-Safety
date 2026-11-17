"""실제 영상 라벨 세트 채점(eval/label_set.py): YOLO 없이 도는 계산만 검사"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from label_set import candidates, iou, match, read_yolo, summarize, to_yolo  # noqa: E402


def test_iou_and_yolo_round_trip(tmp_path):
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 1 / 3
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0
    box = (100.0, 50.0, 300.0, 450.0)
    (tmp_path / "a.txt").write_text(f"1 {to_yolo(box, 1920, 1080)}\n")
    [(cls, back)] = read_yolo(tmp_path / "a.txt", 1920, 1080)
    assert cls == "chair" and all(abs(a - b) < 0.01 for a, b in zip(back, box))
    assert read_yolo(tmp_path / "없음.txt", 1920, 1080) == []          # 라벨 파일 없음 = 물체 없는 프레임


def test_match_counts_tp_fp_fn_and_other_class_confusion():
    truth = [("person", (0, 0, 100, 300)), ("person", (500, 0, 600, 300)), ("chair", (200, 100, 300, 300)),
             ("person", (900, 0, 905, 10))]                              # 높이 10px: 채점에서 뺌
    preds = [("person", 0.9, (5, 5, 100, 300)),                          # 맞음
             ("person", 0.6, (200, 100, 300, 290)),                      # 의자를 사람으로 → 오탐(다른 클래스)
             ("chair", 0.5, (1000, 0, 1100, 200)),                       # 아무것도 없는 곳 → 오탐
             ("person", 0.7, (0, 0, 100, 300))]                          # 같은 사람 중복 → 오탐
    rows = match(truth, preds)
    kinds = sorted((r[0], r[1], r[5]) for r in rows)
    assert kinds == sorted([("tp", "person", False), ("fp", "person", True), ("fp", "person", False),
                            ("fp", "chair", False), ("fn", "person", False), ("fn", "chair", False)])
    s = summarize(rows)
    assert s["person"] == {"truth": 2, "detections": 3, "tp": 1, "fp": 2, "fn": 1, "fp_from_other_class": 1,
                           "false_positive_rate": 0.6667, "recall": 0.5}
    assert s["chair"]["false_positive_rate"] == 1.0 and s["chair"]["recall"] == 0.0


def test_candidates_use_stride_alternate_cameras_and_fixed_seed(tmp_path):
    for rec in ("s1/t1", "s2/t1"):
        for cam in ("cam1", "cam2"):
            (tmp_path / rec / cam).mkdir(parents=True)
            for n in range(1, 101):
                (tmp_path / rec / cam / f"{n:06d}.jpg").touch()
    got = candidates(tmp_path, stride=30, seed=0)
    assert len(got) == 6                                                 # 녹화마다 16, 46, 76번 3개
    s1 = sorted((n, c) for f, n, c in got if f.parent.name == "s1")
    assert s1 == [(16, "cam1"), (46, "cam2"), (76, "cam1")]              # 카메라 번갈아
    assert got == candidates(tmp_path, stride=30, seed=0)                # 같은 seed면 같은 순서
