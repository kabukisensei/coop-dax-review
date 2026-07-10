"""DAX-IFERROR-WRAPPING (§24): don't wrap arithmetic in IFERROR.

§24: ``IFERROR`` around division (or arithmetic generally) hides EVERY error —
including real data/logic bugs — and forces the engine into slower row-by-row
error handling. Divide-by-zero belongs to ``DIVIDE()`` (§14, the paired rule);
expected blanks should be tested, not swallowed.

We flag an ``IFERROR(...)`` whose FIRST argument contains an arithmetic
operator (``+ - * /``) — the provably pointless wrap. An IFERROR guarding a
genuine error source with no arithmetic (a ``VALUE(...)`` conversion, a lookup)
is left alone (precision over recall). Matching runs on masked DAX with
identifier contents blanked, so an operator inside a comment, string, or a
name like ``Sales[Net-Gross]`` never counts.
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
    split_top_commas,
)

_IFERROR = frozenset({"iferror"})
_ARITHMETIC_RE = re.compile(r"[+\-*/]")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = blank_identifiers(mask_dax(target.dax))
        for _name, offset, args in iter_calls(text, _IFERROR):
            first = split_top_commas(args)[0]
            if not _ARITHMETIC_RE.search(first):
                continue  # no arithmetic being wrapped — a legitimate guard
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, offset),
                    message=(
                        "wraps arithmetic in IFERROR — it hides real errors and is slower; "
                        "use DIVIDE() for division (§14) and test inputs for expected "
                        "blanks (§24)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-IFERROR-WRAPPING",
    title="Don't wrap arithmetic in IFERROR",
    severity="warning",
    category="operators",
    standard_ref="§24",
    tier=2,
    check=check,
)
