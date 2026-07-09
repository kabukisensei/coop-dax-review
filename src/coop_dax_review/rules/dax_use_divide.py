"""DAX-USE-DIVIDE (§14): use DIVIDE() instead of the / operator.

§14: ``/`` raises or returns infinity on divide-by-zero, while ``DIVIDE()``
returns blank (or a supplied alternate). We flag each ``/`` division operator in
a measure — and, since the same hazard applies, in a **calculated column** and a
**calculated table** expression (issue #5). Matching is on the comment/string-
masked DAX with identifier contents (bracket refs AND single-quoted table names)
also blanked, so a ``/`` inside a ``//`` line comment, a ``/* */`` block comment,
a string literal, or an identifier like ``Sales[Net/Gross]`` or
``'Actual/Budget'`` never counts — only a real division operator does. One
finding per occurrence, at the operator's line.

A division whose right-hand operand is a **nonzero numeric literal** — the
scaling idiom ``SUM(Sales[Amount]) / 1000`` or ``[Total Days] / 7`` — cannot
divide by zero, so rewriting it as ``DIVIDE()`` buys nothing (and is slower:
DIVIDE carries the alternate-result branch). Those are skipped (issue #12);
a literal ``0``/``0.0`` divisor is a guaranteed error and still flags. Only
literal divisors (optionally parenthesized, optionally signed) are provably
safe — column/measure/expression divisors keep flagging.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import blank_identifiers, dax_targets, line_at

# A single '/' that is not part of '//' (defensive: masking already blanks
# line comments, but never match a doubled slash as a division operator).
_DIVIDE_RE = re.compile(r"(?<!/)/(?!/)")
# The right-hand operand as a plain numeric literal, anchored right after the
# '/': optional whitespace, optional unary sign, a number token — or the same
# wrapped in one pair of parens like ``/ (100)``. Group ``num``/``pnum`` holds
# the digits so the caller can tell a guaranteed-error 0 from a safe nonzero.
_NUM = r"\d+(?:\.\d*)?|\.\d+"
_LITERAL_DIVISOR_RE = re.compile(
    rf"\s*(?:[-+]\s*)?(?:(?P<num>{_NUM})|\(\s*(?:[-+]\s*)?(?P<pnum>{_NUM})\s*\))"
)


def _nonzero_literal_divisor(text: str, pos: int) -> bool:
    """True if the operand starting at ``pos`` (right after a ``/``) is a
    numeric literal with a nonzero value — a division that provably cannot
    divide by zero."""
    m = _LITERAL_DIVISOR_RE.match(text, pos)
    if not m:
        return False
    return float(m.group("num") or m.group("pnum")) != 0


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = blank_identifiers(mask_dax(target.dax))
        for match in _DIVIDE_RE.finditer(text):
            if _nonzero_literal_divisor(text, match.end()):
                continue  # scaling by a nonzero literal cannot divide by zero (§14 rationale)
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, match.start()),
                    message=(
                        "uses the / operator — prefer DIVIDE() for safe divide-by-zero "
                        "handling (it returns blank instead of an error/Infinity) (§14)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-USE-DIVIDE",
    title="Use DIVIDE() instead of the / operator",
    severity="warning",
    category="operators",
    standard_ref="§14",
    tier=2,
    check=check,
)
