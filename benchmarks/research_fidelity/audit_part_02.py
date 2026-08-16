def markdown_to_plain(markdown: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("|", " ")
    text = re.sub(r"[*_`~]", "", text)
    return clean_display_text(text)


def word_tokens(text: str) -> list[str]:
    regex = require_dependency("regex")
    normalized = unicodedata.normalize("NFKC", html_module.unescape(text)).casefold()
    pattern = regex.compile(
        r"\p{L}[\p{L}\p{M}\p{N}'’-]*|\p{N}+(?:[.,]\p{N}+)*",
        regex.VERSION1,
    )
    return [token.strip("'’-.,") for token in pattern.findall(normalized) if token.strip("'’-.,")]


def math_tokens(text: str) -> list[str]:
    regex = require_dependency("regex")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"\\(?:left|right|mathrm|mathbf|mathit|operatorname|text)\b", " ", normalized)
    normalized = re.sub(r"\\([A-Za-z]+)", r" \1 ", normalized)
    return regex.findall(
        r"\p{L}+[\p{L}\p{N}_]*|\p{N}+(?:\.\p{N}+)?|[=<>+\-*/^_∑∫√≈≠≤≥→←∞∈∉±]",
        normalized,
        flags=regex.VERSION1,
    )


def counter_prf(reference: Sequence[Any], predicted: Sequence[Any]) -> tuple[float, float, float]:
    ref_counter = collections.Counter(reference)
    pred_counter = collections.Counter(predicted)
    overlap = sum((ref_counter & pred_counter).values())
    recall = overlap / max(1, sum(ref_counter.values()))
    precision = overlap / max(1, sum(pred_counter.values()))
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return precision, recall, f1


def ngrams(tokens: Sequence[str], size: int) -> list[tuple[str, ...]]:
    if len(tokens) < size:
        return []
    return [tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)]


def local_duplicate_rate(tokens: Sequence[str], size: int = 12, window: int = 200) -> float:
    grams = ngrams(tokens, size)
    if not grams:
        return 0.0
    seen: collections.deque[tuple[str, ...]] = collections.deque()
    counts: collections.Counter[tuple[str, ...]] = collections.Counter()
    duplicate = 0
    for gram in grams:
        if counts[gram] > 0:
            duplicate += 1
        seen.append(gram)
        counts[gram] += 1
        if len(seen) > window:
            old = seen.popleft()
            counts[old] -= 1
            if counts[old] <= 0:
                del counts[old]
    return duplicate / len(grams)


def spacing_error_counts(reference: Sequence[str], predicted: Sequence[str]) -> tuple[int, int]:
    ref_tokens = set(reference)
    ref_bigrams = set(ngrams(reference, 2))
    glued = 0
    for token in predicted:
        if token in ref_tokens or len(token) < 5:
            continue
        if any((token[:split], token[split:]) in ref_bigrams for split in range(2, len(token) - 1)):
            glued += 1
    split_count = 0
    for left, right in ngrams(predicted, 2):
        joined = left + right
        if joined in ref_tokens and left not in ref_tokens and right not in ref_tokens:
            split_count += 1
    return glued, split_count


def markdown_headings(markdown: str) -> list[str]:
    return unique_nonempty(
        match.group(1)
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    )


def markdown_captions(markdown: str) -> list[str]:
    output: list[str] = []
    for line in markdown.splitlines():
        stripped = re.sub(r"^[#>*_`\s]+", "", line).strip()
        if re.match(r"(?i)^(fig(?:ure)?\.?|table)\s*[A-Z0-9IVX.-]+", stripped):
            output.append(stripped)
    return unique_nonempty(output)


def parse_markdown_tables(markdown: str) -> list[list[list[str]]]:
    lines = markdown.splitlines()
    tables: list[list[list[str]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        group: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            group.append(lines[index].strip())
            index += 1
        if len(group) < 2 or not any(re.search(r"\|\s*:?-{3,}:?\s*\|", line) for line in group[:3]):
            continue
        rows: list[list[str]] = []
        for line in group:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def fuzzy_set_prf(reference: Sequence[str], predicted: Sequence[str], threshold: float = 88.0) -> tuple[float, float, float]:
    rapidfuzz = require_dependency("rapidfuzz")
    ref = [clean_display_text(value).casefold() for value in reference if clean_display_text(value)]
    pred = [clean_display_text(value).casefold() for value in predicted if clean_display_text(value)]
    used: set[int] = set()
    matches = 0
    for value in ref:
        best_index = None
        best_score = -1.0
        for index, candidate in enumerate(pred):
            if index in used:
                continue
            score = rapidfuzz.fuzz.ratio(value, candidate)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is not None and best_score >= threshold:
            used.add(best_index)
            matches += 1
    recall = matches / max(1, len(ref))
    precision = matches / max(1, len(pred))
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return precision, recall, f1


def table_shape(table: list[list[str]]) -> tuple[int, int]:
    rows = len(table)
    cols = max((len(row) for row in table), default=0)
    return rows, cols


def table_cell_tokens(table: list[list[str]]) -> list[str]:
    return word_tokens(" ".join(cell for row in table for cell in row))


def table_match_score(reference: list[list[str]], predicted: list[list[str]]) -> float:
    _, _, content_f1 = counter_prf(table_cell_tokens(reference), table_cell_tokens(predicted))
    ref_rows, ref_cols = table_shape(reference)
    pred_rows, pred_cols = table_shape(predicted)
    row_score = min(ref_rows, pred_rows) / max(1, max(ref_rows, pred_rows))
    col_score = min(ref_cols, pred_cols) / max(1, max(ref_cols, pred_cols))
    shape_score = math.sqrt(row_score * col_score)
    return 0.72 * content_f1 + 0.28 * shape_score


def aggregate_table_score(reference: Sequence[list[list[str]]], predicted: Sequence[list[list[str]]]) -> float:
    if not reference:
        return 1.0 if not predicted else 0.85
    if not predicted:
        return 0.0
    scores = [max(table_match_score(table, candidate) for candidate in predicted) for table in reference]
    return statistics.fmean(scores)


def tail_recall(reference: Sequence[str], predicted: Sequence[str]) -> float:
    if not reference:
        return 1.0
    tail = reference[max(0, len(reference) - max(50, len(reference) // 10)) :]
    _, recall, _ = counter_prf(tail, predicted)
    return recall


def sequence_similarity(reference: Sequence[str], predicted: Sequence[str]) -> float:
    rapidfuzz = require_dependency("rapidfuzz")
    return rapidfuzz.fuzz.ratio(" ".join(reference), " ".join(predicted)) / 100.0


def markdown_math_candidates(markdown: str) -> list[str]:
    candidates: list[str] = []
    strong = re.compile(r"[=<>+\-*/^_∑∫√≈≠≤≥→←∞∈∉±]")
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        stripped = clean_display_text(line)
        if not stripped or len(stripped) > 600:
            continue
        if strong.search(stripped) or "$$" in line or "\\(" in line or "\\[" in line:
            candidates.append(stripped)
            if index + 1 < len(lines):
                pair = clean_display_text(line + " " + lines[index + 1])
                if len(pair) <= 900:
                    candidates.append(pair)
    return unique_nonempty(candidates)


def equation_score(reference_equations: Sequence[str], markdown: str) -> float:
    if not reference_equations:
        return 1.0
    candidates = markdown_math_candidates(markdown)
    full_tokens = math_tokens(markdown)
    scores: list[float] = []
    for equation in reference_equations:
        ref_tokens = math_tokens(equation)
        if not ref_tokens:
            continue
        ref_bigrams = ngrams(ref_tokens, 2)
        best = 0.0
        for candidate in candidates:
            pred_tokens = math_tokens(candidate)
            _, token_recall, _ = counter_prf(ref_tokens, pred_tokens)
            _, bigram_recall, _ = counter_prf(ref_bigrams, ngrams(pred_tokens, 2))
            ordered = sequence_similarity(ref_tokens, pred_tokens)
            best = max(best, 0.45 * token_recall + 0.35 * bigram_recall + 0.20 * ordered)
        if not candidates:
            _, token_recall, _ = counter_prf(ref_tokens, full_tokens)
            _, bigram_recall, _ = counter_prf(ref_bigrams, ngrams(full_tokens, 2))
            best = 0.65 * token_recall + 0.35 * bigram_recall
        scores.append(best)
    return statistics.fmean(scores) if scores else 1.0


def calculate_metrics(reference: ReferenceDocument, markdown: str) -> dict[str, Any]:
    plain = markdown_to_plain(markdown)
    ref_tokens = word_tokens(reference.core_text)
    pred_tokens = word_tokens(plain)
    word_precision, word_recall, word_f1 = counter_prf(ref_tokens, pred_tokens)
    bigram_precision, bigram_recall, bigram_f1 = counter_prf(
        ngrams(ref_tokens, 2), ngrams(pred_tokens, 2)
    )
    char_similarity = sequence_similarity(ref_tokens, pred_tokens)
    glued, split = spacing_error_counts(ref_tokens, pred_tokens)
    spacing_error_rate = (glued + split) / max(1, len(ref_tokens))
    duplicate_rate = local_duplicate_rate(pred_tokens)
    heading_precision, heading_recall, heading_f1 = fuzzy_set_prf(
        reference.headings, markdown_headings(markdown)
    )
    _, caption_recall, caption_f1 = fuzzy_set_prf(
        reference.captions, markdown_captions(markdown), threshold=82.0
    )
    table_score = aggregate_table_score(reference.tables, parse_markdown_tables(markdown))
    math_score = equation_score(reference.equations, markdown)
    ending_recall = tail_recall(ref_tokens, pred_tokens)
    cleanliness = max(0.0, 1.0 - min(1.0, duplicate_rate * 5.0 + spacing_error_rate * 8.0))
    overall = (
        0.22 * word_f1
        + 0.18 * bigram_f1
        + 0.12 * char_similarity
        + 0.10 * heading_f1
        + 0.12 * table_score
        + 0.12 * math_score
        + 0.05 * caption_f1
        + 0.05 * ending_recall
        + 0.04 * cleanliness
    )
    failures: list[str] = []
    if word_recall < 0.90 or ending_recall < 0.80:
        failures.append("missing_or_truncated_text")
    if word_precision < 0.95 or duplicate_rate > 0.025:
        failures.append("redundancy_or_duplicate_text")
    if word_f1 >= 0.88 and bigram_f1 < 0.78:
        failures.append("reading_order")
    if spacing_error_rate > 0.004:
        failures.append("spacing")
    if reference.headings and heading_recall < 0.82:
        failures.append("headings")
    if reference.tables and table_score < 0.78:
        failures.append("tables")
    if reference.equations and math_score < 0.78:
        failures.append("equations")
    if reference.captions and caption_recall < 0.82:
        failures.append("captions")
    replacement_count = markdown.count("\ufffd")
    if replacement_count:
        failures.append("encoding")
    return {
        "reference_tokens": len(ref_tokens),
        "predicted_tokens": len(pred_tokens),
        "word_precision": word_precision,
        "word_recall": word_recall,
        "word_f1": word_f1,
        "bigram_precision": bigram_precision,
        "bigram_recall": bigram_recall,
        "bigram_f1": bigram_f1,
        "sequence_similarity": char_similarity,
        "heading_precision": heading_precision,
        "heading_recall": heading_recall,
        "heading_f1": heading_f1,
        "caption_recall": caption_recall,
        "caption_f1": caption_f1,
        "table_score": table_score,
        "equation_score": math_score,
        "tail_recall": ending_recall,
        "local_duplicate_rate": duplicate_rate,
        "glued_token_errors": glued,
        "split_token_errors": split,
        "spacing_error_rate": spacing_error_rate,
        "replacement_character_count": replacement_count,
        "cleanliness": cleanliness,
        "overall_score": overall,
        "failure_labels": failures,
    }

