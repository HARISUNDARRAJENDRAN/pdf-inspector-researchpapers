def lxml_modules() -> tuple[Any, Any]:
    return require_dependency("lxml.etree"), require_dependency("lxml.html")


def element_text(element: Any) -> str:
    if element is None:
        return ""
    parts: list[str] = []

    def visit(node: Any) -> None:
        local = node.tag.split("}")[-1] if isinstance(node.tag, str) else ""
        if local == "math":
            alt = node.attrib.get("alttext") or node.attrib.get("altimg")
            if alt:
                parts.append(alt)
                if node.tail:
                    parts.append(node.tail)
                return
            if node.text:
                parts.append(node.text)
            for child in node:
                visit(child)
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            visit(child)
        if node.tail:
            parts.append(node.tail)

    visit(element)
    return clean_display_text(" ".join(parts))


def unique_nonempty(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = clean_display_text(value)
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def parse_arxiv_html(path: pathlib.Path) -> ReferenceDocument:
    etree, html_lib = lxml_modules()
    document = html_lib.fromstring(path.read_bytes())
    title_nodes = document.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' ltx_title_document ')]"
    )
    if not title_nodes:
        title_nodes = document.xpath("//h1[1]")
    title = element_text(title_nodes[0]) if title_nodes else ""
    heading_nodes = document.xpath(
        "//h1 | //h2 | //h3 | //h4 | //h5 | //h6"
    )
    headings = unique_nonempty(element_text(node) for node in heading_nodes)
    paragraph_nodes = document.xpath(
        "//p[not(ancestor::table) and not(ancestor::figure) and "
        "not(ancestor::*[contains(@class,'ltx_bibliography')]) and "
        "not(ancestor::nav)]"
    )
    paragraphs = unique_nonempty(element_text(node) for node in paragraph_nodes)
    captions = unique_nonempty(
        element_text(node)
        for node in document.xpath("//figcaption | //*[@class='ltx_caption']")
    )
    tables: list[list[list[str]]] = []
    for table in document.xpath("//table"):
        rows: list[list[str]] = []
        for row in table.xpath(".//tr"):
            cells = [element_text(cell) for cell in row.xpath("./th | ./td")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    equations = unique_nonempty(
        (node.attrib.get("alttext") or element_text(node))
        for node in document.xpath("//math")
    )
    blocks: list[str] = []
    core_blocks: list[str] = []
    body_nodes = document.xpath(
        "//h1 | //h2 | //h3 | //h4 | //h5 | //h6 | "
        "//p[not(ancestor::table) and not(ancestor::figure)] | //figcaption | //table//tr"
    )
    for node in body_nodes:
        text = element_text(node)
        if not text:
            continue
        blocks.append(text)
        classes = " ".join(
            ancestor.attrib.get("class", "")
            for ancestor in [node, *node.iterancestors()]
        )
        if "ltx_bibliography" not in classes and "ltx_authors" not in classes:
            core_blocks.append(text)
    return ReferenceDocument(
        title=title,
        full_text="\n".join(blocks),
        core_text="\n".join(core_blocks),
        headings=headings,
        paragraphs=paragraphs,
        captions=captions,
        tables=tables,
        equations=equations,
        reference_kind="arxiv_html",
        reference_quality="structured_source",
    )


def local_name(tag: str) -> str:
    return tag.split("}")[-1]


def jats_xpath(root: Any, path: str) -> list[Any]:
    return root.xpath(path, namespaces={"mml": "http://www.w3.org/1998/Math/MathML"})


def parse_pmc_jats(path: pathlib.Path) -> ReferenceDocument:
    etree, _ = lxml_modules()
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(path.read_bytes(), parser=parser)
    title_nodes = jats_xpath(root, "//article-title")
    title = element_text(title_nodes[0]) if title_nodes else ""
    headings = unique_nonempty(
        element_text(node) for node in jats_xpath(root, "//body//sec/title")
    )
    paragraph_nodes = jats_xpath(
        root,
        "//abstract//p | //body//p[not(ancestor::table-wrap) and not(ancestor::fig)]",
    )
    paragraphs = unique_nonempty(element_text(node) for node in paragraph_nodes)
    captions = unique_nonempty(
        element_text(node)
        for node in jats_xpath(root, "//fig/caption | //table-wrap/caption")
    )
    tables: list[list[list[str]]] = []
    for table in jats_xpath(root, "//table-wrap//table"):
        rows: list[list[str]] = []
        for row in jats_xpath(table, ".//tr"):
            cells = [element_text(cell) for cell in jats_xpath(row, "./th | ./td")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    equations = unique_nonempty(
        element_text(node)
        for node in jats_xpath(root, "//disp-formula | //inline-formula")
    )
    full_blocks: list[str] = []
    core_blocks: list[str] = []
    nodes = jats_xpath(
        root,
        "//front//article-title | //abstract//p | //body//sec/title | "
        "//body//p[not(ancestor::table-wrap) and not(ancestor::fig)] | "
        "//fig/caption | //table-wrap/caption | //table-wrap//tr | //ref-list//ref",
    )
    for node in nodes:
        text = element_text(node)
        if not text:
            continue
        full_blocks.append(text)
        if not any(local_name(ancestor.tag) == "ref-list" for ancestor in node.iterancestors()):
            core_blocks.append(text)
    return ReferenceDocument(
        title=title,
        full_text="\n".join(full_blocks),
        core_text="\n".join(core_blocks),
        headings=headings,
        paragraphs=paragraphs,
        captions=captions,
        tables=tables,
        equations=equations,
        reference_kind="pmc_jats",
        reference_quality="publisher_xml",
    )


def safe_extract_tar(archive: tarfile.TarFile, destination: pathlib.Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        member_path = (destination / member.name).resolve()
        if destination not in member_path.parents and member_path != destination:
            raise AuditError(f"unsafe archive member {member.name}")
    archive.extractall(destination)


def unpack_source(source_path: pathlib.Path, destination: pathlib.Path) -> None:
    data = source_path.read_bytes()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            safe_extract_tar(archive, destination)
            return
    except tarfile.TarError:
        pass
    try:
        decompressed = gzip.decompress(data)
    except OSError:
        decompressed = data
    (destination / "main.tex").write_bytes(decompressed)


def strip_tex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        out: list[str] = []
        escaped = False
        for char in line:
            if char == "%" and not escaped:
                break
            out.append(char)
            if char == "\\":
                escaped = not escaped
            else:
                escaped = False
        lines.append("".join(out))
    return "\n".join(lines)


def find_tex_root(directory: pathlib.Path) -> pathlib.Path:
    tex_files = list(directory.rglob("*.tex"))
    if not tex_files:
        raise AuditError("arXiv source contains no .tex files")
    scored: list[tuple[int, int, pathlib.Path]] = []
    for path in tex_files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        score = 0
        score += 10 if "\\documentclass" in text else 0
        score += 5 if "\\begin{document}" in text else 0
        score += 2 if "\\title" in text else 0
        scored.append((score, len(text), path))
    if not scored:
        raise AuditError("unable to read arXiv .tex files")
    return max(scored, key=lambda item: (item[0], item[1], str(item[2])))[2]


def inline_tex(path: pathlib.Path, seen: set[pathlib.Path] | None = None, depth: int = 0) -> str:
    if depth > 12:
        return ""
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return ""
    seen.add(path)
    text = strip_tex_comments(path.read_text(errors="replace"))
    pattern = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")

    def replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        candidate = (path.parent / target)
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".tex")
        if candidate.exists():
            return inline_tex(candidate, seen, depth + 1)
        return ""

    return pattern.sub(replace, text)


def extract_balanced_command(text: str, command: str) -> list[str]:
    results: list[str] = []
    pattern = re.compile(r"\\" + re.escape(command) + r"\s*\{")
    for match in pattern.finditer(text):
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            if text[index] == "{" and (index == 0 or text[index - 1] != "\\"):
                depth += 1
            elif text[index] == "}" and (index == 0 or text[index - 1] != "\\"):
                depth -= 1
            index += 1
        if depth == 0:
            results.append(text[start : index - 1])
    return results


def latex_to_plain(tex_path: pathlib.Path, source: str) -> tuple[str, str]:
    pandoc = shutil.which("pandoc")
    if pandoc:
        completed = subprocess.run(
            [pandoc, "--from=latex", "--to=plain", "--wrap=none", tex_path.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=120,
            check=False,
            cwd=str(tex_path.parent),
        )
        if completed.returncode == 0 and len(completed.stdout) > 1000:
            return clean_display_text(completed.stdout), "pandoc_source"
    text = source
    text = re.sub(r"\\begin\{(?:document|abstract)\}|\\end\{(?:document|abstract)\}", "\n", text)
    text = re.sub(r"\\(?:cite|citep|citet|ref|eqref|label)\*?(?:\[[^\]]*\])?\{[^{}]*\}", " ", text)
    text = re.sub(r"\\(?:usepackage|documentclass|bibliography|bibliographystyle)(?:\[[^\]]*\])?\{[^{}]*\}", " ", text)
    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", "\n", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("~", " ").replace("\\\\", "\n")
    return clean_display_text(text), "heuristic_source"


def parse_latex_source(path: pathlib.Path) -> ReferenceDocument:
    with tempfile.TemporaryDirectory(prefix="research-source-") as tmp:
        directory = pathlib.Path(tmp)
        unpack_source(path, directory)
        root = find_tex_root(directory)
        source = inline_tex(root)
        title_values = extract_balanced_command(source, "title")
        title = clean_display_text(title_values[0]) if title_values else ""
        headings: list[str] = []
        for command in ("part", "chapter", "section", "subsection", "subsubsection"):
            headings.extend(clean_display_text(value) for value in extract_balanced_command(source, command))
        captions = unique_nonempty(extract_balanced_command(source, "caption"))
        equations: list[str] = []
        for env in ("equation", "equation*", "align", "align*", "gather", "gather*"):
            pattern = re.compile(
                r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}",
                re.DOTALL,
            )
            equations.extend(clean_display_text(match.group(1)) for match in pattern.finditer(source))
        equations.extend(clean_display_text(value) for value in re.findall(r"\$\$(.*?)\$\$", source, re.DOTALL))
        tables: list[list[list[str]]] = []
        for match in re.finditer(r"\\begin\{tabular\}\{([^{}]+)\}(.*?)\\end\{tabular\}", source, re.DOTALL):
            body = match.group(2)
            rows: list[list[str]] = []
            for row in re.split(r"\\\\", body):
                cells = [clean_display_text(re.sub(r"\\[A-Za-z@]+\*?", " ", cell).replace("{", "").replace("}", "")) for cell in row.split("&")]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables.append(rows)
        plain, quality = latex_to_plain(root, source)
        paragraphs = [clean_display_text(part) for part in re.split(r"\n\s*\n", plain) if len(clean_display_text(part)) >= 20]
        return ReferenceDocument(
            title=title,
            full_text=plain,
            core_text=plain,
            headings=unique_nonempty(headings),
            paragraphs=unique_nonempty(paragraphs),
            captions=captions,
            tables=tables,
            equations=unique_nonempty(equations),
            reference_kind="latex_source",
            reference_quality=quality,
        )


def reference_to_json(reference: ReferenceDocument) -> dict[str, Any]:
    return dataclasses.asdict(reference)


def parse_reference(paper: dict[str, Any], directory: pathlib.Path) -> ReferenceDocument:
    html_path = directory / "reference.html"
    xml_path = directory / "reference.xml"
    source_path = directory / "source.bin"
    if html_path.exists():
        return parse_arxiv_html(html_path)
    if xml_path.exists():
        return parse_pmc_jats(xml_path)
    if source_path.exists():
        return parse_latex_source(source_path)
    raise AuditError(f"no reference source for {paper['id']}")

