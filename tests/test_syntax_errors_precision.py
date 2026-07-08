"""Precision guard: the structural DAX validator must fire on NOTHING valid.

A false positive on compliant DAX erodes trust fastest, so this runs the
validator over 100% of ``tests/fixtures/`` AND over every measure in the
standards' own ``docs/standards.md`` "Good"/"Bad" example blocks, asserting ZERO
``SYNTAX_ERROR`` diagnostics. (Both the "Good" and the "Bad" standards examples
are structurally sound DAX — the "Bad" ones are semantic anti-patterns like a
nested CALCULATE, not malformed syntax — so both must stay clean.) If this test
ever fails, the checker over-reaches: fix the checker, not this test.
"""

from __future__ import annotations

import re
from pathlib import Path

from coop_dax_review.cli import build_catalogs, discover_inputs
from coop_dax_review.model import Measure, ModelCatalog
from coop_dax_review.parsers.syntax_validation import validate_dax_syntax

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_STANDARDS = Path(__file__).resolve().parent.parent / "docs" / "standards.md"

_DAX_BLOCK_RE = re.compile(r"^```dax\n(.*?)^```", re.M | re.S)
# A measure header: `Name = ...` (or bare `Name =`) at column 0, where Name is a
# display name (letters/digits/spaces/`:`/`%`). Comment / VAR / RETURN lines are
# NOT headers — they belong to the current measure's body.
_HEADER_RE = re.compile(r"^([A-Za-z][\w :%]*?)\s*=\s*(.*)$")


def _measures_from_standards() -> list[tuple[str, str]]:
    """Every measure defined in a ```dax``` block of the standards, as
    ``(name, dax_body)``. A block may hold several (a Good + a Bad example)."""
    text = _STANDARDS.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for block in _DAX_BLOCK_RE.findall(text):
        cur_name: str | None = None
        cur_body: list[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            header = _HEADER_RE.match(line)
            is_header = (
                header is not None
                and not line.startswith((" ", "\t"))
                and not stripped.startswith(("--", "//", "/*", "*", "VAR", "RETURN"))
            )
            if is_header:
                if cur_name is not None:
                    out.append((cur_name, "\n".join(cur_body).strip()))
                cur_name = header.group(1).strip()
                cur_body = [header.group(2)] if header.group(2) else []
            elif cur_name is not None:
                cur_body.append(line)
        if cur_name is not None:
            out.append((cur_name, "\n".join(cur_body).strip()))
    return out


def test_precision_guard_all_fixtures():
    tmdl, bim = discover_inputs((str(_FIXTURES),))
    assert tmdl or bim, "fixtures must contain at least one model to be a meaningful guard"
    catalogs = build_catalogs(tmdl, bim)
    diags = validate_dax_syntax(catalogs)
    assert diags == [], f"validator false-positived on fixtures: {[d.message for d in diags]}"


def test_precision_guard_all_standards_examples():
    measures = _measures_from_standards()
    # Sanity: the extractor actually found the standards' example measures (so an
    # empty extraction can't make this pass vacuously).
    assert len(measures) >= 10, f"expected the standards' example measures, got {len(measures)}"
    cat = ModelCatalog(name="Standards", file="docs/standards.md")
    for name, dax in measures:
        cat.measures.append(Measure(name=name, dax=dax, file="docs/standards.md", line=1, dax_line=1))
    diags = validate_dax_syntax([cat])
    assert diags == [], (
        f"validator false-positived on a standards example measure: {[d.message for d in diags]}"
    )


def test_precision_guard_tricky_valid_identifiers():
    # The named hazards from the plan — parens/brackets inside identifiers,
    # strings, and comments must never miscount.
    cat = ModelCatalog(name="Tricky", file="t.tmdl")
    valid = [
        "CALCULATE([Net (USD)], 'Sales (2024)'[Amount])",
        'IF(x = "[brackets] and (parens)", 1, 2)',
        "SUM(T[x]) /* a (comment) with ] and ) */ + SUM(T[y])",
        "SUMX('Plan/Actuals', [Net/Gross])",
        'CONCATENATEX(T, [Name], "he said ""hi (there)""")',
        "VAR _v = 1\nRETURN\n  _v",
    ]
    for i, dax in enumerate(valid):
        cat.measures.append(Measure(name=f"m{i}", dax=dax, file="t.tmdl", line=1, dax_line=1))
    diags = validate_dax_syntax([cat])
    assert diags == [], f"validator false-positived: {[d.message for d in diags]}"
