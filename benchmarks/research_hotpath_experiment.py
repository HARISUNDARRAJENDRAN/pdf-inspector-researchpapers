#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

OLD = '''    // Strip PDF comments (% to end of line) from the content stream.
    // Some PDF generators (e.g. PD4ML) embed comments that confuse lopdf's
    // Content::decode parser, causing it to skip operators like ET and Q.
    let content_data = strip_pdf_comments(&content_data);

    let content = match super::content_decode::decode_content_bounded(
        &content_data,
'''
NEW = '''    // Strip PDF comments (% to end of line) only when a comment marker is
    // actually present. Native research PDFs overwhelmingly take the clean
    // path, so borrowing the original page bytes avoids a page-sized clone in
    // the extraction hot path while preserving the existing string-aware
    // comment stripper for producers that need it.
    let stripped_content = content_data
        .contains(&b'%')
        .then(|| strip_pdf_comments(&content_data));
    let content_bytes = stripped_content.as_deref().unwrap_or(&content_data);

    let content = match super::content_decode::decode_content_bounded(
        content_bytes,
'''


def patch(path: Path) -> None:
    source = path.read_text()
    if OLD not in source:
        raise SystemExit('content-stream hot-path anchor not found')
    path.write_text(source.replace(OLD, NEW, 1))


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != 'patch':
        raise SystemExit('usage: research_hotpath_experiment.py patch <content_stream.rs>')
    patch(Path(sys.argv[2]))


if __name__ == '__main__':
    main()
