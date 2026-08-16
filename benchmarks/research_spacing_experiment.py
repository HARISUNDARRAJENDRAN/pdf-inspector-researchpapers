#!/usr/bin/env python3
"""Build fixtures and evaluate the zero-cost TJ spacing fix.

This script is intentionally dependency-free. It has three subcommands:
  patch <content_stream.rs>  - apply the candidate extraction fix
  fixture <output.pdf>       - generate a tiny style-boundary PDF
  score <baseline.md> <candidate.md> - assert visible spaces are recovered
  speed <baseline-bin> <candidate-bin> <pdf>... - paired latency comparison
"""

from __future__ import annotations

import statistics
import subprocess
import sys
from pathlib import Path


OLD = """                                    } else {
                                        total_width_ts += displacement;
                                        if !is_invisible
                                            && n_val < -space_threshold
                                            && !current_text.is_empty()
                                            && !current_text.ends_with(' ')
                                        {
                                            current_text.push(' ');
                                        }
                                    }
"""

NEW = """                                    } else {
                                        total_width_ts += displacement;
                                        // A positioning adjustment before the first glyph belongs
                                        // to the glyph origin, not the glyph's width. TeX/LaTeX
                                        // commonly starts a new styled TJ array with a negative
                                        // adjustment representing the preceding word space.
                                        // Keeping that adjustment inside the item width makes the
                                        // next stage see a zero inter-item gap and glue words across
                                        // font/style boundaries.
                                        if current_text.is_empty() {
                                            sub_start_width_ts = total_width_ts;
                                        } else if !is_invisible
                                            && n_val < -space_threshold
                                            && !current_text.ends_with(' ')
                                        {
                                            current_text.push(' ');
                                        }
                                    }
"""


def patch(path: Path) -> None:
    source = path.read_text()
    count = source.count(OLD)
    if count != 2:
        raise SystemExit(f"expected two TJ numeric branches, found {count}")
    path.write_text(source.replace(OLD, NEW))


def make_fixture(path: Path) -> None:
    stream = b"""BT
/F1 12 Tf
72 720 Td
[(This)-250(paper)-250(presents)]TJ
/F2 12 Tf
[-250(Sentient)-250(Networks)]TJ
/F1 12 Tf
[(,)-250(and)-250(classifies)-250(into)]TJ
/F2 12 Tf
[-250(Stable)]TJ
/F1 12 Tf
[(,)]TJ
/F2 12 Tf
[-250(Degrading)]TJ
/F1 12 Tf
[(,)-250(and)]TJ
/F2 12 Tf
[-250(Unstable)]TJ
/F1 12 Tf
[-250(states.)]TJ
0 -24 Td
[(accuracy)-250(of)]TJ
/F3 12 Tf
[-250(96.84%)]TJ
/F1 12 Tf
[(,)-250(precision)-250(of)]TJ
/F3 12 Tf
[-250(96.59%)]TJ
/F1 12 Tf
[(.)]TJ
ET
"""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R /F3 6 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n".encode()
    data += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        data += f"{off:010d} 00000 n \n".encode()
    data += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(data)


def score(base_path: Path, candidate_path: Path) -> None:
    base = base_path.read_text()
    candidate = candidate_path.read_text()
    expected = [
        "presents *Sentient Networks*",
        "into *Stable*",
        ", *Degrading*",
        "and *Unstable* states",
        "of **96.84%**",
        "of **96.59%**",
    ]
    base_score = sum(value in base for value in expected)
    candidate_score = sum(value in candidate for value in expected)
    print(f"SPACING_SCORE baseline={base_score}/{len(expected)} candidate={candidate_score}/{len(expected)}")
    print("BASELINE:")
    print(base)
    print("CANDIDATE:")
    print(candidate)
    if candidate_score != len(expected):
        raise SystemExit("candidate did not recover every expected visible word space")
    if candidate_score <= base_score:
        raise SystemExit("candidate did not improve spacing fidelity")


def run_speed(binary: str, papers: list[str]) -> tuple[int, int, int]:
    out = subprocess.check_output([binary, *papers], text=True).strip().split()
    return int(out[0]), int(out[1]), int(out[2])


def speed(base: str, candidate: str, papers: list[str]) -> None:
    for _ in range(3):
        run_speed(base, papers)
        run_speed(candidate, papers)

    base_runs: list[int] = []
    candidate_runs: list[int] = []
    for i in range(18):
        order = (base, candidate) if i % 2 == 0 else (candidate, base)
        for binary in order:
            ns, _digest, _size = run_speed(binary, papers)
            (base_runs if binary == base else candidate_runs).append(ns)

    base_median = statistics.median(base_runs)
    candidate_median = statistics.median(candidate_runs)
    delta = (candidate_median - base_median) / base_median * 100.0
    print(
        f"SPEED baseline={base_median / 1e6:.3f}ms "
        f"candidate={candidate_median / 1e6:.3f}ms delta={delta:+.3f}%"
    )
    print("BASE_SAMPLES", [round(x / 1e6, 3) for x in base_runs])
    print("CANDIDATE_SAMPLES", [round(x / 1e6, 3) for x in candidate_runs])
    if candidate_median > base_median * 1.01:
        raise SystemExit(f"candidate regressed median latency by {delta:.3f}%")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: research_spacing_experiment.py <patch|fixture|score|speed> ...")
    command = sys.argv[1]
    if command == "patch" and len(sys.argv) == 3:
        patch(Path(sys.argv[2]))
    elif command == "fixture" and len(sys.argv) == 3:
        make_fixture(Path(sys.argv[2]))
    elif command == "score" and len(sys.argv) == 4:
        score(Path(sys.argv[2]), Path(sys.argv[3]))
    elif command == "speed" and len(sys.argv) >= 5:
        speed(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        raise SystemExit("invalid arguments")


if __name__ == "__main__":
    main()
