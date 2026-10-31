"""
실시간 속도 요약: realtime.py --send 가 남긴 timings.jsonl 을 읽어 표로 보여 준다

무엇을 하나
  - runs/edge/<session_id>/timings.jsonl 의 짝마다 기록을 모은다
      wait_ms    짝이 만들어진 뒤 탐지를 시작하기까지 기다린 시간
      detect_ms  카메라별 탐지(발목 포함) 시간
      age_ms     카메라가 프레임을 받은 뒤 서버 전송 큐에 넣기까지 걸린 전체 시간
  - 항목마다 중간값·90% 값·최댓값을 구한다 (90% 값: 짝 10개 중 9개가 이 시간 안에 끝남)
  - 짝 번호 사이 빈칸으로 "탐지가 밀려서 건너뛴 짝" 비율을 구한다
  - 같은 폴더의 sent_detections.jsonl 로 1초에 보낸 짝 수를 구한다

명령 (ai/ 폴더에서)
  python eval/timing_summary.py runs/edge/classroom-1101-s1-t1
  python eval/timing_summary.py runs/edge/a runs/edge/b        # 여러 세션을 한 표로 비교
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
    return rows


def stats(values) -> str:
    v = np.asarray(list(values), dtype=float)
    return f"{np.median(v):.0f} / {np.percentile(v, 90):.0f} / {v.max():.0f}"


def pairs_per_second(folder: Path) -> float | None:
    """sent_detections.jsonl 의 첫·마지막 프레임 시각으로 1초에 보낸 짝 수를 구한다"""
    sent = folder / "sent_detections.jsonl"
    if not sent.exists():
        return None
    times = []
    for line in sent.read_text(encoding="utf-8").splitlines():
        if line.strip():
            frames = json.loads(line).get("frames", [])
            if frames:
                times.append(max(f.get("recv_ms", f["ts"]) for f in frames))
    if len(times) < 2 or times[-1] <= times[0]:
        return None
    return (len(times) - 1) / ((times[-1] - times[0]) / 1000)


def summarize(folder: Path) -> tuple[list[str], list[str]]:
    rows = load(folder)
    frames = [r["frame"] for r in rows]
    span = max(frames) - min(frames) + 1
    detect_total = [sum(r["detect_ms"].values()) for r in rows]
    cams = sorted({cam for r in rows for cam in r["detect_ms"]})
    pps = pairs_per_second(folder)
    line = [folder.name, str(len(rows)), f"{100 * (1 - len(rows) / span):.0f}%",
            "-" if pps is None else f"{pps:.1f}", stats(r["wait_ms"] for r in rows)]
    line += [stats(r["detect_ms"].get(cam, 0) for r in rows) for cam in cams]
    line += [stats(detect_total), stats(r["age_ms"] for r in rows)]
    return line, cams


def main():
    parser = argparse.ArgumentParser(description="실시간 전송 시간 기록(timings.jsonl) 요약")
    parser.add_argument("folders", nargs="+", help="runs/edge/<session_id> 폴더")
    args = parser.parse_args()

    results = [summarize(Path(f)) for f in args.folders]
    cams = results[0][1]
    head = ["세션", "보낸 짝", "건너뛴 짝", "초당 짝", "대기 (ms)"] + [f"탐지 {c} (ms)" for c in cams]
    head += ["탐지 합 (ms)", "전체 (ms)"]
    print("시간은 중간값 / 90% 값 / 최댓값\n")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for line, _ in results:
        print("| " + " | ".join(line) + " |")


if __name__ == "__main__":
    main()
