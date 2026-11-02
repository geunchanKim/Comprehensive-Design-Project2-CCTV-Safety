"""
실시간 속도 요약: realtime.py --send 가 남긴 timings.jsonl 을 읽어 표로 보여 준다

무엇을 하나
  - runs/edge/<session_id>/timings.jsonl 의 짝마다 기록을 모은다 (항목 뜻은 edge/realtime.py 맨 위 설명)
  - 처음 몇 짝은 빼고 계산한다 (--warmup, 기본 5짝). 첫 짝은 모델을 처음 돌리는 준비 시간이라 수 초가 걸린다
  - 항목마다 중간값·90% 값·최댓값을 구한다 (90% 값: 짝 10개 중 9개가 이 시간 안에 끝남)
      대기       wait_ms
      검출 합    두 카메라 yolo_ms 합 (물체 검출·추적)
      포즈 합    두 카메라 pose_ms 합 (발목)
      탐지 합    두 카메라 detect_ms 합 (검출 + 포즈 + 정리)
      엣지 전체  age_ms (프레임을 받은 뒤 서버 전송 큐에 넣기까지)
      서버 왕복  rtt_ms (요청을 보낸 뒤 응답을 받기까지. dry-run 이면 -)
  - 짝 번호 사이 빈칸으로 "탐지가 밀려서 건너뛴 짝" 비율을 구한다
  - 같은 폴더의 sent_detections.jsonl 로 1초에 보낸 짝 수를 구한다 (준비 짝은 빼고)
  - 서버 실패·버림(status 가 2xx·dry-run 이 아닌 짝) 개수를 센다
  - 예전 기록(yolo_ms 등이 없는 줄)은 그 칸을 - 로 둔다

명령 (ai/ 폴더에서)
  python eval/timing_summary.py runs/edge/classroom-1014-s10-t1-v6
  python eval/timing_summary.py runs/edge/classroom-1014-s*-v6         # 여러 세션을 한 표로
  python eval/timing_summary.py runs/edge/classroom-1014-s*-v6 --warmup 0
"""
import argparse
import json
from pathlib import Path

import numpy as np


def load(folder: Path) -> list[dict]:
    path = folder / "timings.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} 없음 (realtime.py --send 로 기록한 폴더인지 확인)")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"{path} 가 비어 있음")
    return sorted(rows, key=lambda r: r["frame"])


def stats(values) -> str:
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size == 0:
        return "-"
    return f"{np.median(v):.0f} / {np.percentile(v, 90):.0f} / {v.max():.0f}"


def cam_sum(row: dict, key: str):
    """카메라별 값 {cam1: .., cam2: ..} 의 합. 없거나 빈 값이 있으면 None"""
    parts = row.get(key)
    if not parts or any(v is None for v in parts.values()):
        return None
    return sum(parts.values())


def ok_status(status) -> bool:
    return status is None or status == "dry-run" or (isinstance(status, int) and 200 <= status < 300)


def pairs_per_second(folder: Path, first_frame: int) -> float | None:
    """sent_detections.jsonl 에서 first_frame 이후 짝들의 첫·마지막 시각으로 1초에 보낸 짝 수를 구한다"""
    sent = folder / "sent_detections.jsonl"
    if not sent.exists():
        return None
    times = []
    for line in sent.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        bundle = json.loads(line)
        frames = bundle.get("frames", [])
        if frames and bundle.get("pair_id", first_frame) >= first_frame:
            times.append(max(f.get("recv_ms", f["ts"]) for f in frames))
    if len(times) < 2 or times[-1] <= times[0]:
        return None
    return (len(times) - 1) / ((times[-1] - times[0]) / 1000)


def summarize(folder: Path, warmup: int = 5) -> list[str]:
    rows = load(folder)
    if len(rows) > warmup:
        rows = rows[warmup:]
    frames = [r["frame"] for r in rows]
    span = max(frames) - min(frames) + 1
    pps = pairs_per_second(folder, min(frames))
    bad = sum(1 for r in rows if not ok_status(r.get("status")))
    return [folder.name, str(len(rows)), f"{100 * (1 - len(rows) / span):.0f}%",
            "-" if pps is None else f"{pps:.1f}",
            stats(r["wait_ms"] for r in rows),
            stats(cam_sum(r, "yolo_ms") for r in rows),
            stats(cam_sum(r, "pose_ms") for r in rows),
            stats(cam_sum(r, "detect_ms") for r in rows),
            stats(r["age_ms"] for r in rows),
            stats(r.get("rtt_ms") for r in rows),
            str(bad)]


HEAD = ["세션", "짝", "건너뛴 짝", "초당 짝", "대기", "검출 합", "포즈 합", "탐지 합", "엣지 전체", "서버 왕복", "실패·버림"]


def main():
    parser = argparse.ArgumentParser(description="실시간 전송 시간 기록(timings.jsonl) 요약")
    parser.add_argument("folders", nargs="+", help="runs/edge/<session_id> 폴더")
    parser.add_argument("--warmup", type=int, default=5, help="앞에서 뺄 짝 수 (모델 준비 시간)")
    args = parser.parse_args()

    print(f"시간(ms)은 중간값 / 90% 값 / 최댓값 · 앞 {args.warmup}짝 제외\n")
    print("| " + " | ".join(HEAD) + " |")
    print("|" + "---|" * len(HEAD))
    for folder in args.folders:
        print("| " + " | ".join(summarize(Path(folder), args.warmup)) + " |")


if __name__ == "__main__":
    main()
