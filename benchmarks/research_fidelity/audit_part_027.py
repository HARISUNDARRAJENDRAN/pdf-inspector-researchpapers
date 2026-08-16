# Equation metric performance guard.
#
# Scientific papers can contain thousands of inline MathML nodes. Comparing
# every reference expression against every Markdown candidate while repeatedly
# tokenizing the same candidate is quadratic enough to dominate the parser
# benchmark. Sample deterministically across the document, tokenize once, and
# keep the same token/bigram/order scoring formula.

MAX_REFERENCE_EQUATIONS = 120
MAX_MARKDOWN_MATH_CANDIDATES = 300


def equation_score(reference_equations: Sequence[str], markdown: str) -> float:
    if not reference_equations:
        return 1.0

    references = evenly_spaced(
        unique_nonempty(reference_equations), MAX_REFERENCE_EQUATIONS
    )
    candidate_texts = evenly_spaced(
        markdown_math_candidates(markdown), MAX_MARKDOWN_MATH_CANDIDATES
    )
    prepared_candidates: list[
        tuple[list[str], collections.Counter[str], collections.Counter[tuple[str, ...]], str]
    ] = []
    for candidate in candidate_texts:
        tokens = math_tokens(candidate)
        if not tokens:
            continue
        prepared_candidates.append(
            (
                tokens,
                collections.Counter(tokens),
                collections.Counter(ngrams(tokens, 2)),
                " ".join(tokens),
            )
        )

    full_tokens = math_tokens(markdown)
    full_counter = collections.Counter(full_tokens)
    full_bigram_counter = collections.Counter(ngrams(full_tokens, 2))
    rapidfuzz = require_dependency("rapidfuzz")
    scores: list[float] = []

    for equation in references:
        ref_tokens = math_tokens(equation)
        if not ref_tokens:
            continue
        ref_counter = collections.Counter(ref_tokens)
        ref_bigrams = ngrams(ref_tokens, 2)
        ref_bigram_counter = collections.Counter(ref_bigrams)
        ref_size = max(1, sum(ref_counter.values()))
        ref_bigram_size = max(1, sum(ref_bigram_counter.values()))
        ref_joined = " ".join(ref_tokens)
        best = 0.0

        for pred_tokens, pred_counter, pred_bigram_counter, pred_joined in prepared_candidates:
            token_recall = sum((ref_counter & pred_counter).values()) / ref_size
            # Expressions with no shared tokens cannot be the best candidate;
            # avoid the more expensive bigram and order comparisons.
            if token_recall == 0.0:
                continue
            bigram_recall = (
                sum((ref_bigram_counter & pred_bigram_counter).values())
                / ref_bigram_size
            )
            # Only compute edit order for candidates capable of improving the
            # current score even with a perfect order component.
            upper_bound = 0.45 * token_recall + 0.35 * bigram_recall + 0.20
            if upper_bound <= best:
                continue
            ordered = rapidfuzz.fuzz.ratio(ref_joined, pred_joined) / 100.0
            best = max(
                best,
                0.45 * token_recall + 0.35 * bigram_recall + 0.20 * ordered,
            )

        if not prepared_candidates:
            token_recall = sum((ref_counter & full_counter).values()) / ref_size
            bigram_recall = (
                sum((ref_bigram_counter & full_bigram_counter).values())
                / ref_bigram_size
            )
            best = 0.65 * token_recall + 0.35 * bigram_recall
        scores.append(best)

    return statistics.fmean(scores) if scores else 1.0
