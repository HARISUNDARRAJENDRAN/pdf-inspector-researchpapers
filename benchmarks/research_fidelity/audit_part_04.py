def build_stress_pdf(manifest: dict[str, Any], root: pathlib.Path, out: pathlib.Path, pages: int) -> int:
    pypdf = require_dependency("pypdf")
    writer = pypdf.PdfWriter()
    papers = [paper for paper in manifest["papers"] if paper.get("download_status") == "ok"]
    papers.sort(key=lambda paper: (paper["provider"], paper["source_id"]))
    added = 0
    for paper in papers:
        pdf_path = root / paper["id"] / "paper.pdf"
        try:
            reader = pypdf.PdfReader(str(pdf_path), strict=False)
            for page in reader.pages:
                writer.add_page(page)
                added += 1
                if added >= pages:
                    break
        except Exception as exc:
            print(f"stress pack skipped {paper['id']}: {exc}", file=sys.stderr)
        if added >= pages:
            break
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    return added


def command_stress(args: argparse.Namespace) -> None:
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    root = pathlib.Path(args.root)
    out_dir = pathlib.Path(args.out_dir)
    stress_pdf = out_dir / f"research-stress-{args.pages}p.pdf"
    page_count = build_stress_pdf(manifest, root, stress_pdf, args.pages)
    binary = pathlib.Path(args.fork_binary).resolve()
    results: dict[str, Any] = {
        "page_count": page_count,
        "pdf_bytes": stress_pdf.stat().st_size,
        "modes": {},
    }
    for mode in ("standard", "research"):
        run_json_command([str(binary), mode, str(stress_pdf)], timeout=600)
        samples = []
        for _ in range(args.repeats):
            payload, external_ms = run_json_command(
                [str(binary), mode, str(stress_pdf)], timeout=600
            )
            wall_ns = payload.get("wall_time_ns")
            samples.append(float(wall_ns) / 1_000_000.0 if wall_ns else external_ms)
        results["modes"][mode] = {
            "samples_ms": samples,
            "median_ms": statistics.median(samples),
            "ms_per_page": statistics.median(samples) / max(1, page_count),
        }
    standard = results["modes"]["standard"]["median_ms"]
    research = results["modes"]["research"]["median_ms"]
    results["research_speedup_fraction"] = (standard - research) / max(1e-9, standard)
    atomic_write(out_dir / "stress.json", json.dumps(results, indent=2).encode())
    print(json.dumps(results, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    select = sub.add_parser("select", help="select a diverse deterministic corpus")
    select.add_argument("--arxiv", type=int, default=60)
    select.add_argument("--pmc", type=int, default=40)
    select.add_argument("--out", required=True)
    select.set_defaults(func=command_select)

    download = sub.add_parser("download", help="download PDFs and source references")
    download.add_argument("--manifest", required=True)
    download.add_argument("--root", required=True)
    download.set_defaults(func=command_download)

    evaluate = sub.add_parser("evaluate", help="run parsers and calculate fidelity metrics")
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--root", required=True)
    evaluate.add_argument("--fork-binary", required=True)
    evaluate.add_argument("--upstream-binary")
    evaluate.add_argument("--out", required=True)
    evaluate.add_argument("--resume", action="store_true")
    evaluate.set_defaults(func=command_evaluate)

    summarize = sub.add_parser("summarize", help="aggregate failure clusters")
    summarize.add_argument("--results", required=True)
    summarize.add_argument("--out-dir", required=True)
    summarize.set_defaults(func=command_summarize)

    stress = sub.add_parser("stress", help="build and time a mixed 200-page stress PDF")
    stress.add_argument("--manifest", required=True)
    stress.add_argument("--root", required=True)
    stress.add_argument("--fork-binary", required=True)
    stress.add_argument("--out-dir", required=True)
    stress.add_argument("--pages", type=int, default=200)
    stress.add_argument("--repeats", type=int, default=3)
    stress.set_defaults(func=command_stress)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (AuditError, subprocess.TimeoutExpired) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
