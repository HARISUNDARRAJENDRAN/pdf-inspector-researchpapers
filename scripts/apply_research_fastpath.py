from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1))


# Core detector: opt-in trusted native-text strategy.
replace_once(
    "src/detector.rs",
    """    /// Only scan these specific 1-indexed page numbers.
    /// Best when the caller knows which pages to check.
    Pages(Vec<u32>),
""",
    """    /// Only scan these specific 1-indexed page numbers.
    /// Best when the caller knows which pages to check.
    Pages(Vec<u32>),
    /// Trust the caller that the document has a usable native text layer.
    ///
    /// This skips classification and the detector's document-wide font scan.
    /// Use it only for source-controlled native-text feeds such as modern
    /// arXiv papers. Extraction still performs its normal text-quality, font,
    /// layout, and per-page OCR checks.
    TrustedText,
""",
)

replace_once(
    "src/detector.rs",
    """impl Default for DetectionConfig {
    fn default() -> Self {
        Self {
            // EarlyExit is too aggressive for PDFs with an image-only cover
            // followed by text-heavy pages (e.g., annual reports).
            strategy: ScanStrategy::Sample(8),
            min_text_ops_per_page: 3,
            text_page_ratio_threshold: 0.6,
        }
    }
}
""",
    """impl Default for DetectionConfig {
    fn default() -> Self {
        Self {
            // EarlyExit is too aggressive for PDFs with an image-only cover
            // followed by text-heavy pages (e.g., annual reports).
            strategy: ScanStrategy::Sample(8),
            min_text_ops_per_page: 3,
            text_page_ratio_threshold: 0.6,
        }
    }
}

impl DetectionConfig {
    /// Configuration for a caller-verified native-text document.
    ///
    /// This is intended for controlled research-paper sources such as arXiv.
    /// Arbitrary uploads should continue to use [`DetectionConfig::default`].
    pub fn trusted_text() -> Self {
        Self {
            strategy: ScanStrategy::TrustedText,
            ..Self::default()
        }
    }
}
""",
)

replace_once(
    "src/detector.rs",
    """pub(crate) fn detect_from_document(
    doc: &Document,
    page_count: u32,
    config: &DetectionConfig,
) -> Result<PdfTypeResult, PdfError> {
    let pages = doc.get_pages();
""",
    """pub(crate) fn detect_from_document(
    doc: &Document,
    page_count: u32,
    config: &DetectionConfig,
) -> Result<PdfTypeResult, PdfError> {
    if matches!(&config.strategy, ScanStrategy::TrustedText) {
        return Ok(PdfTypeResult {
            pdf_type: PdfType::TextBased,
            page_count,
            pages_sampled: 0,
            pages_with_text: 0,
            confidence: 1.0,
            title: get_document_title(doc),
            ocr_recommended: false,
            pages_needing_ocr: Vec::new(),
            ocr_reasons_by_page: std::collections::BTreeMap::new(),
        });
    }

    let pages = doc.get_pages();
""",
)

replace_once(
    "src/detector.rs",
    """        ScanStrategy::Pages(pages) => {
            let mut valid: Vec<u32> = pages
                .iter()
                .copied()
                .filter(|&p| p >= 1 && p <= total_pages)
                .collect();
            valid.sort();
            valid.dedup();
            (valid, false)
        }
""",
    """        ScanStrategy::Pages(pages) => {
            let mut valid: Vec<u32> = pages
                .iter()
                .copied()
                .filter(|&p| p >= 1 && p <= total_pages)
                .collect();
            valid.sort();
            valid.dedup();
            (valid, false)
        }
        ScanStrategy::TrustedText => {
            unreachable!("trusted-text documents return before page selection")
        }
""",
)

# Rust public API.
replace_once(
    "src/lib.rs",
    """    /// Create options with all defaults ([`ProcessMode::Full`]).
    pub fn new() -> Self {
        Self::default()
    }

    /// Shorthand for detect-only options.
""",
    """    /// Create options with all defaults ([`ProcessMode::Full`]).
    pub fn new() -> Self {
        Self::default()
    }

    /// Full extraction optimized for a caller-verified native-text paper.
    ///
    /// The classifier and its document-wide font scan are skipped. Extraction
    /// still runs the normal text-quality, font, layout, and OCR checks. Use
    /// this only for controlled native-text sources such as modern arXiv PDFs.
    pub fn research_paper() -> Self {
        Self {
            detection: DetectionConfig::trusted_text(),
            ..Self::default()
        }
    }

    /// Shorthand for detect-only options.
""",
)

replace_once(
    "src/lib.rs",
    """pub fn process_pdf<P: AsRef<Path>>(path: P) -> Result<PdfProcessResult, PdfError> {
    process_pdf_with_options(path, PdfOptions::new())
}

/// Fast metadata-only detection — no text extraction or markdown generation.
""",
    """pub fn process_pdf<P: AsRef<Path>>(path: P) -> Result<PdfProcessResult, PdfError> {
    process_pdf_with_options(path, PdfOptions::new())
}

/// Process a caller-verified native-text research paper.
///
/// This skips classification and its document-wide font scan, then runs the
/// same extraction, Markdown, layout, and post-extraction quality checks as
/// [`process_pdf`]. Use the default path for arbitrary user uploads.
pub fn process_research_pdf<P: AsRef<Path>>(
    path: P,
) -> Result<PdfProcessResult, PdfError> {
    process_pdf_with_options(path, PdfOptions::research_paper())
}

/// Fast metadata-only detection — no text extraction or markdown generation.
""",
)

replace_once(
    "src/lib.rs",
    """pub fn process_pdf_mem(buffer: &[u8]) -> Result<PdfProcessResult, PdfError> {
    process_pdf_mem_with_options(buffer, PdfOptions::new())
}

/// Fast metadata-only detection from a memory buffer.
""",
    """pub fn process_pdf_mem(buffer: &[u8]) -> Result<PdfProcessResult, PdfError> {
    process_pdf_mem_with_options(buffer, PdfOptions::new())
}

/// Process a caller-verified native-text research paper from memory.
///
/// See [`process_research_pdf`] for the trust boundary and safety behavior.
pub fn process_research_pdf_mem(
    buffer: &[u8],
) -> Result<PdfProcessResult, PdfError> {
    process_pdf_mem_with_options(buffer, PdfOptions::research_paper())
}

/// Fast metadata-only detection from a memory buffer.
""",
)

# Python API and stubs.
replace_once(
    "src/python.rs",
    """fn process_pdf(path: &str, pages: Option<Vec<u32>>) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::new();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_with_options(path, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Process a PDF from bytes in memory.
""",
    """fn process_pdf(path: &str, pages: Option<Vec<u32>>) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::new();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_with_options(path, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Process a caller-verified native-text research paper.
///
/// Use this for controlled sources such as modern arXiv PDFs. Arbitrary
/// uploads should use process_pdf so classification and OCR routing remain on.
#[pyfunction]
#[pyo3(signature = (path, pages=None))]
fn process_research_pdf(path: &str, pages: Option<Vec<u32>>) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::research_paper();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_with_options(path, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Process a PDF from bytes in memory.
""",
)

replace_once(
    "src/python.rs",
    """fn process_pdf_bytes(data: &[u8], pages: Option<Vec<u32>>) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::new();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_mem_with_options(data, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Fast detection only — no text extraction or markdown.
""",
    """fn process_pdf_bytes(data: &[u8], pages: Option<Vec<u32>>) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::new();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_mem_with_options(data, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Process a caller-verified native-text research paper from bytes.
#[pyfunction]
#[pyo3(signature = (data, pages=None))]
fn process_research_pdf_bytes(
    data: &[u8],
    pages: Option<Vec<u32>>,
) -> PyResult<PyPdfResult> {
    let mut opts = crate::PdfOptions::research_paper();
    if let Some(p) = pages {
        opts = opts.pages(p);
    }
    let result = crate::process_pdf_mem_with_options(data, opts).map_err(to_py_err)?;
    Ok(to_py_result(result))
}

/// Fast detection only — no text extraction or markdown.
""",
)

replace_once(
    "src/python.rs",
    """    m.add_function(wrap_pyfunction!(process_pdf, m)?)?;
    m.add_function(wrap_pyfunction!(process_pdf_bytes, m)?)?;
""",
    """    m.add_function(wrap_pyfunction!(process_pdf, m)?)?;
    m.add_function(wrap_pyfunction!(process_pdf_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(process_research_pdf, m)?)?;
    m.add_function(wrap_pyfunction!(process_research_pdf_bytes, m)?)?;
""",
)

replace_once(
    "pdf_inspector.pyi",
    """def process_pdf(path: str, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a PDF: detect type, extract text, convert to Markdown.\"\"\"
    ...

def process_pdf_bytes(data: bytes, pages: Optional[list[int]] = None) -> PdfResult:
""",
    """def process_pdf(path: str, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a PDF: detect type, extract text, convert to Markdown.\"\"\"
    ...

def process_research_pdf(path: str, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a caller-verified native-text research paper.\"\"\"
    ...

def process_pdf_bytes(data: bytes, pages: Optional[list[int]] = None) -> PdfResult:
""",
)

replace_once(
    "pdf_inspector.pyi",
    """def process_pdf_bytes(data: bytes, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a PDF from bytes in memory.\"\"\"
    ...

def detect_pdf(path: str) -> PdfResult:
""",
    """def process_pdf_bytes(data: bytes, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a PDF from bytes in memory.\"\"\"
    ...

def process_research_pdf_bytes(data: bytes, pages: Optional[list[int]] = None) -> PdfResult:
    \"\"\"Process a caller-verified native-text research paper from bytes.\"\"\"
    ...

def detect_pdf(path: str) -> PdfResult:
""",
)

# Rust documentation.
replace_once(
    "docs/rust-api.md",
    "Fast metadata-only detection (no text extraction or markdown generation):\n",
    """Trusted native-text research-paper fast path (for controlled sources such as modern arXiv PDFs):

```rust
use pdf_inspector::process_research_pdf;

let result = process_research_pdf("paper.pdf")?;
println!("{}", result.markdown.as_deref().unwrap_or_default());
```

This path skips pre-extraction classification and its document-wide font scan. It still runs the normal extraction, layout, text-quality, font-decoding, and per-page OCR checks. Do not use it for arbitrary uploads; use `process_pdf` for those.

Fast metadata-only detection (no text extraction or markdown generation):
""",
)

replace_once(
    "docs/rust-api.md",
    """| `process_pdf(path)` | Full processing with defaults |
| `detect_pdf(path)` | Fast metadata-only detection (no extraction) |
""",
    """| `process_pdf(path)` | Full processing with defaults |
| `process_research_pdf(path)` | Trusted native-text research-paper processing without pre-classification |
| `detect_pdf(path)` | Fast metadata-only detection (no extraction) |
""",
)

replace_once(
    "docs/rust-api.md",
    """| `process_pdf_mem(bytes)` | Full processing from a byte buffer |
| `detect_pdf_mem(bytes)` | Fast detection from a byte buffer |
""",
    """| `process_pdf_mem(bytes)` | Full processing from a byte buffer |
| `process_research_pdf_mem(bytes)` | Trusted research-paper processing from bytes |
| `detect_pdf_mem(bytes)` | Fast detection from a byte buffer |
""",
)

replace_once(
    "docs/rust-api.md",
    "| `ScanStrategy` | `EarlyExit`, `Full`, `Sample(n)`, `Pages(vec)` |\n",
    "| `ScanStrategy` | `EarlyExit`, `Full`, `Sample(n)`, `Pages(vec)`, `TrustedText` |\n",
)

# Regression tests.
Path("tests/research_paper_fast_path.rs").write_text(
    r'''use pdf_inspector::{
    process_pdf, process_pdf_mem, process_research_pdf, process_research_pdf_mem,
    DetectionConfig, PdfOptions, PdfType, ScanStrategy,
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
    assert_eq!(optimized.layout, baseline.layout);
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
    assert_eq!(optimized.layout, baseline.layout);
    assert_eq!(optimized.has_encoding_issues, baseline.has_encoding_issues);
}
'''
)
