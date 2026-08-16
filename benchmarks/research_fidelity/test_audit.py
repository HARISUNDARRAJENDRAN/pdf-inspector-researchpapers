from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name("audit.py")
SPEC = importlib.util.spec_from_file_location("research_fidelity_audit", MODULE_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class ReferenceParsingTests(unittest.TestCase):
    def test_arxiv_html_structure(self) -> None:
        html = """
        <html><body><article class="ltx_document">
          <h1 class="ltx_title_document">A Paper</h1>
          <h2>1 Introduction</h2>
          <p>This is a paragraph with <math alttext="x = y + 1">x=y+1</math>.</p>
          <figure><figcaption>Figure 1: Model.</figcaption></figure>
          <table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
        </article></body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "reference.html"
            path.write_text(html)
            reference = AUDIT.parse_arxiv_html(path)
        self.assertEqual(reference.title, "A Paper")
        self.assertIn("1 Introduction", reference.headings)
        self.assertEqual(reference.tables[0][1], ["1", "2"])
        self.assertIn("x = y + 1", reference.equations)

    def test_pmc_jats_structure(self) -> None:
        xml = """
        <article xmlns:mml="http://www.w3.org/1998/Math/MathML">
          <front><article-meta><title-group><article-title>JATS Paper</article-title></title-group>
          <abstract><p>Abstract text.</p></abstract></article-meta></front>
          <body><sec><title>Methods</title><p>Method text.</p>
          <fig><caption><p>Fig 1. Result.</p></caption></fig>
          <table-wrap><caption><p>Table 1.</p></caption><table>
          <tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr>
          </table></table-wrap>
          <disp-formula><mml:math><mml:mi>x</mml:mi><mml:mo>=</mml:mo><mml:mn>1</mml:mn></mml:math></disp-formula>
          </sec></body>
        </article>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "reference.xml"
            path.write_text(xml)
            reference = AUDIT.parse_pmc_jats(path)
        self.assertEqual(reference.title, "JATS Paper")
        self.assertEqual(reference.headings, ["Methods"])
        self.assertEqual(reference.tables[0][1], ["x", "y"])
        self.assertIn("x = 1", reference.equations)


class MetricTests(unittest.TestCase):
    def reference(self) -> object:
        return AUDIT.ReferenceDocument(
            title="A Paper",
            full_text="A Paper Introduction This method predicts stable networks x y 1 Figure 1 Model A B 1 2",
            core_text="A Paper Introduction This method predicts stable networks x y 1 Figure 1 Model A B 1 2",
            headings=["A Paper", "Introduction"],
            paragraphs=["This method predicts stable networks"],
            captions=["Figure 1 Model"],
            tables=[[ ["A", "B"], ["1", "2"] ]],
            equations=["x = y + 1"],
            reference_kind="test",
            reference_quality="test",
        )

    def test_exact_markdown_scores_high(self) -> None:
        markdown = """# A Paper

## Introduction

This method predicts stable networks. x = y + 1

Figure 1 Model

| A | B |
|---|---|
| 1 | 2 |
"""
        metrics = AUDIT.calculate_metrics(self.reference(), markdown)
        self.assertGreater(metrics["word_f1"], 0.98)
        self.assertGreater(metrics["bigram_f1"], 0.90)
        self.assertGreater(metrics["table_score"], 0.95)
        self.assertNotIn("spacing", metrics["failure_labels"])

    def test_spacing_detector_finds_glued_words(self) -> None:
        reference = AUDIT.word_tokens("presents Sentient Networks and Stable states")
        predicted = AUDIT.word_tokens("presentsSentient Networks and Stable states")
        glued, split = AUDIT.spacing_error_counts(reference, predicted)
        self.assertEqual(glued, 1)
        self.assertEqual(split, 0)

    def test_local_duplicate_rate_detects_immediate_repeat(self) -> None:
        tokens = AUDIT.word_tokens("one two three four five six seven eight nine ten eleven twelve")
        repeated = tokens + tokens
        self.assertGreater(AUDIT.local_duplicate_rate(repeated, size=4, window=50), 0.2)


if __name__ == "__main__":
    unittest.main()
