#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ANCHOR = r'''pub(crate) fn is_heading_fragment(text: &str) -> bool {
    let t = text.trim_end();

'''
INSERT = r'''pub(crate) fn is_heading_fragment(text: &str) -> bool {
    let t = text.trim_end();

    // Display equations frequently use a font size/face that is rare in the
    // document, which makes typography-only heading detection over-promote
    // them.  Strong mathematical operators are direct semantic evidence and
    // are cheaper/more reliable than another layout pass.  Keep the gate
    // conservative: short equation-like lines only, never ordinary prose.
    let word_count = t.split_whitespace().count();
    let alpha_count = t.chars().filter(|c| c.is_alphabetic()).count();
    let strong_operator = t.chars().any(|c| {
        matches!(
            c,
            '=' | '<'
                | '>'
                | '≤'
                | '≥'
                | '≪'
                | '≫'
                | '≈'
                | '≠'
                | '±'
                | '∑'
                | '∫'
                | '√'
                | '∝'
                | '∈'
                | '∉'
                | '∞'
        )
    });
    let bracketed_math = (t.contains('[') && t.contains(']'))
        || (t.contains('{') && t.contains('}'));
    if word_count <= 12
        && (strong_operator || bracketed_math)
        && (alpha_count <= 32 || t.contains('='))
    {
        return true;
    }

'''


def patch(path: Path) -> None:
    source = path.read_text()
    if ANCHOR not in source:
        raise SystemExit('analysis.rs heading-fragment anchor not found')
    path.write_text(source.replace(ANCHOR, INSERT, 1))


def esc(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def fixture(path: Path) -> None:
    ops = ['BT', '/F1 10 Tf']
    y = 740
    for i in range(18):
        text = f'Body paragraph line {i+1} explains the statistical prediction framework.'
        ops += [f'1 0 0 1 72 {y} Tm', f'({esc(text)}) Tj']
        y -= 17
    # Rare larger math face: baseline typography wants to make these headings.
    ops += ['/F2 12 Tf']
    for y, text in [
        (420, 'X = {x1, x2, ..., xN}'),
        (390, 'mu = 1/N sum xi'),
        (360, '0 <= p_t <= 1'),
        (330, 'f_t = [sigma_t^2, mu_t, rho_t, RSSI_t]'),
    ]:
        ops += [f'1 0 0 1 150 {y} Tm', f'({esc(text)}) Tj']
    ops += ['ET']
    stream = ('\n'.join(ops) + '\n').encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'endstream',
    ]
    data = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(objects)+1}\n'.encode() + b'0000000000 65535 f \n'
    for off in offsets[1:]: data += f'{off:010d} 00000 n \n'.encode()
    data += f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(data)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit('usage: research_math_experiment.py <patch|fixture> path')
    if sys.argv[1] == 'patch': patch(Path(sys.argv[2]))
    elif sys.argv[1] == 'fixture': fixture(Path(sys.argv[2]))
    else: raise SystemExit('invalid command')

if __name__ == '__main__':
    main()
