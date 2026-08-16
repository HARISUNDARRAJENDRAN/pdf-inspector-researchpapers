#!/usr/bin/env python3
"""Apply allocation-free common-path optimizations used by fidelity benchmarks."""

from pathlib import Path
import sys


def patch_content_stream(path: Path) -> None:
    source = path.read_text()

    import_anchor = "use std::collections::HashMap;\n"
    if "use std::borrow::Cow;" not in source:
        if import_anchor not in source:
            raise SystemExit("content-stream import anchor not found")
        source = source.replace(import_anchor, "use std::borrow::Cow;\n" + import_anchor, 1)

    old_sig = "fn strip_pdf_comments(data: &[u8]) -> Vec<u8> {\n"
    new_sig = "fn strip_pdf_comments(data: &[u8]) -> Cow<'_, [u8]> {\n"
    if old_sig not in source:
        raise SystemExit("strip_pdf_comments signature anchor not found")
    source = source.replace(old_sig, new_sig, 1)

    old_fast = """    // Quick check: if no '%' present, return as-is (common case)\n    if !data.contains(&b'%') {\n        return data.to_vec();\n    }\n"""
    new_fast = """    // Quick check: if no '%' is present, borrow the already-loaded page\n    // content instead of copying it. Native research PDFs overwhelmingly hit\n    // this path, so comment stripping becomes allocation-free in the common\n    // case while preserving the exact slow path for malformed producers.\n    if !data.contains(&b'%') {\n        return Cow::Borrowed(data);\n    }\n"""
    if old_fast not in source:
        raise SystemExit("strip_pdf_comments fast-path anchor not found")
    source = source.replace(old_fast, new_fast, 1)

    old_return = """    result\n}\n\nfn transform_path_point"""
    new_return = """    Cow::Owned(result)\n}\n\nfn transform_path_point"""
    if old_return not in source:
        raise SystemExit("strip_pdf_comments return anchor not found")
    source = source.replace(old_return, new_return, 1)

    old_decode = """    let content = match super::content_decode::decode_content_bounded(\n        &content_data,\n        super::content_decode::MAX_PAGE_OPERATIONS,\n    )? {\n"""
    new_decode = """    let content = match super::content_decode::decode_content_bounded(\n        content_data.as_ref(),\n        super::content_decode::MAX_PAGE_OPERATIONS,\n    )? {\n"""
    if old_decode not in source:
        raise SystemExit("content decode anchor not found")
    source = source.replace(old_decode, new_decode, 1)

    path.write_text(source)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: research_speed_optimizations.py <content_stream.rs>")
    patch_content_stream(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
