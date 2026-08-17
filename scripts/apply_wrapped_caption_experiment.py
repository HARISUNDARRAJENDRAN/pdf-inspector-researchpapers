#!/usr/bin/env python3
"""Apply the conservative wrapped scientific-caption experiment."""

from __future__ import annotations

import argparse
from pathlib import Path


PREPROCESS_IMPORT = "use super::analysis::detect_header_level;\n"
PREPROCESS_IMPORT_REPLACEMENT = (
    "use super::analysis::{detect_header_level, line_is_mostly_bold};\n"
    "use super::classify::{is_caption_line, is_list_item};\n"
)
PREPROCESS_ANCHOR = """    result
}

/// Merge drop caps with the appropriate line.
"""
PREPROCESS_INSERT = r'''    result
}

/// Merge visual continuation lines into the scientific caption that owns them.
///
/// PDF content streams do not carry a generic "caption block" primitive. A
/// multi-line caption is commonly extracted as one prefixed line
/// (`Figure 2. ...`) followed by ordinary-looking visual lines. Leaving those
/// lines separate detaches the label from the explanation a reader treats as
/// one caption and creates false paragraph boundaries.
///
/// The merge is intentionally evidence-heavy. A continuation must stay on the
/// same page, sit at normal caption line spacing, use approximately the same
/// font size, and remain close to the caption's left edge. Small caption type
/// is strong evidence; body-size captions additionally require lowercase text,
/// a hanging indent, or unfinished syntax. A probable heading, list item, or
/// new caption always starts a new block.
pub(crate) fn merge_wrapped_caption_lines(
    lines: Vec<TextLine>,
    base_size: f32,
    para_threshold: f32,
) -> Vec<TextLine> {
    if lines.len() < 2 {
        return lines;
    }

    const MAX_CONTINUATION_LINES: usize = 5;
    const MAX_CAPTION_WORDS: usize = 180;

    let mut result = Vec::with_capacity(lines.len());
    let mut index = 0usize;

    while index < lines.len() {
        let mut caption = lines[index].clone();
        let caption_text = caption.text();
        if !is_caption_line(caption_text.trim()) {
            result.push(caption);
            index += 1;
            continue;
        }

        let Some(first) = caption.items.first() else {
            result.push(caption);
            index += 1;
            continue;
        };
        let caption_size = first.font_size.max(1.0);
        let caption_x = first.x;
        let small_caption_type = caption_size <= base_size * 0.92;
        let mut total_words = caption_text.split_whitespace().count();
        let mut joined = 0usize;
        let mut last_y = caption.y;
        let mut tail_char = caption_text.trim_end().chars().last();

        while index + 1 < lines.len() && joined < MAX_CONTINUATION_LINES {
            let next = &lines[index + 1];
            if next.page != caption.page || next.items.is_empty() {
                break;
            }

            let next_text = next.text();
            let next_trimmed = next_text.trim();
            if next_trimmed.is_empty()
                || is_caption_line(next_trimmed)
                || is_list_item(next_trimmed)
            {
                break;
            }

            let next_first = &next.items[0];
            let y_gap = last_y - next.y;
            let max_line_gap = para_threshold
                .min(caption_size * 1.9)
                .max(caption_size * 1.25);
            if !(y_gap > 0.0 && y_gap <= max_line_gap) {
                break;
            }

            let size_delta = (next_first.font_size - caption_size).abs();
            if size_delta > 1.0_f32.max(caption_size * 0.12) {
                break;
            }

            let x_delta = next_first.x - caption_x;
            if !(-8.0..=84.0).contains(&x_delta) {
                break;
            }

            let next_words = next_trimmed.split_whitespace().count();
            if next_words == 0
                || next_words > 55
                || total_words + next_words > MAX_CAPTION_WORDS
            {
                break;
            }

            // A short all-bold body-size line is much more likely the next
            // section heading than caption prose.
            if next_first.font_size >= base_size * 0.95
                && next_words <= 12
                && line_is_mostly_bold(next)
            {
                break;
            }

            let starts_lowercase = next_trimmed
                .chars()
                .find(|character| character.is_alphabetic())
                .is_some_and(char::is_lowercase);
            let hanging_indent = x_delta >= caption_size * 0.65;
            let unfinished_lead = tail_char
                .is_some_and(|character| matches!(character, ',' | ';' | ':' | '-' | '(' | '['));
            let completed_sentence =
                tail_char.is_some_and(|character| matches!(character, '.' | '!' | '?'));

            // A complete one-line caption followed by an uppercase line at
            // the same margin is normally the article body, even when the
            // publisher uses small type throughout the page.
            if completed_sentence && !starts_lowercase && !hanging_indent {
                break;
            }
            if !small_caption_type && !starts_lowercase && !hanging_indent && !unfinished_lead {
                break;
            }

            if let Some(first_item) = next.items.first() {
                let mut joined_first = first_item.clone();
                joined_first.text = format!(" {}", joined_first.text.trim_start());
                caption.items.push(joined_first);
            }
            caption.items.extend(next.items.iter().skip(1).cloned());
            total_words += next_words;
            joined += 1;
            last_y = next.y;
            tail_char = next_trimmed.chars().last();
            index += 1;
        }

        result.push(caption);
        index += 1;
    }

    result
}

/// Merge drop caps with the appropriate line.
'''

TEST_ANCHOR = '''    fn make_line(text: &str, font_size: f32, page: u32, y: f32, mcid: Option<i64>) -> TextLine {
        TextLine {
            items: vec![make_item(text, font_size, mcid)],
            y,
            page,
            adaptive_threshold: 0.10,
        }
    }

'''
TEST_INSERT = '''    fn make_line(text: &str, font_size: f32, page: u32, y: f32, mcid: Option<i64>) -> TextLine {
        make_line_at(text, font_size, page, 0.0, y, mcid)
    }

    fn make_line_at(
        text: &str,
        font_size: f32,
        page: u32,
        x: f32,
        y: f32,
        mcid: Option<i64>,
    ) -> TextLine {
        let mut item = make_item(text, font_size, mcid);
        item.x = x;
        item.y = y;
        item.page = page;
        TextLine {
            items: vec![item],
            y,
            page,
            adaptive_threshold: 0.10,
        }
    }

    #[test]
    fn merges_small_type_caption_continuations() {
        let lines = vec![
            make_line("Figure 2. The proposed architecture", 9.0, 1, 700.0, None),
            make_line("uses two complementary branches", 9.0, 1, 689.0, None),
            make_line("and a shared prediction head.", 9.0, 1, 678.0, None),
            make_line("Methods begin with data collection.", 12.0, 1, 655.0, None),
        ];

        let result = merge_wrapped_caption_lines(lines, 12.0, 18.0);
        assert_eq!(result.len(), 2);
        assert_eq!(
            result[0].text(),
            "Figure 2. The proposed architecture uses two complementary branches and a shared prediction head."
        );
        assert_eq!(result[1].text(), "Methods begin with data collection.");
    }

    #[test]
    fn caption_merge_stops_before_body_font() {
        let lines = vec![
            make_line("Table 1. Experimental results.", 9.0, 1, 700.0, None),
            make_line("The experiment uses five folds.", 12.0, 1, 688.0, None),
        ];

        assert_eq!(merge_wrapped_caption_lines(lines, 12.0, 18.0).len(), 2);
    }

    #[test]
    fn body_size_caption_needs_continuation_evidence() {
        let separate = vec![
            make_line("Figure 3. System overview.", 12.0, 1, 700.0, None),
            make_line("Methods and Materials", 12.0, 1, 686.0, None),
        ];
        assert_eq!(
            merge_wrapped_caption_lines(separate, 12.0, 18.0).len(),
            2
        );

        let continuation = vec![
            make_line("Figure 3. The system overview", 12.0, 1, 700.0, None),
            make_line(
                "shows the complete inference path.",
                12.0,
                1,
                686.0,
                None,
            ),
        ];
        let merged = merge_wrapped_caption_lines(continuation, 12.0, 18.0);
        assert_eq!(merged.len(), 1);
        assert!(merged[0].text().contains("complete inference path"));
    }

    #[test]
    fn body_size_hanging_caption_continuation_is_preserved() {
        let lines = vec![
            make_line_at(
                "Fig. 4. Evaluation across datasets",
                12.0,
                1,
                72.0,
                700.0,
                None,
            ),
            make_line_at(
                "ImageNet and CIFAR-100 results.",
                12.0,
                1,
                86.0,
                686.0,
                None,
            ),
        ];

        let result = merge_wrapped_caption_lines(lines, 12.0, 18.0);
        assert_eq!(result.len(), 1);
        assert!(result[0].text().contains("ImageNet and CIFAR-100"));
    }

'''

CONVERT_IMPORT = "use super::preprocess::{merge_drop_caps, merge_heading_lines};"
CONVERT_IMPORT_REPLACEMENT = (
    "use super::preprocess::{merge_drop_caps, merge_heading_lines, "
    "merge_wrapped_caption_lines};"
)
CONVERT_PRIMARY_ANCHOR = '''    let para_threshold = compute_paragraph_threshold(&lines, base_size);

    // Merge wrapped bold headings:'''
CONVERT_PRIMARY_INSERT = '''    let para_threshold = compute_paragraph_threshold(&lines, base_size);

    // A caption is often emitted as one prefixed line followed by several
    // unlabelled visual wraps. Join only high-confidence continuations before
    // heading/paragraph classification so the complete caption remains one
    // semantic block.
    let lines = merge_wrapped_caption_lines(lines, base_size, para_threshold);

    // Merge wrapped bold headings:'''
CONVERT_SIMPLE_ANCHOR = '''    // Compute the typical line spacing for paragraph break detection
    let para_threshold = compute_paragraph_threshold(&lines, base_size);

    let isolated_lines = find_isolated_lines(&lines, base_size, para_threshold);'''
CONVERT_SIMPLE_INSERT = '''    // Compute the typical line spacing for paragraph break detection
    let para_threshold = compute_paragraph_threshold(&lines, base_size);
    let lines = merge_wrapped_caption_lines(lines, base_size, para_threshold);

    let isolated_lines = find_isolated_lines(&lines, base_size, para_threshold);'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def apply(root: Path) -> None:
    preprocess = root / "src/markdown/preprocess.rs"
    source = preprocess.read_text()
    source = replace_once(
        source,
        PREPROCESS_IMPORT,
        PREPROCESS_IMPORT_REPLACEMENT,
        "preprocess import",
    )
    source = replace_once(
        source,
        PREPROCESS_ANCHOR,
        PREPROCESS_INSERT,
        "preprocess function",
    )
    source = replace_once(source, TEST_ANCHOR, TEST_INSERT, "preprocess tests")
    preprocess.write_text(source)

    convert = root / "src/markdown/convert.rs"
    source = convert.read_text()
    source = replace_once(
        source,
        CONVERT_IMPORT,
        CONVERT_IMPORT_REPLACEMENT,
        "convert import",
    )
    source = replace_once(
        source,
        CONVERT_PRIMARY_ANCHOR,
        CONVERT_PRIMARY_INSERT,
        "primary converter",
    )
    source = replace_once(
        source,
        CONVERT_SIMPLE_ANCHOR,
        CONVERT_SIMPLE_INSERT,
        "simple converter",
    )
    convert.write_text(source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    apply(Path(args.root).resolve())
