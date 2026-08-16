# LaTeX-source conversion overrides.
#
# Running Pandoc on an arXiv root file lets it recursively follow the original
# include graph. A malformed or macro-heavy submission can therefore spend
# minutes in conversion even though `inline_tex` has already produced the
# complete source text we need. Feed that inlined text through stdin under a
# short, hard timeout; on any failure, fall back to a bounded regex-based
# projection. Both paths preserve blank-line paragraph boundaries.


def _normalize_plain_blocks(text: str) -> str:
    text = html_module.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n+", text):
        normalized = " ".join(block.replace("\u00a0", " ").split())
        if normalized:
            blocks.append(normalized)
    return "\n\n".join(blocks)


def _heuristic_latex_plain(source: str) -> str:
    text = source
    # Keep the article body when a normal document environment is present.
    body_match = re.search(
        r"\\begin\{document\}(.*?)\\end\{document\}",
        text,
        flags=re.DOTALL,
    )
    if body_match:
        text = body_match.group(1)

    # Structural commands become paragraph boundaries rather than disappearing.
    for command in (
        "part",
        "chapter",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "title",
    ):
        text = re.sub(
            r"\\" + command + r"\*?(?:\[[^\]]*\])?\{([^{}]*)\}",
            r"\n\n\1\n\n",
            text,
        )

    # Common inline formatting commands are semantically transparent.
    unwrap = (
        "textbf",
        "textit",
        "emph",
        "textrm",
        "textsf",
        "texttt",
        "underline",
        "mbox",
        "mathrm",
        "mathbf",
        "mathit",
        "operatorname",
        "caption",
    )
    unwrap_pattern = re.compile(
        r"\\(?:" + "|".join(unwrap) + r")\*?\{([^{}]*)\}"
    )
    for _ in range(8):
        updated = unwrap_pattern.sub(r"\1", text)
        if updated == text:
            break
        text = updated

    # References carry little lexical ground truth and their command arguments
    # are identifiers rather than visible text.
    text = re.sub(
        r"\\(?:cite|citep|citet|citeauthor|citeyear|ref|eqref|pageref|label)\*?"
        r"(?:\[[^\]]*\])?\{[^{}]*\}",
        " ",
        text,
    )
    text = re.sub(
        r"\\(?:usepackage|documentclass|bibliography|bibliographystyle|includegraphics)"
        r"(?:\[[^\]]*\])?\{[^{}]*\}",
        " ",
        text,
    )
    text = re.sub(r"\\begin\{(?:abstract|quote|quotation|itemize|enumerate)\}", "\n\n", text)
    text = re.sub(r"\\end\{(?:abstract|quote|quotation|itemize|enumerate)\}", "\n\n", text)
    text = re.sub(r"\\item(?:\[[^\]]*\])?", "\n\n", text)
    text = re.sub(r"\\par\b", "\n\n", text)
    text = text.replace("\\\\", "\n")
    text = text.replace("~", " ")

    # Preserve the textual payload of simple math while discarding delimiters.
    text = re.sub(r"\$\$?", " ", text)
    text = re.sub(r"\\\[|\\\]|\\\(|\\\)", " ", text)
    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", "\n\n", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return _normalize_plain_blocks(text)


def latex_to_plain(tex_path: pathlib.Path, source: str) -> tuple[str, str]:
    pandoc = shutil.which("pandoc")
    if pandoc:
        try:
            completed = subprocess.run(
                [pandoc, "--from=latex", "--to=plain", "--wrap=none"],
                input=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
                check=False,
                cwd=str(tex_path.parent),
            )
            plain = _normalize_plain_blocks(completed.stdout)
            if completed.returncode == 0 and len(plain) > 1_000:
                return plain, "pandoc_source"
        except (OSError, subprocess.SubprocessError):
            pass
    return _heuristic_latex_plain(source), "heuristic_source"
