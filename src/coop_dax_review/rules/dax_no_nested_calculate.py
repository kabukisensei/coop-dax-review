"""DAX-NO-NESTED-CALCULATE (§3): never nest CALCULATE directly inside CALCULATE.

§3 says a ``CALCULATE`` *directly* inside another ``CALCULATE`` should be
broken apart with ``VAR``. We scan the comment/string-masked DAX, tag every
call's opening paren with its function, and flag a ``CALCULATE(`` opened while
another ``CALCULATE(`` is still open on the paren stack with **no iterator
frame in between**. When an iterator (``SUMX``/``AVERAGEX``/``FILTER``/...)
mediates the nesting, the inner CALCULATE exists to force a *per-row* context
transition (the §9 idiom) — hoisting it into a VAR would evaluate it once
outside the row context and change results, so that shape is not reported.
CALCULATETABLE counts too (same context-transition trap). The finding points
at the inner ``CALCULATE``'s line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import ITERATOR_FUNCS, blank_identifiers, dax_targets, line_at

# A function call: an identifier (dotted names like PERCENTILEX.INC allowed)
# immediately followed by an opening paren — used to tag each '(' with its
# owning function so the paren stack knows which frames are CALCULATEs and
# which are iterators.
_FUNC_PAREN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_CALC_NAMES = frozenset({"calculate", "calculatetable"})


def _nested_offsets(text: str) -> list[int]:
    """Offsets of every ``CALCULATE`` whose paren opens inside another open
    CALCULATE's parens with no iterator frame between the two."""
    # Blank identifier contents (length-preserving, so offsets/lines are
    # unchanged) so parentheses inside a column/measure name like ``[Net (USD)]``
    # or a quoted table name like ``'Sales (2024)'`` cannot perturb the
    # CALCULATE-depth paren stack.
    text = blank_identifiers(text)
    # Map each call's '(' offset to (function name lower-cased, name offset).
    paren_func: dict[int, tuple[str, int]] = {}
    for match in _FUNC_PAREN_RE.finditer(text):
        paren_func[match.end() - 1] = (match.group(1).lower(), match.start())

    nested: list[int] = []
    stack: list[str] = []  # each open paren's frame kind: "calc" | "iter" | ""
    for idx, char in enumerate(text):
        if char == "(":
            func, name_offset = paren_func.get(idx, ("", idx))
            if func in _CALC_NAMES:
                kind = "calc"
                # Walk the enclosing frames innermost-first: a CALCULATE seen
                # before any iterator means DIRECT nesting (report); an
                # iterator in between is the endorsed per-row idiom (skip).
                for outer in reversed(stack):
                    if outer == "iter":
                        break
                    if outer == "calc":
                        nested.append(name_offset)
                        break
            else:
                kind = "iter" if func in ITERATOR_FUNCS else ""
            stack.append(kind)
        elif char == ")" and stack:
            stack.pop()
    return nested


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    # calc columns / tables / items carry the same context-transition trap (#5/#8).
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = mask_dax(target.dax)
        for offset in _nested_offsets(text):
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, offset),
                    message="nested CALCULATE — break the inner CALCULATE out into a VAR (§3).",
                )
            )
    return findings


RULE = Rule(
    id="DAX-NO-NESTED-CALCULATE",
    title="No CALCULATE nested directly inside another CALCULATE",
    severity="warning",
    category="calculate",
    standard_ref="§3",
    tier=1,
    check=check,
)
