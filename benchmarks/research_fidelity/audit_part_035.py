_aggregate_mode_without_paragraphs = aggregate_mode


def aggregate_mode(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result = _aggregate_mode_without_paragraphs(rows)
    values = [float(row["paragraph_f1"]) for row in rows if row.get("paragraph_f1") is not None]
    result["mean_paragraph_f1"] = statistics.fmean(values) if values else 0.0
    result["p10_paragraph_f1"] = percentile(values, 0.10)
    result["median_paragraph_f1"] = statistics.median(values) if values else 0.0
    return result
