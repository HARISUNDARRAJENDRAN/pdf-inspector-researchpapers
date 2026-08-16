# arXiv HTML/source alignment gate.
#
# The /html/<id> endpoint is normally the LaTeXML rendering of the same source
# as the PDF, but some submissions contain ancillary documents (for example an
# author response) that can become the rendered HTML while the downloadable PDF
# remains the paper. A source-derived benchmark must not compare those two
# different documents. Keep the HTML only when its article title and lexical
# mass agree with the selected paper; otherwise fetch the official e-print
# source archive and mark the mismatch in the manifest.

_download_arxiv_before_alignment = download_arxiv


def arxiv_reference_alignment(
    reference: ReferenceDocument,
    paper: dict[str, Any],
    page_count: int,
) -> tuple[bool, str]:
    rapidfuzz = require_dependency("rapidfuzz")
    expected_title = clean_display_text(paper.get("title") or "")
    actual_title = clean_display_text(reference.title)
    title_score = (
        rapidfuzz.fuzz.token_set_ratio(expected_title.casefold(), actual_title.casefold())
        if expected_title and actual_title
        else 0.0
    )
    core_words = len(word_tokens(reference.core_text))

    # Even formula-heavy research papers carry materially more than a few
    # dozen prose words per rendered page. The floor is deliberately lax: its
    # job is to reject a short rebuttal/supplement paired with a long paper, not
    # to grade the paper's writing density.
    minimum_words = max(500, page_count * 70)
    title_ok = title_score >= 82.0
    length_ok = core_words >= minimum_words
    if title_ok and length_ok:
        return True, (
            f"aligned: title={title_score:.1f}, core_words={core_words}, "
            f"minimum_words={minimum_words}"
        )
    return False, (
        f"HTML/PDF mismatch: title={title_score:.1f}, core_words={core_words}, "
        f"minimum_words={minimum_words}"
    )


def _download_arxiv_source(
    session: Any,
    source_id: str,
    destination: pathlib.Path,
) -> None:
    bare_id = re.sub(r"v\d+$", "", source_id)
    resumable_download(
        session,
        [
            f"https://arxiv.org/e-print/{source_id}",
            f"https://export.arxiv.org/e-print/{source_id}",
            f"https://arxiv.org/e-print/{bare_id}",
        ],
        destination,
        validator=source_archive_valid,
    )


def download_arxiv(session: Any, paper: dict[str, Any], directory: pathlib.Path) -> None:
    _download_arxiv_before_alignment(session, paper, directory)
    html_path = directory / "reference.html"
    if not html_path.exists():
        return

    pdf_path = directory / "paper.pdf"
    try:
        reference = parse_arxiv_html(html_path)
        page_count = count_pdf_pages(pdf_path)
        aligned, reason = arxiv_reference_alignment(reference, paper, page_count)
    except Exception as exc:
        aligned = False
        reason = f"HTML reference parse failed: {exc}"

    paper["arxiv_html_alignment"] = reason
    if aligned:
        paper["reference_kind"] = "arxiv_html"
        return

    source_path = directory / "source.bin"
    _download_arxiv_source(session, paper["source_id"], source_path)
    paper["reference_kind"] = "latex_source"
