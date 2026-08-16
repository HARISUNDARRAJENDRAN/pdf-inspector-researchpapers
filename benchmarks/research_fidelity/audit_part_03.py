def run_json_command(command: Sequence[str], timeout: int = 300) -> tuple[dict[str, Any], float]:
    start = time.perf_counter_ns()
    completed = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000.0
    stdout = completed.stdout.strip()
    if not stdout:
        raise AuditError(
            f"command produced no JSON (exit={completed.returncode}): {' '.join(command)}\n{completed.stderr[-1000:]}"
        )
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise AuditError(
            f"invalid JSON from {' '.join(command)}: {stdout[-1000:]}\n{completed.stderr[-1000:]}"
        ) from exc
    if completed.returncode != 0 or payload.get("error"):
        raise AuditError(str(payload.get("error") or completed.stderr[-1000:]))
    return payload, elapsed_ms


def evaluate_one_mode(
    mode: str,
    paper: dict[str, Any],
    pdf_path: pathlib.Path,
    reference: ReferenceDocument,
    fork_binary: pathlib.Path,
    upstream_binary: pathlib.Path | None,
) -> dict[str, Any]:
    if mode == "fork_standard":
        command = [str(fork_binary), "standard", str(pdf_path)]
    elif mode == "fork_research":
        command = [str(fork_binary), "research", str(pdf_path)]
    elif mode == "upstream_standard":
        if upstream_binary is None:
            raise AuditError("upstream binary not configured")
        command = [str(upstream_binary), str(pdf_path), "--json"]
    else:
        raise AuditError(f"unknown mode {mode}")
    payload, external_wall_ms = run_json_command(command)
    markdown = payload.get("markdown") or ""
    metrics = calculate_metrics(reference, markdown)
    reported = payload.get("reported_time_ms", payload.get("processing_time_ms"))
    wall_ns = payload.get("wall_time_ns")
    parser_wall_ms = (float(wall_ns) / 1_000_000.0) if wall_ns is not None else external_wall_ms
    page_count = int(payload.get("page_count") or paper.get("page_count") or 0)
    return {
        "paper_id": paper["id"],
        "source_id": paper["source_id"],
        "provider": paper["provider"],
        "category": paper.get("category"),
        "journal": paper.get("journal"),
        "title": paper.get("title"),
        "reference_kind": reference.reference_kind,
        "reference_quality": reference.reference_quality,
        "mode": mode,
        "page_count": page_count,
        "pdf_bytes": paper.get("pdf_bytes"),
        "parser_wall_ms": parser_wall_ms,
        "external_wall_ms": external_wall_ms,
        "reported_time_ms": reported,
        "ms_per_page": parser_wall_ms / max(1, page_count),
        "markdown_length": len(markdown),
        "pdf_type": payload.get("pdf_type"),
        "has_encoding_issues": payload.get("has_encoding_issues"),
        "pages_needing_ocr": payload.get("pages_needing_ocr", []),
        "pages_with_tables": payload.get("pages_with_tables", []),
        "pages_with_columns": payload.get("pages_with_columns", []),
        **metrics,
    }


def command_evaluate(args: argparse.Namespace) -> None:
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    root = pathlib.Path(args.root)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fork_binary = pathlib.Path(args.fork_binary).resolve()
    upstream_binary = pathlib.Path(args.upstream_binary).resolve() if args.upstream_binary else None
    modes = ["fork_standard", "fork_research"]
    if upstream_binary:
        modes.append("upstream_standard")
    completed_ids: set[tuple[str, str]] = set()
    if out.exists() and args.resume:
        for line in out.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            completed_ids.add((row.get("paper_id"), row.get("mode")))
    with out.open("a", encoding="utf-8") as handle:
        for index, paper in enumerate(manifest["papers"], 1):
            if paper.get("download_status") != "ok":
                continue
            directory = root / paper["id"]
            pdf_path = directory / "paper.pdf"
            print(f"[{index}/{len(manifest['papers'])}] reference {paper['id']}", flush=True)
            try:
                reference = parse_reference(paper, directory)
                atomic_write(
                    directory / "reference.json",
                    json.dumps(reference_to_json(reference), indent=2, ensure_ascii=False).encode(),
                )
            except Exception as exc:
                error_row = {
                    "paper_id": paper["id"],
                    "provider": paper["provider"],
                    "mode": "reference",
                    "error": str(exc),
                }
                handle.write(json.dumps(error_row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"reference failed for {paper['id']}: {exc}", file=sys.stderr)
                continue
            for mode in modes:
                if (paper["id"], mode) in completed_ids:
                    continue
                try:
                    row = evaluate_one_mode(
                        mode,
                        paper,
                        pdf_path,
                        reference,
                        fork_binary,
                        upstream_binary,
                    )
                except Exception as exc:
                    row = {
                        "paper_id": paper["id"],
                        "source_id": paper["source_id"],
                        "provider": paper["provider"],
                        "mode": mode,
                        "error": str(exc),
                    }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                if "error" not in row:
                    print(
                        f"  {mode}: score={row['overall_score']:.4f} time={row['parser_wall_ms']:.1f}ms",
                        flush=True,
                    )
                else:
                    print(f"  {mode} failed: {row['error']}", file=sys.stderr)


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def paired_rows(rows: Sequence[dict[str, Any]], left: str, right: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_key = {(row["paper_id"], row["mode"]): row for row in rows}
    pairs = []
    for paper_id in {row["paper_id"] for row in rows}:
        a = by_key.get((paper_id, left))
        b = by_key.get((paper_id, right))
        if a and b:
            pairs.append((a, b))
    return pairs


def format_float(value: float) -> str:
    return f"{value:.4f}"


def aggregate_mode(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        "overall_score",
        "word_f1",
        "bigram_f1",
        "sequence_similarity",
        "heading_f1",
        "table_score",
        "equation_score",
        "caption_f1",
        "tail_recall",
        "cleanliness",
    ]
    result: dict[str, Any] = {"documents": len(rows)}
    for metric in metrics:
        values = [float(row[metric]) for row in rows if row.get(metric) is not None]
        result[f"mean_{metric}"] = statistics.fmean(values) if values else 0.0
        result[f"p10_{metric}"] = percentile(values, 0.10)
        result[f"median_{metric}"] = statistics.median(values) if values else 0.0
    times = [float(row["parser_wall_ms"]) for row in rows]
    result["median_time_ms"] = statistics.median(times) if times else 0.0
    result["p90_time_ms"] = percentile(times, 0.90)
    per_page = [float(row["ms_per_page"]) for row in rows]
    result["median_ms_per_page"] = statistics.median(per_page) if per_page else 0.0
    failures = collections.Counter(
        label for row in rows for label in row.get("failure_labels", [])
    )
    result["failure_counts"] = dict(failures)
    return result


def command_summarize(args: argparse.Namespace) -> None:
    rows = []
    errors = []
    for line in pathlib.Path(args.results).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error"):
            errors.append(row)
        elif row.get("mode") != "reference":
            rows.append(row)
    by_mode: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)
    summary = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modes": {mode: aggregate_mode(mode_rows) for mode, mode_rows in sorted(by_mode.items())},
        "errors": errors,
    }
    comparisons = {}
    for left, right, label in [
        ("upstream_standard", "fork_standard", "fork_vs_upstream"),
        ("fork_standard", "fork_research", "research_vs_fork_standard"),
    ]:
        pairs = paired_rows(rows, left, right)
        if not pairs:
            continue
        score_delta = [b["overall_score"] - a["overall_score"] for a, b in pairs]
        speed_delta = [
            (b["parser_wall_ms"] - a["parser_wall_ms"]) / max(1e-9, a["parser_wall_ms"])
            for a, b in pairs
        ]
        comparisons[label] = {
            "pairs": len(pairs),
            "mean_score_delta": statistics.fmean(score_delta),
            "median_score_delta": statistics.median(score_delta),
            "improved_documents": sum(delta > 1e-5 for delta in score_delta),
            "regressed_documents": sum(delta < -1e-5 for delta in score_delta),
            "median_latency_delta_fraction": statistics.median(speed_delta),
        }
    summary["comparisons"] = comparisons
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(out_dir / "summary.json", json.dumps(summary, indent=2).encode())

    fieldnames = sorted({key for row in rows for key in row.keys() if not isinstance(row.get(key), (list, dict))})
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    failure_counts = collections.Counter(label for row in rows for label in row.get("failure_labels", []))
    worst = sorted(rows, key=lambda row: row["overall_score"])[:25]
    slowest = sorted(rows, key=lambda row: row["parser_wall_ms"], reverse=True)[:25]
    report: list[str] = [
        "# Research-paper fidelity audit",
        "",
        f"Evaluated {len(rows)} parser/document combinations across {len({row['paper_id'] for row in rows})} papers.",
        "",
        "## Aggregate metrics",
        "",
        "| Mode | Docs | Overall | Word F1 | Order bigram F1 | Tables | Equations | Median ms | Median ms/page |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, values in summary["modes"].items():
        report.append(
            "| {mode} | {documents} | {overall} | {word} | {order} | {tables} | {equations} | {time:.1f} | {per_page:.3f} |".format(
                mode=mode,
                documents=values["documents"],
                overall=format_float(values["mean_overall_score"]),
                word=format_float(values["mean_word_f1"]),
                order=format_float(values["mean_bigram_f1"]),
                tables=format_float(values["mean_table_score"]),
                equations=format_float(values["mean_equation_score"]),
                time=values["median_time_ms"],
                per_page=values["median_ms_per_page"],
            )
        )
    report.extend(["", "## Failure clusters", "", "| Failure | Count |", "|---|---:|"])
    for label, count in failure_counts.most_common():
        report.append(f"| {label} | {count} |")
    report.extend(
        [
            "",
            "## Pairwise comparisons",
            "",
            "| Comparison | Pairs | Mean score delta | Improved | Regressed | Median latency delta |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label, values in comparisons.items():
        report.append(
            f"| {label} | {values['pairs']} | {values['mean_score_delta']:+.5f} | "
            f"{values['improved_documents']} | {values['regressed_documents']} | "
            f"{values['median_latency_delta_fraction']:+.2%} |"
        )
    report.extend(
        [
            "",
            "## Lowest-scoring outputs",
            "",
            "| Paper | Mode | Provider | Pages | Score | Word F1 | Order F1 | Table | Equation | Failures |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in worst:
        report.append(
            f"| {row['paper_id']} | {row['mode']} | {row['provider']} | {row['page_count']} | "
            f"{row['overall_score']:.4f} | {row['word_f1']:.4f} | {row['bigram_f1']:.4f} | "
            f"{row['table_score']:.4f} | {row['equation_score']:.4f} | "
            f"{', '.join(row.get('failure_labels', []))} |"
        )
    report.extend(
        [
            "",
            "## Slowest outputs",
            "",
            "| Paper | Mode | Pages | Time ms | ms/page | PDF MB |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in slowest:
        report.append(
            f"| {row['paper_id']} | {row['mode']} | {row['page_count']} | "
            f"{row['parser_wall_ms']:.1f} | {row['ms_per_page']:.3f} | "
            f"{(row.get('pdf_bytes') or 0) / 1_000_000:.2f} |"
        )
    if errors:
        report.extend(["", "## Errors", "", "```json", json.dumps(errors, indent=2), "```"])
    atomic_write(out_dir / "report.md", ("\n".join(report) + "\n").encode())
    print(f"wrote summary to {out_dir}")

