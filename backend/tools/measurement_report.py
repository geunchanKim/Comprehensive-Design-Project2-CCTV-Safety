"""Summarize one edge session without assuming synchronized server/edge clocks."""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from .timing_summary import percentile


def load(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("durations must be finite nonnegative numbers")
    return float(value)


def report(folder):
    timings = load(folder / "timings.jsonl")
    sent = load(folder / "sent_detections.jsonl")
    responses = load(folder / "responses_detections.jsonl")
    failed = [row for row in load(folder / "failed.jsonl") if row.get("path") == "/detections"]
    if not any((timings, sent, responses, failed)):
        raise ValueError("no measurement records found")
    identities = {(row["session_id"], row.get("calibration_profile", "basic")) for row in sent + responses}
    identities |= {(row["message"]["session_id"], row["message"].get("calibration_profile", "basic"))
                   for row in failed}
    if len(identities) > 1:
        raise ValueError("one folder must contain one session/profile")
    if len({row.get("settings", {}).get("algorithm", "baseline") for row in responses}) > 1:
        raise ValueError("one folder must contain one algorithm condition")
    counts = Counter(row["pair_id"] for row in sent)
    if any(count > 1 for count in counts.values()):
        raise ValueError("duplicate successful pair_id in sent records")
    response_ids = [row["pair_id"] for row in responses]
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("duplicate pair_id in response records")
    timing_ids = [row["frame"] for row in timings]
    if len(timing_ids) != len(set(timing_ids)):
        raise ValueError("duplicate frame in timings records")
    metrics = defaultdict(list)
    for row in timings:
        for field in ("wait_ms", "age_ms", "rtt_ms"):
            if row.get(field) is not None:
                metrics[f"edge.{field}"].append(duration(row[field]))
        for field in ("detect_ms", "yolo_ms", "pose_ms"):
            if row.get(field) is not None:
                for camera, value in row[field].items():
                    metrics[f"edge.{field}.{camera}"].append(duration(value))
    for row in responses:
        for field, value in row.get("timings_ms", {}).items():
            metrics[f"server.{field}"].append(duration(value))
        if row.get("rtt_ms") is not None:
            metrics["response.rtt_ms"].append(duration(row["rtt_ms"]))
    times = []
    for row in sent:
        frames = row.get("frames", [])
        if frames:
            times.append(max(duration(f["recv_ms"] if f.get("recv_ms") is not None else f["ts"])
                             for f in frames))
    rate = ((len(times) - 1) * 1000 / (max(times) - min(times))
            if len(times) > 1 and max(times) > min(times) else None)
    observed = set(timing_ids) | set(counts) | set(response_ids)
    failures = Counter(str(row.get("status", "unknown")) for row in failed)
    missing_responses = set(counts) - set(response_ids)
    orphan_responses = set(response_ids) - set(counts)
    lines = ["# Edge and server measurement report", "", f"Folder: {folder.name}",
             f"Session/profile: {next(iter(identities), ('unavailable', 'unavailable'))}", "",
             f"- Timing rows: {len(timings)}; successful send records: {len(sent)}; responses: {len(responses)}",
             f"- Detection failures: {len(failed)}; by status: {dict(failures)}",
             f"- Successful sends without saved response: {len(missing_responses)}",
             f"- Saved responses without successful-send record: {len(orphan_responses)}",
             f"- Pairs present in all three logs: {len(set(timing_ids) & set(counts) & set(response_ids))}",
             f"- Observed pair range: {min(observed) if observed else '-'}..{max(observed) if observed else '-'}",
             f"- Successful sends per input receive-time second: {rate:.3f}" if rate is not None
             else "- Successful sends per input receive-time second: unavailable", "",
             "This rate uses successful input frame times, not server response completion times.",
             "Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.", "",
             "| Metric | Samples | Mean ms | p50 ms | p95 ms | Max ms |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, values in sorted(metrics.items()):
        lines.append(f"| {name} | {len(values)} | {mean(values):.3f} | {percentile(values, 50):.3f} | "
                     f"{percentile(values, 95):.3f} | {max(values):.3f} |")
    for field in ("yolo_ms", "pose_ms", "rtt_ms"):
        if not any(field in name for name in metrics):
            lines.append(f"\n{field}: unavailable")
    if not any(name.startswith("server.") for name in metrics):
        lines.append("\nServer stage timings: unavailable (expected before profiling deployment).")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = report(args.folder)
        args.out.write_text(result, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
