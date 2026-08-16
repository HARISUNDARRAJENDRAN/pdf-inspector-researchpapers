//! Benchmark-only driver used by the research-fidelity corpus audit.
//!
//! It deliberately exposes no new library API. The binary runs either the
//! standard pipeline or the trusted research-paper fast path and emits one
//! machine-readable JSON object containing timing and Markdown output.

use pdf_inspector::{process_pdf, process_research_pdf, PdfProcessResult, PdfType};
use std::env;
use std::fmt::Write as _;
use std::process;
use std::time::Instant;

fn json_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 32);
    for ch in value.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{000c}' => out.push_str("\\f"),
            c if c < '\u{0020}' => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out
}

fn pdf_type_label(pdf_type: PdfType) -> &'static str {
    match pdf_type {
        PdfType::TextBased => "text_based",
        PdfType::Scanned => "scanned",
        PdfType::ImageBased => "image_based",
        PdfType::Mixed => "mixed",
    }
}

fn json_u32_array(values: &[u32]) -> String {
    values
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",")
}

fn print_result(mode: &str, wall_time_ns: u128, result: PdfProcessResult) {
    let markdown = result.markdown.unwrap_or_default();
    println!(
        concat!(
            "{{",
            "\"mode\":\"{}\",",
            "\"wall_time_ns\":{},",
            "\"reported_time_ms\":{},",
            "\"pdf_type\":\"{}\",",
            "\"confidence\":{},",
            "\"page_count\":{},",
            "\"markdown_length\":{},",
            "\"pages_needing_ocr\":[{}],",
            "\"pages_with_tables\":[{}],",
            "\"pages_with_columns\":[{}],",
            "\"has_encoding_issues\":{},",
            "\"markdown\":\"{}\"",
            "}}"
        ),
        json_escape(mode),
        wall_time_ns,
        result.processing_time_ms,
        pdf_type_label(result.pdf_type),
        result.confidence,
        result.page_count,
        markdown.len(),
        json_u32_array(&result.pages_needing_ocr),
        json_u32_array(&result.layout.pages_with_tables),
        json_u32_array(&result.layout.pages_with_columns),
        result.has_encoding_issues,
        json_escape(&markdown),
    );
}

fn main() {
    let mut args = env::args().skip(1);
    let mode = args.next().unwrap_or_else(|| {
        eprintln!("usage: research-audit <standard|research> <paper.pdf>");
        process::exit(2);
    });
    let path = args.next().unwrap_or_else(|| {
        eprintln!("usage: research-audit <standard|research> <paper.pdf>");
        process::exit(2);
    });
    if args.next().is_some() {
        eprintln!("usage: research-audit <standard|research> <paper.pdf>");
        process::exit(2);
    }

    let start = Instant::now();
    let parsed = match mode.as_str() {
        "standard" => process_pdf(&path),
        "research" => process_research_pdf(&path),
        _ => {
            eprintln!("mode must be 'standard' or 'research'");
            process::exit(2);
        }
    };
    let wall_time_ns = start.elapsed().as_nanos();

    match parsed {
        Ok(result) => print_result(&mode, wall_time_ns, result),
        Err(error) => {
            println!(
                "{{\"mode\":\"{}\",\"wall_time_ns\":{},\"error\":\"{}\"}}",
                json_escape(&mode),
                wall_time_ns,
                json_escape(&error.to_string())
            );
            process::exit(1);
        }
    }
}
