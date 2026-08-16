# Structured-source refinements loaded after the provider-specific parsers.
#
# Full-source text is used only as the precision vocabulary, so include author
# blocks, affiliations, permissions, and references that legitimately appear in
# the PDF. Body/core text remains the stricter recall target. LaTeXML represents
# many display equations with HTML <table> elements; those are equation layout,
# not research-paper data tables, and must not enter the table-structure score.

_parse_arxiv_html_base = parse_arxiv_html
_parse_pmc_jats_base = parse_pmc_jats


def parse_arxiv_html(path: pathlib.Path) -> ReferenceDocument:
    reference = _parse_arxiv_html_base(path)
    _, html_lib = lxml_modules()
    document = html_lib.fromstring(path.read_bytes())
    article_nodes = document.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_document ')]"
    )
    if article_nodes:
        reference.full_text = element_text(article_nodes[0])

    data_tables: list[list[list[str]]] = []
    candidates = document.xpath(
        "//table[not(contains(concat(' ', normalize-space(@class), ' '), ' ltx_eqn_table ')) "
        "and not(contains(concat(' ', normalize-space(@class), ' '), ' ltx_equation ')) "
        "and not(ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_equation ')])]"
    )
    for table in candidates:
        rows: list[list[str]] = []
        for row in table.xpath(".//tr"):
            cells = [element_text(cell) for cell in row.xpath("./th | ./td")]
            if any(cells):
                rows.append(cells)
        if rows:
            data_tables.append(rows)
    reference.tables = data_tables
    return reference


def parse_pmc_jats(path: pathlib.Path) -> ReferenceDocument:
    reference = _parse_pmc_jats_base(path)
    etree, _ = lxml_modules()
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(path.read_bytes(), parser=parser)
    reference.full_text = element_text(root)
    return reference
