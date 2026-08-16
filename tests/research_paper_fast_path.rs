use pdf_inspector::{
    process_pdf, process_pdf_mem, process_research_pdf, process_research_pdf_mem, DetectionConfig,
    PdfOptions, PdfType, ScanStrategy,
};
use std::path::PathBuf;

fn native_text_fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join("firecrawl_docs_tagged.pdf")
}

#[test]
fn trusted_text_configuration_is_explicit_and_opt_in() {
    let config = DetectionConfig::trusted_text();
    assert!(matches!(config.strategy, ScanStrategy::TrustedText));

    let options = PdfOptions::research_paper();
    assert!(matches!(
        options.detection.strategy,
        ScanStrategy::TrustedText
    ));
}

#[test]
fn research_paper_file_path_preserves_markdown() {
    let path = native_text_fixture();
    let baseline = process_pdf(&path).expect("default parser should process fixture");
    let optimized =
        process_research_pdf(&path).expect("research-paper path should process fixture");

    assert_eq!(optimized.pdf_type, PdfType::TextBased);
    assert_eq!(optimized.confidence, 1.0);
    assert_eq!(optimized.markdown, baseline.markdown);
    assert_eq!(optimized.layout.is_complex, baseline.layout.is_complex);
    assert_eq!(
        optimized.layout.pages_with_tables,
        baseline.layout.pages_with_tables
    );
    assert_eq!(
        optimized.layout.pages_with_columns,
        baseline.layout.pages_with_columns
    );
    assert_eq!(optimized.has_encoding_issues, baseline.has_encoding_issues);
}

#[test]
fn research_paper_memory_path_preserves_markdown() {
    let bytes = std::fs::read(native_text_fixture()).expect("fixture should be readable");
    let baseline = process_pdf_mem(&bytes).expect("default memory parser should process fixture");
    let optimized = process_research_pdf_mem(&bytes)
        .expect("research-paper memory path should process fixture");

    assert_eq!(optimized.pdf_type, PdfType::TextBased);
    assert_eq!(optimized.confidence, 1.0);
    assert_eq!(optimized.markdown, baseline.markdown);
    assert_eq!(optimized.layout.is_complex, baseline.layout.is_complex);
    assert_eq!(
        optimized.layout.pages_with_tables,
        baseline.layout.pages_with_tables
    );
    assert_eq!(
        optimized.layout.pages_with_columns,
        baseline.layout.pages_with_columns
    );
    assert_eq!(optimized.has_encoding_issues, baseline.has_encoding_issues);
}
