"""Summarize detection_timing records from a server log, grouped by condition."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


def percentile(values, percent):
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent / 100
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def summarize(lines):
    groups = defaultdict(list)
    for number, line in enumerate(lines, 1):
        if "detection_timing " not in line:
            continue
        try:
            row = json.loads(line.split("detection_timing ", 1)[1])
            timings = row["timings_ms"]
            if "total_ms" not in timings or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v >= 0 for v in timings.values()
            ):
                raise ValueError("invalid timings_ms")
            key = tuple(row[k] for k in ("session_id", "calibration_profile", "algorithm", "commit"))
            groups[key].append(timings)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"invalid detection_timing record at line {number}: {exc}") from exc
    if not groups:
        raise ValueError("no detection_timing records found")
    output = ["# Server processing times", "",
              "Successful bundles only; excludes HTTP parsing, serialization and network latency.", ""]
    for key, records in sorted(groups.items()):
        output += [f"## {' / '.join(str(v) for v in key)}", "", f"Bundles: {len(records)}", "",
                   "| Stage | Samples | Mean ms | p50 ms | p90 ms | p95 ms | Max ms |",
                   "| --- | --- | --- | --- | --- | --- | --- |"]
        for stage in sorted({k for row in records for k in row}):
            values = [row[stage] for row in records if stage in row]
            output.append(f"| {stage} | {len(values)} | {mean(values):.3f} | "
                          f"{percentile(values, 50):.3f} | {percentile(values, 90):.3f} | "
                          f"{percentile(values, 95):.3f} | {max(values):.3f} |")
        output.append("")
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        with args.log.open(encoding="utf-8-sig") as source:
            report = summarize(source)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
