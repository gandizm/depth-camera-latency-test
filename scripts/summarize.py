#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Summarize rs2-latency-lab CSV samples without third-party packages."""

import argparse
import csv
from pathlib import Path
import re
import statistics
import sys


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def format_number(value):
    return "n/a" if value is None else f"{value:.2f}"


def summarize(path):
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    visual = [float(row["visual_latency_ms"]) for row in rows]
    arrival = [float(row["arrival_to_callback_ms"]) for row in rows
               if float(row["arrival_to_callback_ms"]) >= 0]
    domains = sorted({row["timestamp_domain"] for row in rows})
    metrics = {}
    log_path = path.with_suffix(".log")
    if log_path.exists():
        match = re.search(r"^SUMMARY (.+)$", log_path.read_text(
            encoding="utf-8", errors="replace"), re.MULTILINE)
        if match:
            for key, value in re.findall(r"(\w+)=([^ ]+)", match.group(1)):
                metrics[key] = value
    return {
        "run": path.stem,
        "samples": len(rows),
        "capture_fps": metrics.get("capture_fps"),
        "depth_fps": metrics.get("depth_fps"),
        "overwritten_frames": metrics.get("overwritten_frames"),
        "median_ms": statistics.median(visual) if visual else None,
        "p95_ms": percentile(visual, 0.95),
        "average_ms": statistics.fmean(visual) if visual else None,
        "arrival_median_ms": statistics.median(arrival) if arrival else None,
        "timestamp_domains": "+".join(domains) if domains else "n/a",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument(
        "--fail-on-empty", action="store_true",
        help="return status 2 if any run contains no accepted visual sample")
    args = parser.parse_args()

    summaries = [summarize(path)
                 for path in sorted(args.result_dir.glob("*.csv"))
                 if path.name != "summary.csv"]
    fields = ["run", "samples", "capture_fps", "depth_fps",
              "overwritten_frames", "median_ms", "p95_ms", "average_ms",
              "arrival_median_ms", "timestamp_domains"]

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            writer.writerows(summaries)

    lines = [
        "# Latency summary",
        "",
        "| Run | Samples | RGB/visual FPS | Depth FPS | Overwritten | "
        "Median ms | P95 ms | Average ms | "
        "Arrival→callback median ms | Timestamp domains |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in summaries:
        lines.append(
            f"| {item['run']} | {item['samples']} | "
            f"{item['capture_fps'] or 'n/a'} | "
            f"{item['depth_fps'] or 'n/a'} | "
            f"{item['overwritten_frames'] or 'n/a'} | "
            f"{format_number(item['median_ms'])} | "
            f"{format_number(item['p95_ms'])} | "
            f"{format_number(item['average_ms'])} | "
            f"{format_number(item['arrival_median_ms'])} | "
            f"{item['timestamp_domains']} |")
    document = "\n".join(lines) + "\n"
    if args.markdown:
        args.markdown.write_text(document, encoding="utf-8")
    print(document, end="")
    empty_runs = [item["run"] for item in summaries if item["samples"] == 0]
    if args.fail_on_empty and empty_runs:
        print(
            "Invalid latency runs (zero visual samples): "
            + ", ".join(empty_runs),
            file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
