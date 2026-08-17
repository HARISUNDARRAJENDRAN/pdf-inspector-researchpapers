#!/usr/bin/env python3
"""Compare a candidate parser against the current main branch.

The source-grounded audit intentionally writes rich JSONL rather than one
headline score.  This gate locates the research-fast-path metric object in each
record, aggregates every important fidelity dimension, and rejects silent
trade-offs.  A separate paired latency mode alternates execution order on the
same generated 200-page paper.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import subprocess
import sys
from collections.abc import Iterable
from typing import Any

QUALITY_METRICS = (
    "overall_score",
    "word_precision",
    "word_recall",
    "word_f1",
    "bigram_precision",
    "bigram_recall",
    "bigram_f1",
    "sequence_similarity",
    "paragraph_precision",
    "paragraph_recall",
    "paragraph_f1",
    "heading_precision",
    "heading_recall",
    "heading_f1",
    "caption_recall",
    "caption_f1",
    "table_score",
    "equation_score",
    "tail_recall",
    "cleanliness",
)

# A candidate may improve a targeted structure metric while leaving the large
# aggregate nearly unchanged, but it may not purchase that gain by degrading a
# different core dimension.  Tolerances are absolute score points.
REGRESSION_LIMITS = {
    "overall_score": 0.00020,
    "word_precision": 0.00150,
    "word_recall": 0.00150,
    "word_f1": 0.00150,
    "bigram_f1": 0.00200,
    "sequence_similarity": 0.00200,
    "paragraph_f1": 0.00250,
    "heading_f1": 0.00250,
    "caption_f1": 0.00250,
    "table_score": 0.00200,
    "equation_score": 0.00200,
    "tail_recall": 0.00200,
    "cleanliness": 0.00200,
}

TARGET_GAINS = {
    "overall_score": 0.00015,
    "word_f1": 0.00100,
    "bigram_f1": 0.00150,
    "paragraph_f1": 0.00400,
    "heading_f1": 0.00400,
    "caption_f1": 0.00400,
    "table_score": 0.00300,
    "equation_score": 0.00300,
    "cleanliness": 0.00300,
}


def metric_dicts(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], dict[str, Any]]]:
    if isinstance(value, dict):
        if isinstance(value.get("overall_score"), (int, float)):
            yield path, value
        for key, child in value.items():
            yield from metric_dicts(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from metric_dicts(child, (*path, str(index)))


def research_rank(path: tuple[str, ...]) -> tuple[int, int]:
    label = "/".join(path).casefold()
    score = 0
    if "research" in label:
        score += 20
    if "fork" in label or "candidate" in label:
        score += 8
    if "standard" in label:
        score -= 12
    if "upstream" in label or "firecrawl" in label:
        score -= 40
    # Prefer a more specific path when two objects have the same semantic rank.
    return score, len(path)


def select_research_metrics(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates = list(metric_dicts(record))
    if not candidates:
        raise RuntimeError("audit record contains no metric object with overall_score")
    path, metrics = max(candidates, key=lambda item: research_rank(item[0]))
    if research_rank(path)[0] <= 0:
        paths = ["/".join(candidate_path) for candidate_path, _ in candidates]
        raise RuntimeError(f"could not identify research fast-path metrics; candidates={paths}")
    return "/".join(path), metrics


def load_quality(path: pathlib.Path) -> tuple[dict[str, float], int, set[str]]:
    values: dict[str, list[float]] = {metric: [] for metric in QUALITY_METRICS}
    selected_paths: set[str] = set()
    count = 0
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        selected_path, metrics = select_research_metrics(record)
        selected_paths.add(selected_path)
        count += 1
        for metric in QUALITY_METRICS:
            value = metrics.get(metric)
            if isinstance(value, (int, float)):
                values[metric].append(float(value))
    if count == 0:
        raise RuntimeError(f"{path} contains no audit records")
    aggregate = {
        metric: statistics.fmean(metric_values)
        for metric, metric_values in values.items()
        if metric_values
    }
    if "overall_score" not in aggregate:
        raise RuntimeError(f"{path} contains no aggregate-able overall_score")
    return aggregate, count, selected_paths


def quality_command(args: argparse.Namespace) -> int:
    baseline, baseline_count, baseline_paths = load_quality(pathlib.Path(args.baseline))
    candidate, candidate_count, candidate_paths = load_quality(pathlib.Path(args.candidate))
    if baseline_count != candidate_count:
        raise RuntimeError(
            f"paper-count mismatch: baseline={baseline_count}, candidate={candidate_count}"
        )

    common = sorted(set(baseline) & set(candidate))
    deltas = {metric: candidate[metric] - baseline[metric] for metric in common}
    regressions = {
        metric: delta
        for metric, delta in deltas.items()
        if metric in REGRESSION_LIMITS and delta < -REGRESSION_LIMITS[metric]
    }
    meaningful_gains = {
        metric: delta
        for metric, delta in deltas.items()
        if metric in TARGET_GAINS and delta >= TARGET_GAINS[metric]
    }

    report = {
        "papers": candidate_count,
        "baseline_metric_paths": sorted(baseline_paths),
        "candidate_metric_paths": sorted(candidate_paths),
        "baseline": baseline,
        "candidate": candidate,
        "delta": deltas,
        "meaningful_gains": meaningful_gains,
        "regressions": regressions,
        "passed": not regressions and bool(meaningful_gains),
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(json.dumps(report, indent=2, sort_keys=True))
    if regressions:
        print("quality gate failed: material metric regression", file=sys.stderr)
        return 1
    if not meaningful_gains:
        print("quality gate failed: no measured significant gain", file=sys.stderr)
        return 1
    return 0


def parser_wall_time_ns(binary: str, pdf: str) -> int:
    completed = subprocess.run(
        [binary, "research", pdf],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = json.loads(completed.stdout)
    value = payload.get("wall_time_ns")
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{binary} did not emit a positive wall_time_ns")
    return value


def latency_command(args: argparse.Namespace) -> int:
    baseline_samples: list[int] = []
    candidate_samples: list[int] = []

    # Warm both binaries without recording. Alternating measured order then
    # limits cache, thermal, and CPU-frequency bias.
    for _ in range(args.warmups):
        parser_wall_time_ns(args.baseline_binary, args.pdf)
        parser_wall_time_ns(args.candidate_binary, args.pdf)

    for round_index in range(args.rounds):
        order = (
            ("baseline", args.baseline_binary),
            ("candidate", args.candidate_binary),
        )
        if round_index % 2:
            order = tuple(reversed(order))
        for label, binary in order:
            elapsed = parser_wall_time_ns(binary, args.pdf)
            if label == "baseline":
                baseline_samples.append(elapsed)
            else:
                candidate_samples.append(elapsed)

    baseline_median = statistics.median(baseline_samples)
    candidate_median = statistics.median(candidate_samples)
    ratio = candidate_median / baseline_median
    report = {
        "warmups": args.warmups,
        "rounds": args.rounds,
        "baseline_samples_ms": [value / 1_000_000 for value in baseline_samples],
        "candidate_samples_ms": [value / 1_000_000 for value in candidate_samples],
        "baseline_median_ms": baseline_median / 1_000_000,
        "candidate_median_ms": candidate_median / 1_000_000,
        "candidate_over_baseline": ratio,
        "delta_percent": (ratio - 1.0) * 100.0,
        "limit": args.max_ratio,
        "passed": ratio <= args.max_ratio,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    quality = subparsers.add_parser("quality")
    quality.add_argument("--baseline", required=True)
    quality.add_argument("--candidate", required=True)
    quality.add_argument("--out", required=True)
    quality.set_defaults(func=quality_command)

    latency = subparsers.add_parser("latency")
    latency.add_argument("--baseline-binary", required=True)
    latency.add_argument("--candidate-binary", required=True)
    latency.add_argument("--pdf", required=True)
    latency.add_argument("--rounds", type=int, default=12)
    latency.add_argument("--warmups", type=int, default=2)
    latency.add_argument("--max-ratio", type=float, default=1.01)
    latency.add_argument("--out", required=True)
    latency.set_defaults(func=latency_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
