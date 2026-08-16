#!/usr/bin/env python3
"""Research-table fidelity experiment.

The fixture models a common dense journal table: many repeated body-column
anchors, slightly offset headers, and two genuinely distinct narrow columns.
The candidate prefers recurring tight X anchors only for wide regular tables.
"""

from __future__ import annotations

import sys
from pathlib import Path


ANCHOR = """    // Track cluster membership: for each cluster, store the list of x positions
    let mut cluster_xs: Vec<Vec<f32>> = vec![vec![x_positions[0]]];
"""

FAST_PATH = r'''    // Wide research/journal tables often have stable body-column starts while
    // multi-word headers are slightly offset. A 25pt minimum clustering
    // threshold can merge genuinely distinct narrow columns. Prefer recurring
    // tight X anchors only when at least five well-supported columns explain
    // most of the region. This stays on the existing sorted X positions and
    // can skip the more expensive general clustering path.
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

HELPER = r'''/// Recover stable left-edge anchors from repeated wide table rows.
///
/// The deliberately high column-count and coverage gates make this a narrow
/// academic-table fast path rather than a replacement for general table
/// detection. Forms, prose grids, and small technical tables retain the legacy
/// detector unchanged.
fn recurring_x_anchors(
    x_positions: &[f32],
    items: &[(usize, &TextItem)],
    mode: TableDetectionMode,
) -> Option<Vec<f32>> {
    const TIGHT_X_TOLERANCE: f32 = 4.5;
    if x_positions.len() < 20 {
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
    if supports.len() < 5 {
        return None;
    }
    supports.sort_unstable();
    let median_support = supports[supports.len() / 2];
    let support_floor = ((median_support as f32 * 0.70).ceil() as usize).max(3);

    let columns: Vec<f32> = clusters
        .iter()
        .filter_map(|(center, n)| (*n >= support_floor).then_some(*center))
        .collect();
    if columns.len() < 5 || columns.len() > 25 {
        return None;
    }

    let covered = items
        .iter()
        .filter(|(_, item)| {
            columns
                .iter()
                .any(|column| (item.x - column).abs() <= TIGHT_X_TOLERANCE)
        })
        .count();
    let coverage = covered as f32 / items.len() as f32;
    if coverage < 0.65 {
        return None;
    }

    if mode == TableDetectionMode::BodyFont {
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


def patch(path: Path) -> None:
    source = path.read_text()
    if ANCHOR not in source or HELPER_ANCHOR not in source:
        raise SystemExit("grid.rs patch anchor not found")
    source = source.replace(ANCHOR, FAST_PATH + ANCHOR, 1)
    source = source.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
    path.write_text(source)


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_fixture(path: Path) -> None:
    # The final two body anchors are only 19pt apart. The legacy >=25pt
    # threshold merges them; repeated left-edge evidence should keep them as
    # distinct logical columns. Header labels are intentionally offset.
    anchors = [72, 111, 151, 197, 237, 277, 317, 336]
    headers = [
        (70, "Ref."),
        (110, "AI"),
        (137, "Distributed"),
        (188, "Predictive"),
        (232, "Edge"),
        (265, "Adaptive"),
        (314, "CSI"),
        (336, "Main Limitation"),
    ]
    rows = [
        ["Traditional", "x", "x", "x", "x", "x", "x", "Manual-config"],
        ["[1]", "yes", "x", "x", "x", "yes", "x", "Reactive-opt"],
        ["[4]", "yes", "x", "x", "x", "yes", "x", "No-prediction"],
        ["[5]", "yes", "yes", "x", "yes", "yes", "x", "Comm-overhead"],
        ["[6]", "yes", "yes", "x", "yes", "yes", "x", "No-CSI-integration"],
        ["[7]", "yes", "yes", "x", "yes", "yes", "x", "Limited-awareness"],
        ["[8]", "yes", "yes", "x", "Partial", "yes", "x", "High-complexity"],
    ]

    ops: list[str] = ["BT", "/F0 10 Tf", "72 750 Tm", "(Academic table fidelity fixture) Tj", "ET"]
    ops += ["BT", "/F1 8 Tf"]
    y = 700
    for x, text in headers:
        ops += [f"1 0 0 1 {x} {y} Tm", f"({pdf_escape(text)}) Tj"]
    y -= 18
    for row in rows:
        for x, text in zip(anchors, row):
            ops += [f"1 0 0 1 {x} {y} Tm", f"({pdf_escape(text)}) Tj"]
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
    base = base_path.read_text().replace(" ", "")
    candidate = candidate_path.read_text().replace(" ", "")
    expected_header = "|Ref.|AI|Distributed|Predictive|Edge|Adaptive|CSI|MainLimitation|".replace(" ", "")
    expected_row = "|[7]|yes|yes|x|yes|yes|x|Limited-awareness|".replace(" ", "")
    print("BASELINE TABLE OUTPUT:\n", base_path.read_text())
    print("CANDIDATE TABLE OUTPUT:\n", candidate_path.read_text())
    if expected_header not in candidate:
        raise SystemExit("candidate did not recover all eight logical columns")
    if expected_row not in candidate:
        raise SystemExit("candidate did not preserve the narrow CSI/final-column boundary")
    if expected_header in base and expected_row in base:
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
