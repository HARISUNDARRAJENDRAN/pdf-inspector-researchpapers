# Research-paper fidelity audit

This benchmark asks a narrower and more useful question than “does the
Markdown look plausible?”:

> How faithfully does the parser recover the structure and reading order of
> native-text research papers, compared with the structured source from which
> those papers were published?

The audit is deterministic. It does **not** call an LLM, OCR service, or layout
model. The production parser remains Rust-only and model-free.

## Default corpus

A normal run selects 100 papers:

- **60 arXiv papers**, evenly distributed across ten categories: NLP, machine
  learning, computer vision, software engineering, numerical mathematics,
  probability, statistics, computational physics, computational neuroscience,
  and econometrics.
- **40 PubMed Central Open Access papers**, selected across distinct journals
  and publisher templates rather than one site or one discipline.

The selector uses fixed 2024 date windows and stable sorting so repeated runs
remain comparable. arXiv contributes official HTML when available, otherwise
the official source archive. PubMed Central contributes publisher JATS XML.
The PDFs and source packages are downloaded during CI and are not committed or
uploaded as benchmark artifacts.

## What is measured

The benchmark independently scores:

- body-text recall and full-document precision;
- adjacent-word bigrams as a reading-order signal;
- paragraph-boundary recovery;
- heading recovery;
- caption recovery;
- table content plus row/column shape;
- mathematical-expression token and operator recovery;
- end-of-document recall to catch truncation;
- glued and spuriously split words;
- local duplicate/repeated output;
- replacement-character and encoding failures;
- parser wall time and milliseconds per page.

The component scores are more important than the composite. The weighted
`overall_score` is a triage tool for ranking failures, not a universal claim
that one number represents human reading.

## Ground-truth limitations

Structured source is substantially stronger than comparing one PDF extractor
to another, but it is not perfect:

- publisher XML can normalize references, symbols, or author metadata
  differently from the final PDF;
- arXiv HTML may reflect a newer conversion of the submitted TeX;
- LaTeX-source fallback is marked `heuristic_source` when Pandoc cannot produce
  a structured reference;
- figures contain visual information that text-only source comparison cannot
  fully score;
- equations can be semantically equivalent despite different serialization.

Results therefore preserve `reference_kind` and `reference_quality` for every
paper. Claims should be based primarily on `publisher_xml`, `arxiv_html`, and
`pandoc_source` rows, with heuristic-source rows treated as diagnostic only.

## Compared implementations

Each paper is processed by:

1. the fork's standard `process_pdf` path;
2. the fork's trusted native-text `process_research_pdf` path;
3. the latest upstream `firecrawl/pdf-inspector` standard CLI built in the same
   GitHub Actions job.

The same PDF bytes and source reference are used for every mode. The trusted
path must preserve quality while removing redundant classification work.

## 200-page scaling test

The workflow also builds a deterministic mixed-template 200-page PDF by
concatenating pages from the downloaded corpus. It records one warm-up and
three measured samples for the standard and trusted paths.

This stress pack measures scaling and latency only. It is not used as fidelity
ground truth because concatenation changes document-level semantics.

The ambitious 20–100 ms target for 200 pages is treated as a hypothesis, not a
promise. The benchmark reports the actual number and the per-page slope.

## Running locally

```bash
python3 -m pip install -r benchmarks/research_fidelity/requirements.txt
python3 -m unittest benchmarks/research_fidelity/test_audit.py
cargo build --release --bin research-audit

python3 benchmarks/research_fidelity/audit.py select \
  --arxiv 60 --pmc 40 --out /tmp/research-audit/manifest.json

python3 benchmarks/research_fidelity/audit.py download \
  --manifest /tmp/research-audit/manifest.json \
  --root /tmp/research-audit/corpus

python3 benchmarks/research_fidelity/audit.py evaluate \
  --manifest /tmp/research-audit/manifest.json \
  --root /tmp/research-audit/corpus \
  --fork-binary target/release/research-audit \
  --upstream-binary /path/to/upstream/target/release/pdf2md \
  --out /tmp/research-audit/results.jsonl

python3 benchmarks/research_fidelity/audit.py summarize \
  --results /tmp/research-audit/results.jsonl \
  --out-dir /tmp/research-audit/report
```

GitHub Actions publishes only the manifest, per-document metrics, aggregate
report, environment metadata, and 200-page timing result. Copyrighted PDFs and
source packages remain ephemeral on the runner.

## Acceptance rule for parser changes

A change is a candidate for production only when it:

1. improves a repeatable failure cluster rather than one hand-picked paper;
2. adds a minimal synthetic regression fixture for the underlying PDF pattern;
3. shows no material regression on the broad corpus or existing snapshots;
4. keeps the trusted-path median latency within the configured gate;
5. passes formatting, strict Clippy, Rust tests, WASM checks, and the static
   browser build.

A visually appealing output on one paper is not sufficient evidence.
