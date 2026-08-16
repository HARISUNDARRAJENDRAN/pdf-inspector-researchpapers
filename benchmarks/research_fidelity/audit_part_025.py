def asymmetric_counter_prf(
    recall_reference: Sequence[Any],
    precision_reference: Sequence[Any],
    predicted: Sequence[Any],
) -> tuple[float, float, float]:
    """Use body text for recall and the complete source for precision.

    Publisher XML and arXiv HTML expose a high-confidence article body plus
    lower-confidence peripheral material such as author blocks and reference
    formatting. This split keeps body completeness strict without labelling
    legitimate PDF references as hallucinated extra text.
    """

    recall_counter = collections.Counter(recall_reference)
    precision_counter = collections.Counter(precision_reference)
    predicted_counter = collections.Counter(predicted)
    recall_overlap = sum((recall_counter & predicted_counter).values())
    precision_overlap = sum((precision_counter & predicted_counter).values())
    recall = recall_overlap / max(1, sum(recall_counter.values()))
    precision = precision_overlap / max(1, sum(predicted_counter.values()))
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return precision, recall, f1


def markdown_paragraphs(markdown: str) -> list[str]:
    text = re.sub(r"<!--.*?-->", " ", markdown, flags=re.DOTALL)
    blocks = re.split(r"\n\s*\n", text)
    paragraphs: list[str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped or stripped.startswith("```"):
            continue
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith("|") for line in lines):
            continue
        if len(lines) == 1 and re.match(r"^#{1,6}\s+", lines[0]):
            continue
        value = markdown_to_plain(" ".join(lines))
        if len(word_tokens(value)) >= 5:
            paragraphs.append(value)
    return paragraphs


def paragraph_fidelity(
    reference: Sequence[str], predicted: Sequence[str]
) -> tuple[float, float, float]:
    """Greedily match source paragraphs to Markdown paragraph blocks.

    A merged pair of source paragraphs can satisfy only one match and a split
    paragraph competes for the same reference, making both over- and
    under-segmentation visible without requiring exact typography.
    """

    rapidfuzz = require_dependency("rapidfuzz")
    ref = [value for value in reference if len(word_tokens(value)) >= 5]
    pred = [value for value in predicted if len(word_tokens(value)) >= 5]
    if not ref:
        if pred:
            return 0.9, 1.0, 0.9473684211
        return 1.0, 1.0, 1.0
    used: set[int] = set()
    matches = 0
    for value in ref:
        ref_len = len(word_tokens(value))
        best_index = None
        best_score = -1.0
        for index, candidate in enumerate(pred):
            if index in used:
                continue
            pred_len = len(word_tokens(candidate))
            length_ratio = min(ref_len, pred_len) / max(1, max(ref_len, pred_len))
            if length_ratio < 0.45:
                continue
            score = rapidfuzz.fuzz.token_set_ratio(value.casefold(), candidate.casefold())
            score *= 0.65 + 0.35 * length_ratio
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is not None and best_score >= 78.0:
            used.add(best_index)
            matches += 1
    recall = matches / len(ref)
    precision = matches / max(1, len(pred))
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return precision, recall, f1


def calculate_metrics(reference: ReferenceDocument, markdown: str) -> dict[str, Any]:
    plain = markdown_to_plain(markdown)
    ref_core_tokens = word_tokens(reference.core_text)
    ref_full_tokens = word_tokens(reference.full_text)
    pred_tokens = word_tokens(plain)

    word_precision, core_word_recall, word_f1 = asymmetric_counter_prf(
        ref_core_tokens, ref_full_tokens, pred_tokens
    )
    _, full_word_recall, full_word_f1 = counter_prf(ref_full_tokens, pred_tokens)
    bigram_precision, core_bigram_recall, bigram_f1 = asymmetric_counter_prf(
        ngrams(ref_core_tokens, 2), ngrams(ref_full_tokens, 2), ngrams(pred_tokens, 2)
    )
    _, full_bigram_recall, full_bigram_f1 = counter_prf(
        ngrams(ref_full_tokens, 2), ngrams(pred_tokens, 2)
    )
    sequence_score = sequence_similarity(ref_full_tokens, pred_tokens)
    glued, split = spacing_error_counts(ref_core_tokens, pred_tokens)
    spacing_error_rate = (glued + split) / max(1, len(ref_core_tokens))
    duplicate_rate = local_duplicate_rate(pred_tokens)
    heading_precision, heading_recall, heading_f1 = fuzzy_set_prf(
        reference.headings, markdown_headings(markdown)
    )
    paragraph_precision, paragraph_recall, paragraph_f1 = paragraph_fidelity(
        reference.paragraphs, markdown_paragraphs(markdown)
    )
    _, caption_recall, caption_f1 = fuzzy_set_prf(
        reference.captions, markdown_captions(markdown), threshold=82.0
    )
    table_score = aggregate_table_score(reference.tables, parse_markdown_tables(markdown))
    math_score = equation_score(reference.equations, markdown)
    ending_recall = tail_recall(ref_full_tokens, pred_tokens)
    cleanliness = max(
        0.0,
        1.0 - min(1.0, duplicate_rate * 5.0 + spacing_error_rate * 8.0),
    )
    overall = (
        0.18 * word_f1
        + 0.15 * bigram_f1
        + 0.08 * sequence_score
        + 0.09 * paragraph_f1
        + 0.09 * heading_f1
        + 0.12 * table_score
        + 0.12 * math_score
        + 0.05 * caption_f1
        + 0.07 * ending_recall
        + 0.05 * cleanliness
    )
    failures: list[str] = []
    if core_word_recall < 0.90 or ending_recall < 0.80:
        failures.append("missing_or_truncated_text")
    if word_precision < 0.95 or duplicate_rate > 0.025:
        failures.append("redundancy_or_duplicate_text")
    if word_f1 >= 0.88 and bigram_f1 < 0.78:
        failures.append("reading_order")
    if spacing_error_rate > 0.004:
        failures.append("spacing")
    if reference.paragraphs and paragraph_recall < 0.80:
        failures.append("paragraph_boundaries")
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
        "reference_core_tokens": len(ref_core_tokens),
        "reference_full_tokens": len(ref_full_tokens),
        "predicted_tokens": len(pred_tokens),
        "word_precision": word_precision,
        "word_recall": core_word_recall,
        "word_f1": word_f1,
        "full_word_recall": full_word_recall,
        "full_word_f1": full_word_f1,
        "bigram_precision": bigram_precision,
        "bigram_recall": core_bigram_recall,
        "bigram_f1": bigram_f1,
        "full_bigram_recall": full_bigram_recall,
        "full_bigram_f1": full_bigram_f1,
        "sequence_similarity": sequence_score,
        "paragraph_precision": paragraph_precision,
        "paragraph_recall": paragraph_recall,
        "paragraph_f1": paragraph_f1,
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
