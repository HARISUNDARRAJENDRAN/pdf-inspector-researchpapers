#!/usr/bin/env python3
"""Loader for the research fidelity audit implementation."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _part in sorted(_ROOT.glob("audit_part_*.py")):
    exec(compile(_part.read_text(encoding="utf-8"), str(_part), "exec"), globals(), globals())
