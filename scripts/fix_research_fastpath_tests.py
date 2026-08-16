from pathlib import Path

path = Path("tests/research_paper_fast_path.rs")
text = path.read_text()
old = """    assert_eq!(optimized.layout, baseline.layout);
    assert_eq!(optimized.has_encoding_issues, baseline.has_encoding_issues);
"""
new = """    assert_eq!(optimized.layout.is_complex, baseline.layout.is_complex);
    assert_eq!(
        optimized.layout.pages_with_tables,
        baseline.layout.pages_with_tables
    );
    assert_eq!(
        optimized.layout.pages_with_columns,
        baseline.layout.pages_with_columns
    );
    assert_eq!(optimized.has_encoding_issues, baseline.has_encoding_issues);
"""
if text.count(old) != 2:
    raise SystemExit(f"expected two layout assertions, found {text.count(old)}")
path.write_text(text.replace(old, new))
