#!/usr/bin/env python3
"""Research-table fidelity experiment.

The fixture models a common journal table shape: dense recurring data anchors,
slightly offset multi-word headers, and a wrapped final text column. The
candidate prefers recurring tight X anchors before the general gap heuristic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ANCHOR = """    // Track cluster membership: for each cluster, store the list of x positions
    let mut cluster_xs: Vec<Vec<f32>> = vec![vec![x_positions[0]]];
"""

FAST_PATH = r'''    // Research/journal tables often have stable data-column starts while
    // multi-word headers are slightly offset from those starts.  A wide
    // center-based clustering threshold can therefore merge a real narrow
    // column into its neighbour (for example a boolean/checkmark column) or
    // promote wrapped text in the last column to a phantom column.
    //
    // Prefer recurring tight X anchors when they explain most of the region.
    // This is O(n) after the sort above and, on regular academic tables, also
    // skips the more expensive general clustering/merge path below.
    if let Some(columns) = recurring_x_anchors(&x_positions, items, mode) {
        log::debug!(
            "  find_column_boundaries: {} recurring anchors, {} items",
            columns.len(),
            items.len()
        );
        return columns;
    }

'''

HELPER_ANCHOR = """/// Check if a text string looks like a number (digits, decimals, sign, comma).
fn is_numeric_text(s: &str) -> bool {
"""

HELPER = r'''/// Recover stable left-edge anchors from repeated table rows.
///
/// Academic tables commonly align body cells much more consistently than
/// their headers.  We cluster only very-near X positions, retain anchors with
/// row-like support, and use them only when they account for most items.  The
/// conservative coverage/support gates keep ordinary prose on the existing
/// detector path.
fn recurring_x_anchors(
    x_positions: &[f32],
    items: &[(usize, &TextItem)],
    mode: TableDetectionMode,
) -> Option<Vec<f32>> {
    const TIGHT_X_TOLERANCE: f32 = 4.5;
    if x_positions.len() < 12 {
        return None;
    }

    let mut clusters: Vec<(f32, usize)> = Vec::new();
    let mut sum = x_positions[0];
    let mut count = 1usize;
    let mut last = x_positions[0];

    for &x in &x_positions[1..] {
        if x - last <= TIGHT_X_TOLERANCE {
            sum += x;
            count += 1;
        } else {
            clusters.push((sum / count as f32, count));
            sum = x;
            count = 1;
        }
        last = x;
    }
    clusters.push((sum / count as f32, count));

    let mut supports: Vec<usize> = clusters
        .iter()
        .filter_map(|(_, n)| (*n >= 3).then_some(*n))
        .collect();
    if supports.len() < 3 {
        return None;
    }
    supports.sort_unstable();
    let median_support = supports[supports.len() / 2];
    let support_floor = ((median_support as f32 * 0.60).ceil() as usize).max(3);

    let columns: Vec<f32> = clusters
        .iter()
        .filter_map(|(center, n)| (*n >= support_floor).then_some(*center))
        .collect();
    if columns.len() < 3 || columns.len() > 25 {
        return None;
    }

    // Count each item once if it sits on a retained left-edge anchor.  Header
    // labels and wrapped prose are expected not to match; data rows should.
    let covered = items
        .iter()
        .filter(|(_, item)| {
            columns
                .iter()
                .any(|column| (item.x - column).abs() <= TIGHT_X_TOLERANCE)
        })
        .count();
    let coverage = covered as f32 / items.len() as f32;
    if coverage < 0.55 {
        return None;
    }

    if mode == TableDetectionMode::BodyFont {
        // Keep the existing paragraph guard semantics: no recurring anchor may
        // own most of the region.
        for &column in &columns {
            let count = items
                .iter()
                .filter(|(_, item)| (item.x - column).abs() <= TIGHT_X_TOLERANCE)
                .count();
            if count as f32 / items.len() as f32 > 0.60 {
                return None;
            }
        }
    }

    Some(columns)
}

'''

INDEX_OLD = r'''    columns
        .iter()
        .enumerate()
        .min_by(|(_, a), (_, b)| {
            (x - *a)
                .abs()
                .partial_cmp(&(x - *b).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .filter(|(_, col_x)| (x - *col_x).abs() < threshold)
        .map(|(idx, _)| idx)
'''

INDEX_NEW = r'''    let (idx, col_x) = columns.iter().enumerate().min_by(|(_, a), (_, b)| {
        (x - *a)
            .abs()
            .partial_cmp(&(x - *b).abs())
            .unwrap_or(std::cmp::Ordering::Equal)
    })?;

    // The first and last columns of journal tables are frequently descriptive
    // text.  Wrapped words can start farther from the left-edge anchor than an
    // internal numeric/boolean cell.  The region has already been qualified as
    // a table, so allow extra room only at the two outer columns.
    let edge_threshold = if idx == 0 || idx + 1 == columns.len() {
        threshold.max(60.0)
    } else {
        threshold
    };
    ((x - *col_x).abs() < edge_threshold).then_some(idx)
'''


def patch(path: Path) -> None:
    source = path.read_text()
    if ANCHOR not in source or HELPER_ANCHOR not in source or INDEX_OLD not in source:
        raise SystemExit("grid.rs patch anchor not found")
    source = source.replace(ANCHOR, FAST_PATH + ANCHOR, 1)
    source = source.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
    source = source.replace(INDEX_OLD, INDEX_NEW, 1)
    path.write_text(source)


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_fixture(path: Path) -> None:
    # Eight logical columns.  Body cells use stable anchors; header labels are
    # deliberately offset like many journal templates.  The final column has a
    # wrapped continuation starting substantially to the right of its anchor.
    anchors = [72, 111, 151, 207, 259, 309, 359, 405]
    headers = [
        (70, "Ref."),
        (110, "AI"),
        (137, "Distributed"),
        (194, "Predictive"),
        (254, "Edge"),
        (297, "Adaptive"),
        (357, "CSI"),
        (405, "Main Limitation"),
    ]
    rows = [
        ["Traditional", "x", "x", "x", "x", "x", "x", "Manual configuration"],
        ["[1]", "yes", "x", "x", "x", "yes", "x", "Reactive optimization"],
        ["[4]", "yes", "x", "x", "x", "yes", "x", "No prediction"],
        ["[5]", "yes", "yes", "x", "yes", "yes", "x", "Communication overhead"],
        ["[6]", "yes", "yes", "x", "yes", "yes", "x", "No CSI integration"],
        ["[7]", "yes", "yes", "x", "yes", "yes", "x", "Limited physical-layer"],
        ["[8]", "yes", "yes", "x", "Partial", "yes", "x", "High complexity"],
    ]

    ops: list[str] = ["BT", "/F0 10 Tf", "72 750 Tm", "(Academic table fidelity fixture) Tj", "ET"]
    ops += ["BT", "/F1 8 Tf"]
    y = 700
    for x, text in headers:
        ops += [f"1 0 0 1 {x} {y} Tm", f"({pdf_escape(text)}) Tj"]
    y -= 18
    for row_idx, row in enumerate(rows):
        for x, text in zip(anchors, row):
            ops += [f"1 0 0 1 {x} {y} Tm", f"({pdf_escape(text)}) Tj"]
        if row_idx == 5:
            # Continuation belonging to the final cell, intentionally offset.
            ops += [f"1 0 0 1 456 {y - 9} Tm", "(awareness) Tj"]
        y -= 18
    ops += ["ET"]
    stream = ("\n".join(ops) + "\n").encode()

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F0 4 0 R /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n".encode()
    data += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        data += f"{off:010d} 00000 n \n".encode()
    data += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(data)


def score(base_path: Path, candidate_path: Path) -> None:
    base = base_path.read_text()
    candidate = candidate_path.read_text()
    expected_header = "|Ref.|AI|Distributed|Predictive|Edge|Adaptive|CSI|Main Limitation|"
    expected_row = "|[7]|yes|yes|x|yes|yes|x|Limited physical-layer awareness|"
    candidate_compact = candidate.replace(" ", "")
    header_compact = expected_header.replace(" ", "")
    row_compact = expected_row.replace(" ", "")
    base_compact = base.replace(" ", "")
    print("BASELINE TABLE OUTPUT:\n", base)
    print("CANDIDATE TABLE OUTPUT:\n", candidate)
    if header_compact not in candidate_compact:
        raise SystemExit("candidate did not recover the eight-column header")
    if row_compact not in candidate_compact:
        raise SystemExit("candidate did not keep wrapped final-column text in its cell")
    if header_compact in base_compact and row_compact in base_compact:
        raise SystemExit("fixture does not distinguish baseline from candidate")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: research_table_experiment.py <patch|fixture|score> ...")
    command = sys.argv[1]
    if command == "patch" and len(sys.argv) == 3:
        patch(Path(sys.argv[2]))
    elif command == "fixture" and len(sys.argv) == 3:
        make_fixture(Path(sys.argv[2]))
    elif command == "score" and len(sys.argv) == 4:
        score(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit("invalid arguments")


if __name__ == "__main__":
    main()
