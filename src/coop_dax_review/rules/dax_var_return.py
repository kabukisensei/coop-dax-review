"""DAX-VAR-RETURN (§2): non-trivial measures should use VAR/RETURN.

§2 makes VAR/RETURN the house style for readability and to avoid repeating
logic. We don't want to nag genuinely trivial measures — a bare
``SUM(Sales[x])`` or a single ``CALCULATE(...)`` reads fine inline and the §2
Good example only earns VAR/RETURN because it has real intermediate steps.

So this fires only when a measure (a) lacks a VAR/RETURN structure AND (b) is
"non-trivial", measured as having at least ``_MIN_FUNCTIONS`` function calls in
its (comment/string-masked) DAX. Threshold rationale: the §2 Bad example
``CALCULATE(SUM(...), DATESBETWEEN(..., MIN(...), MAX(...)))`` packs five calls
into one line, while the trivial cases we must stay silent on top out at two
(``CALCULATE(SUM(...))``). A cutoff of 3 cleanly separates them and favors
precision — a one- or two-call measure never fires, so compliant simple
aggregations are safe.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import blank_identifiers, has_var_return, masked

# A measure with this many (or more) function calls and no VAR/RETURN is
# considered non-trivial. Kept conservative so simple one-liners don't fire.
_MIN_FUNCTIONS = 3

# Same call shape as helpers._CALL_RE: an identifier (dotted names allowed)
# immediately followed by '('. We count occurrences (not distinct names) so a
# measure that calls the same function repeatedly still reads as non-trivial.
_CALL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\s*\(")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    min_functions = ctx.param("min_functions", _MIN_FUNCTIONS)  # tunable in rules.yml
    for measure in ctx.catalog.measures:
        text = masked(measure)
        if has_var_return(text):
            continue
        # Blank identifier contents so a paren inside a column/measure name
        # (``[Amount (USD)]``) or a quoted table name (``'Sales (2024)'``) is
        # not miscounted as a phantom function call.
        if len(_CALL_RE.findall(blank_identifiers(text))) < min_functions:
            continue  # trivial enough to read inline
        findings.append(
            ctx.finding(
                object=f"[{measure.name}]",
                file=measure.file,
                line=measure.line,
                message=(
                    "non-trivial measure has no VAR/RETURN structure — break the logic into "
                    "named VARs with a RETURN for readability (§2)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-VAR-RETURN",
    title="Non-trivial measures use VAR/RETURN structure",
    severity="info",
    category="structure",
    standard_ref="§2",
    tier=2,
    check=check,
)
