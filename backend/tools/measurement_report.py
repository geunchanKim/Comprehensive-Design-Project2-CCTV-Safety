"""Summarize edge sessions without assuming synchronized server/edge clocks."""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from .server_log_summary import percentile


def load(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("durations must be finite nonnegative numbers")
    return float(value)


def analyze(folder, warmup):
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
    # Exclude the same observed pair IDs from every latency source. Frame IDs
    # need not be contiguous, and timing rows may arrive in completion order.
    observed = set(timing_ids) | set(counts) | set(response_ids)
    observed |= {row["message"]["pair_id"] for row in failed}
    excluded = set(sorted(observed)[:warmup])
    for row in timings:
        if row["frame"] in excluded:
            continue
        for field in ("wait_ms", "age_ms", "queue_ms", "rtt_ms"):
            if row.get(field) is not None:
                metrics[f"edge.{field}"].append(duration(row[field]))
        for field in ("detect_ms", "yolo_ms", "pose_ms"):
            if row.get(field) is not None:
                values = []
                for camera, value in row[field].items():
                    values.append(duration(value))
                    metrics[f"edge.{field}.{camera}"].append(values[-1])
                if values:
                    metrics[f"edge.{field}.total"].append(sum(values))
    for row in responses:
        if row["pair_id"] in excluded:
            continue
        for field, value in row.get("timings_ms", {}).items():
            metrics[f"server.{field}"].append(duration(value))
        if row.get("rtt_ms") is not None:
            metrics["response.rtt_ms"].append(duration(row["rtt_ms"]))
    times = []
    for row in sent:
        if row["pair_id"] in excluded:
            continue
        frames = row.get("frames", [])
        if frames:
            times.append(max(duration(f["recv_ms"] if f.get("recv_ms") is not None else f["ts"])
                             for f in frames))
    rate = ((len(times) - 1) * 1000 / (max(times) - min(times))
            if len(times) > 1 and max(times) > min(times) else None)
    failures = Counter(str(row.get("status", "unknown")) for row in failed)
    missing_responses = set(counts) - set(response_ids)
    orphan_responses = set(response_ids) - set(counts)
    lines = ["# Edge and server measurement report", "", f"Folder: {folder.name}",
             f"Session/profile: {next(iter(identities), ('unavailable', 'unavailable'))}", "",
             f"- Timing rows: {len(timings)}; successful send records: {len(sent)}; responses: {len(responses)}",
             f"- Detection failures: {len(failed)}; by status: {dict(failures)}",
             f"- Timing status counts (all rows): {dict(Counter(str(row.get('status', 'unknown')) for row in timings))}",
             f"- Warmup pairs excluded from latency statistics: {len(excluded)} (requested {warmup})",
             f"- Successful sends without saved response: {len(missing_responses)}",
             f"- Saved responses without successful-send record: {len(orphan_responses)}",
             f"- Pairs present in all three logs: {len(set(timing_ids) & set(counts) & set(response_ids))}",
             f"- Observed pair range: {min(observed) if observed else '-'}..{max(observed) if observed else '-'}",
             f"- Successful sends per input receive-time second: {rate:.3f}" if rate is not None
             else "- Successful sends per input receive-time second: unavailable", "",
             "This rate uses successful input frame times, not server response completion times.",
             "Missing measurements are unavailable, never zero. RTT is not capture-to-display latency.", "",
             ]
    return lines, metrics, identities, responses


def metric_table(metrics):
    lines = ["| Metric | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, values in sorted(metrics.items()):
        lines.append(f"| {name} | {len(values)} | {mean(values):.3f} | {percentile(values, 50):.3f} | "
                     f"{percentile(values, 90):.3f} | "
                     f"{percentile(values, 95):.3f} | {max(values):.3f} |")
    for field in ("yolo_ms", "pose_ms", "rtt_ms"):
        if not any(field in name for name in metrics):
            lines.append(f"\n{field}: unavailable")
    if not any(name.startswith("server.") for name in metrics):
        lines.append("\nServer stage timings: unavailable (expected before profiling deployment).")
    return "\n".join(lines) + "\n"


def report(folders, warmup=0):
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ValueError("warmup must be a nonnegative integer")
    if isinstance(folders, (str, Path)):
        folders = [Path(folders)]
    folders = [Path(folder) for folder in folders]
    if not folders or len({folder.resolve() for folder in folders}) != len(folders):
        raise ValueError("provide distinct session folders")
    results = [analyze(folder, warmup) for folder in folders]
    if len(results) == 1:
        lines, metrics, _, _ = results[0]
        return "\n".join(lines) + "\n" + metric_table(metrics)
    identities = [identity for _, _, ids, _ in results for identity in ids]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate session/profile across folders")
    # Different calibration/algorithm/version conditions are separate experiments.
    conditions = {(profile, match.group() if (match := re.search(r"-v\d+$", session)) else None)
                  for session, profile in identities}
    algorithms = {row.get("settings", {}).get("algorithm", "baseline")
                  for _, _, _, responses in results for row in responses}
    if len(conditions) > 1 or len(algorithms) > 1:
        raise ValueError("cannot aggregate different version/profile/algorithm conditions")
    combined = defaultdict(list)
    statuses = Counter()
    failures = Counter()
    totals = Counter()
    for folder, (_, metrics, _, _) in zip(folders, results):
        for name, values in metrics.items():
            combined[name].extend(values)
        timings = load(folder / "timings.jsonl")
        statuses.update(str(row.get("status", "unknown")) for row in timings)
        totals["timings"] += len(timings)
        sent = load(folder / "sent_detections.jsonl")
        responses = load(folder / "responses_detections.jsonl")
        failed = [row for row in load(folder / "failed.jsonl") if row.get("path") == "/detections"]
        totals["sent"] += len(sent)
        totals["responses"] += len(responses)
        totals["failed"] += len(failed)
        failures.update(str(row.get("status", "unknown")) for row in failed)
        sent_ids = {row["pair_id"] for row in sent}
        response_ids = {row["pair_id"] for row in responses}
        totals["missing_responses"] += len(sent_ids - response_ids)
        totals["orphan_responses"] += len(response_ids - sent_ids)
        totals["pairs_in_all_three_logs"] += len(sent_ids & response_ids & {row["frame"] for row in timings})
    lines = ["# Edge and server measurement report", "", "## Overall", "",
             f"Sessions: {len(folders)}; warmup: first {warmup} observed pairs per session.",
             "Latency statistics pool individual samples; record/status counts include warmup; send rates exclude warmup.",
             f"- Records (all pairs): {dict(totals)}",
             f"- Timing status counts (all rows): {dict(statuses)}",
             f"- Detection failure status counts (all rows): {dict(failures)}", "", metric_table(combined)]
    for folder, (details, metrics, _, _) in zip(folders, results):
        lines += [f"## {folder.name}", "", *details[2:], metric_table(metrics)]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", type=Path, nargs="+")
    parser.add_argument("--warmup", type=int, default=0,
                        help="exclude first N observed pairs per session from latency statistics")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = report(args.folders, warmup=args.warmup)
        args.out.write_text(result, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
