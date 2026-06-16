"""DAX-USE-DIVIDE (§14): use DIVIDE() instead of the / operator.

§14: ``/`` raises or returns infinity on divide-by-zero, while ``DIVIDE()``
returns blank (or a supplied alternate). We flag each ``/`` division operator in
a measure. Matching is on the comment/string-masked DAX with bracket-reference
contents also blanked, so a ``/`` inside a ``//`` line comment, a ``/* */``
block comment, a string literal, or an identifier like ``Sales[Net/Gross]``
never counts — only a real division operator does. One finding per occurrence,
at the operator's line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import blank_brackets, line_at, masked

# A single '/' that is not part of '//' (defensive: masking already blanks
# line comments, but never match a doubled slash as a division operator).
_DIVIDE_RE = re.compile(r"(?<!/)/(?!/)")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        text = blank_brackets(masked(measure))
        for match in _DIVIDE_RE.finditer(text):
            findings.append(
                ctx.finding(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=line_at(measure, match.start()),
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
