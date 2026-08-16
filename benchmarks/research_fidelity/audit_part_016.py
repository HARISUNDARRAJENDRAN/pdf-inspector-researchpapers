# Correctly scope arXiv HTML references to the LaTeXML article.
#
# The arXiv HTML shell contains accessibility/reporting modals outside the
# paper. It also decorates the article element with layout classes such as
# `ltx_authors_1line`; substring checks for `ltx_authors` therefore excluded
# the entire paper and retained only the modal. All source truth below is
# article-scoped and class checks operate on exact whitespace-separated tokens.


def _class_tokens(node: Any) -> set[str]:
    return set((node.attrib.get("class") or "").split())


def _has_class(node: Any, token: str) -> bool:
    return token in _class_tokens(node)


def _has_ancestor_class(node: Any, token: str, *, include_self: bool = True) -> bool:
    candidates = [node, *node.iterancestors()] if include_self else node.iterancestors()
    return any(_has_class(candidate, token) for candidate in candidates)


def _arxiv_article(document: Any) -> Any:
    articles = document.xpath(
        "//article[contains(concat(' ', normalize-space(@class), ' '), ' ltx_document ')]"
    )
    if not articles:
        articles = document.xpath(
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_document ')]"
        )
    if not articles:
        raise AuditError("arXiv HTML contains no LaTeXML article")
    return max(articles, key=lambda node: len(element_text(node)))


def _is_arxiv_equation_table(node: Any) -> bool:
    equation_classes = {
        "ltx_eqn_table",
        "ltx_equation",
        "ltx_equationgroup",
        "ltx_eqn_row",
    }
    return any(
        bool(_class_tokens(candidate) & equation_classes)
        for candidate in [node, *node.iterancestors()]
    )


def _is_arxiv_core_prose(node: Any) -> bool:
    if _has_ancestor_class(node, "ltx_bibliography"):
        return False
    if _has_ancestor_class(node, "ltx_authors"):
        return False
    if any(local_name(ancestor.tag) in {"table", "figure", "figcaption"} for ancestor in node.iterancestors()):
        return False
    return True


def parse_arxiv_html(path: pathlib.Path) -> ReferenceDocument:
    _, html_lib = lxml_modules()
    document = html_lib.fromstring(path.read_bytes())
    article = _arxiv_article(document)

    title_nodes = article.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_title_document ')]"
    )
    if not title_nodes:
        title_nodes = article.xpath(".//h1[1]")
    title = element_text(title_nodes[0]) if title_nodes else ""

    heading_nodes = article.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6")
    headings = unique_nonempty(element_text(node) for node in heading_nodes)

    paragraph_nodes = [
        node
        for node in article.xpath(".//p")
        if _is_arxiv_core_prose(node)
    ]
    paragraphs = unique_nonempty(element_text(node) for node in paragraph_nodes)

    caption_nodes = article.xpath(
        ".//figcaption | .//*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_caption ')]"
    )
    captions = unique_nonempty(element_text(node) for node in caption_nodes)

    data_tables: list[list[list[str]]] = []
    data_table_nodes: list[Any] = []
    for table in article.xpath(".//table"):
        if _is_arxiv_equation_table(table):
            continue
        rows: list[list[str]] = []
        for row in table.xpath(".//tr"):
            cells = [element_text(cell) for cell in row.xpath("./th | ./td")]
            if any(cells):
                rows.append(cells)
        if rows:
            data_table_nodes.append(table)
            data_tables.append(rows)

    equations = unique_nonempty(
        (node.attrib.get("alttext") or element_text(node))
        for node in article.xpath(".//math")
    )

    # Build the high-confidence article body in DOM order. Bibliography entries
    # remain in full_text for precision, but are not required for body recall.
    data_table_ids = {id(table) for table in data_table_nodes}
    core_blocks: list[str] = []
    nodes = article.xpath(
        ".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6 | "
        ".//p | .//figcaption | .//table//tr | .//li[not(.//p)]"
    )
    for node in nodes:
        tag = local_name(node.tag)
        if tag == "p" and not _is_arxiv_core_prose(node):
            continue
        if tag == "tr":
            owner = next((ancestor for ancestor in node.iterancestors() if local_name(ancestor.tag) == "table"), None)
            if owner is None or id(owner) not in data_table_ids:
                continue
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and _has_ancestor_class(
            node, "ltx_bibliography"
        ):
            # The References heading is semantically useful even when the
            # individual citations are excluded from strict body recall.
            text = element_text(node)
            if text:
                core_blocks.append(text)
            continue
        text = element_text(node)
        if text:
            core_blocks.append(text)

    full_text = element_text(article)
    core_text = "\n".join(core_blocks)
    if len(word_tokens(core_text)) < 20:
        raise AuditError("arXiv article produced an implausibly small core reference")

    return ReferenceDocument(
        title=title,
        full_text=full_text,
        core_text=core_text,
        headings=headings,
        paragraphs=paragraphs,
        captions=captions,
        tables=data_tables,
        equations=equations,
        reference_kind="arxiv_html",
        reference_quality="structured_source",
    )


_parse_reference_before_arxiv_alignment = parse_reference


def parse_reference(paper: dict[str, Any], directory: pathlib.Path) -> ReferenceDocument:
    html_path = directory / "reference.html"
    source_path = directory / "source.bin"
    if paper.get("provider") == "arxiv" and html_path.exists():
        reference = parse_arxiv_html(html_path)
        page_count = int(paper.get("page_count") or count_pdf_pages(directory / "paper.pdf"))
        aligned, reason = arxiv_reference_alignment(reference, paper, page_count)
        paper["arxiv_html_alignment"] = reason
        if aligned:
            return reference
        if source_path.exists():
            return parse_latex_source(source_path)
        raise AuditError(reason)
    return _parse_reference_before_arxiv_alignment(paper, directory)
