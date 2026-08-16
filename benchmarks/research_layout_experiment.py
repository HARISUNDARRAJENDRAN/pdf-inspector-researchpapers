#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

HELPER_ANCHOR = """/// Group text items into lines, with multi-column support
/// Detect newspaper-style columns: independent text flows that should be read
/// sequentially (all of col1, then col2) rather than Y-interleaved.
pub(crate) fn is_newspaper_layout(
"""

HELPER = r'''/// Return the index of a narrow, sparse sidebar beside a primary prose column.
///
/// Publisher metadata, margin notes, and similar sidebars are independent from
/// the article's reading flow.  The geometry is intentionally conservative:
/// exactly two columns, the narrow side must also contain fewer lines, and the
/// body must be substantial.  No lexical/publisher-specific rules are needed.
fn sparse_sidebar_index(
    per_column_lines: &[Vec<TextLine>],
    columns: &[ColumnRegion],
) -> Option<usize> {
    if per_column_lines.len() != 2 || columns.len() != 2 {
        return None;
    }

    let widths = [
        columns[0].x_max - columns[0].x_min,
        columns[1].x_max - columns[1].x_min,
    ];
    let counts = [per_column_lines[0].len(), per_column_lines[1].len()];
    let narrow = usize::from(widths[1] < widths[0]);
    let fewer = usize::from(counts[1] < counts[0]);
    if narrow != fewer || counts[narrow] < 3 || counts[1 - narrow] < 15 {
        return None;
    }

    let width_ratio = widths[narrow] / widths[1 - narrow].max(1.0);
    let line_ratio = counts[narrow] as f32 / counts[1 - narrow].max(1) as f32;
    if width_ratio >= 0.60 || line_ratio >= 0.50 {
        return None;
    }

    let vertical_span = |lines: &[TextLine]| -> f32 {
        if lines.len() < 2 {
            return 0.0;
        }
        let lo = lines.iter().map(|line| line.y).fold(f32::INFINITY, f32::min);
        let hi = lines
            .iter()
            .map(|line| line.y)
            .fold(f32::NEG_INFINITY, f32::max);
        (hi - lo).max(0.0)
    };
    let narrow_span = vertical_span(&per_column_lines[narrow]);
    let body_span = vertical_span(&per_column_lines[1 - narrow]);

    // Very short sidebars are already decisive. Longer sidebars must still
    // occupy materially less of the page than the article column.
    if counts[narrow] <= 8 || (body_span > 0.0 && narrow_span / body_span < 0.72) {
        Some(narrow)
    } else {
        None
    }
}

'''

IS_NEWSPAPER_OLD = r'''    if per_column_lines.len() < 2 {
        return false;
    }

    // Each column must independently have substantial content
'''
IS_NEWSPAPER_NEW = r'''    if per_column_lines.len() < 2 {
        return false;
    }

    // A sparse publisher/sidebar column is an independent flow even when it
    // has too few lines for the dense-newspaper thresholds below.
    if sparse_sidebar_index(per_column_lines, columns).is_some() {
        return true;
    }

    // Each column must independently have substantial content
'''

ORDER_OLD = r'''            let is_newspaper = is_newspaper_layout(&per_column_lines, &columns);
            debug!(
'''
ORDER_NEW = r'''            let sidebar_idx = sparse_sidebar_index(&per_column_lines, &columns);
            let is_newspaper = is_newspaper_layout(&per_column_lines, &columns);
            debug!(
'''

SWAP_ANCHOR = r'''                for col in per_column_lines {
                    let (core, stragglers) = split_column_stragglers(col);
                    core_columns.push(core);
                    col_stragglers.push(stragglers);
                }

                // col_top = min of max Y across core columns
'''
SWAP_NEW = r'''                for col in per_column_lines {
                    let (core, stragglers) = split_column_stragglers(col);
                    core_columns.push(core);
                    col_stragglers.push(stragglers);
                }

                // A left-hand publisher/sidebar column is supplemental context,
                // not the primary article flow. Read the wide body first. A
                // right-hand sidebar is already after the body in normal order.
                if sidebar_idx == Some(0) && core_columns.len() == 2 {
                    core_columns.swap(0, 1);
                    col_stragglers.swap(0, 1);
                }

                // col_top = min of max Y across core columns
'''


def patch(path: Path) -> None:
    source = path.read_text()
    for old in (HELPER_ANCHOR, IS_NEWSPAPER_OLD, ORDER_OLD, SWAP_ANCHOR):
        if old not in source:
            raise SystemExit(f"layout patch anchor missing: {old[:50]!r}")
    source = source.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
    source = source.replace(IS_NEWSPAPER_OLD, IS_NEWSPAPER_NEW, 1)
    source = source.replace(ORDER_OLD, ORDER_NEW, 1)
    source = source.replace(SWAP_ANCHOR, SWAP_NEW, 1)
    path.write_text(source)


def esc(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def fixture(path: Path) -> None:
    ops = ['BT', '/F1 10 Tf']
    # Full-width, three-line title above the asymmetric article/sidebar layout.
    for y, text in [
        (760, 'Sentient Networks: A Predictive Edge Intelligence Framework'),
        (738, 'for Autonomous Wi-Fi Stability Prediction and'),
        (716, 'Self-Optimization'),
    ]:
        ops += [f'1 0 0 1 45 {y} Tm', f'({esc(text)}) Tj']
    # Wide primary article column.
    ops += ['/F1 10 Tf']
    y = 680
    main = [
        'Abstract',
        'Conventional wireless optimization is predominantly reactive and delayed.',
        'The proposed framework predicts instability before degradation is visible.',
        'It combines channel sensing temporal prediction and safe control policies.',
        'The system continuously observes the wireless channel and updates its state.',
        'Prediction confidence is checked before any autonomous action is executed.',
        'Temporal persistence prevents transient interference from causing reconfiguration.',
        'This creates a practical closed loop suitable for edge deployment.',
        'Keywords wireless networking predictive intelligence edge optimization.',
        '1. Introduction',
    ]
    main += [f'Primary article paragraph line {i} contains substantial research prose.' for i in range(1, 22)]
    for text in main:
        ops += [f'1 0 0 1 205 {y} Tm', f'({esc(text)}) Tj']
        y -= 13
    # Sparse left publisher metadata overlaps the lower main-column Y range.
    y = 390
    for text in [
        'Received: August 2026',
        'Revised:',
        'Accepted:',
        'Published:',
        'Copyright 2026 authors',
        'Creative Commons license',
    ]:
        ops += [f'1 0 0 1 45 {y} Tm', f'({esc(text)}) Tj']
        y -= 18
    ops += ['ET']
    stream = ('\n'.join(ops) + '\n').encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'endstream',
    ]
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(objects)+1}\n'.encode() + b'0000000000 65535 f \n'
    for off in offsets[1:]: data += f'{off:010d} 00000 n \n'.encode()
    data += f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(data)


def score(base: Path, candidate: Path) -> None:
    b = base.read_text(); c = candidate.read_text()
    title_parts = [
        'Sentient Networks: A Predictive Edge Intelligence Framework',
        'for Autonomous Wi-Fi Stability Prediction and',
        'Self-Optimization',
    ]
    for part in title_parts:
        if part not in c:
            raise SystemExit(f'candidate lost title fragment: {part}')
    intro = c.find('1. Introduction')
    received = c.find('Received: August 2026')
    if intro < 0 or received < 0 or intro > received:
        raise SystemExit('candidate did not read the primary article before the left sidebar')
    print('LAYOUT_ORDER candidate introduction before sidebar:', intro, received)
    print('BASELINE snippet:\n', b[:1800])
    print('CANDIDATE snippet:\n', c[:1800])


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit('usage: research_layout_experiment.py <patch|fixture|score-base-candidate-not-supported> path')
    cmd = sys.argv[1]
    if cmd == 'patch': patch(Path(sys.argv[2]))
    elif cmd == 'fixture': fixture(Path(sys.argv[2]))
    else: raise SystemExit('invalid command')

if __name__ == '__main__':
    main()
