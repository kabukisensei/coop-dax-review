"""DAX-NO-GRATUITOUS-CALCULATE (§29): no single-argument CALCULATE in measures.

§29: MUST NOT wrap a basic scalar expression or straightforward aggregation in
``CALCULATE`` when no filter, relationship, or context-transition behavior is
needed. A single-argument ``CALCULATE`` in a plain measure manipulates nothing
and misleads the reader into looking for a filter override that does not exist.

Detection is a masked-text scan of measures for ``CALCULATE`` / ``CALCULATETABLE``
calls whose argument list holds exactly one argument (``split_top_commas`` on the
call span). Two deliberate exclusions keep precision:

- **Row context.** A single-argument ``CALCULATE`` inside an iterator (``SUMX``,
  ``FILTER``, ``ADDCOLUMNS``, …) is row-to-filter context transition — the §30
  case 3 / §32 pattern, intentional or not — so the call is skipped when it sits
  inside any row-context function's argument span. Calculated columns are row
  context by definition, so the rule scans measures only (``dax_targets``
  default), matching §29's "basic measures" scope.
- **Nested single-argument CALCULATE.** In ``CALCULATE(CALCULATE(SUM(x)))`` both
  calls qualify; the rule defers to the innermost one so the construct produces
  a single finding (the nesting itself is §3's concern).

Identifier contents are blanked before scanning, so a column named
``[CALCULATE(]`` or ``CALCULATE(`` inside a string or comment can never fire.
One finding per flagged call, at the call's line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import (
    blank_identifiers,
    dax_targets,
    iter_calls,
    line_at,
)

_CALCULATE = frozenset({"calculate", "calculatetable"})

# Functions whose arguments evaluate in a row context. Inside one of these a
# single-argument CALCULATE is context transition (§30 case 3), not noise.
_ROW_CONTEXT_FUNCS = frozenset(
    {
        "filter",
        "sumx",
        "averagex",
        "countx",
        "countax",
        "minx",
        "maxx",
        "productx",
        "concatenatex",
        "geomeanx",
        "medianx",
        "percentilex.inc",
        "percentilex.exc",
        "stdevx.p",
        "stdevx.s",
        "varx.p",
        "varx.s",
        "rankx",
        "topn",
        "addcolumns",
        "selectcolumns",
        "generate",
        "generateall",
    }
)

# A span whose whole content is another CALCULATE call — the outer call defers
# to the inner one so a nested single-argument chain fires once.
_NESTED_CALC_RE = re.compile(r"^\s*CALCULATE(?:TABLE)?\s*\(", re.IGNORECASE)


def _open_paren(text: str, name_offset: int) -> int:
    """Index of the ``(`` opening the call whose name starts at ``name_offset``."""
    return text.find("(", name_offset)


def _top_comma_indices(text: str) -> list[int]:
    """Indices of depth-0 commas in identifier-blanked call-span text.

    Blank ``split_top_commas`` output cannot be used for argument counting here:
    an argument that is ONLY a measure reference (``CALCULATE([Sales: Revenue],
    ...)``) blanks to pure whitespace and would be miscounted as no argument.
    Instead the comma positions are found in the blanked text (paren-safe) and
    applied to the aligned unblanked span, which is length-identical.
    """
    indices: list[int] = []
    depth = 0
    for idx, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            indices.append(idx)
    return indices


def _arg_count(blanked_args: str, raw_args: str) -> int:
    """Number of call arguments: comma-split positions from the blanked span,
    emptiness judged on the raw span (a blanked measure ref still counts)."""
    bounds = [-1, *_top_comma_indices(blanked_args), len(blanked_args)]
    segments = [raw_args[bounds[i] + 1 : bounds[i + 1]] for i in range(len(bounds) - 1)]
    return len([s for s in segments if s.strip()])


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in dax_targets(ctx.catalog):  # measures only: calc columns are row context
        raw = mask_dax(target.dax)
        text = blank_identifiers(raw)
        # Argument spans of every row-context function in the measure, as
        # (open_paren, close_paren) index pairs to test containment against.
        row_context_spans = []
        for _, off, args in iter_calls(text, _ROW_CONTEXT_FUNCS):
            open_paren = _open_paren(text, off)
            row_context_spans.append((open_paren, open_paren + len(args) + 1))
        for name, off, args in iter_calls(text, _CALCULATE):
            open_paren = _open_paren(text, off)
            raw_args = raw[open_paren + 1 : open_paren + 1 + len(args)]
            if _arg_count(args, raw_args) != 1:
                continue  # filter arguments present — CALCULATE is doing its job
            if _NESTED_CALC_RE.match(args):
                continue  # defer to the innermost single-argument CALCULATE
            if any(start < open_paren < end for start, end in row_context_spans):
                continue  # context transition inside an iterator — §30 case 3
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, off),
                    message=(
                        f"single-argument {name.upper()} manipulates no filters — write the "
                        "aggregation directly (§29). Inside a row context this shape is "
                        "context transition and must be intentional (§30)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-NO-GRATUITOUS-CALCULATE",
    title="No single-argument CALCULATE in measures",
    severity="warning",
    category="calculate",
    standard_ref="§29",
    tier=2,
    check=check,
)
