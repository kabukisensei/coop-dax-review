"""DAX-COMPLEX-NO-HEADER (§12): complex measures want a /* ... */ header.

§12 shows a header comment block (Measure/Purpose/Context/Dependencies/...)
for complex measures. This advisory rule flags a *complex* measure that has no
``/* ... */`` header block. Complexity is gated by a module constant: a measure
with ``_MIN_VARS`` (3) or more ``VAR`` declarations is "complex". The header
check scans the RAW dax via :func:`has_block_comment` (masking blanks comments,
so a header would otherwise vanish). A simple measure without a header, or any
measure that already carries a ``/* */`` header, never fires. Points at the
measure declaration line.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import count_vars, has_block_comment, masked

# A measure with at least this many VARs is "complex" enough to warrant a
# documenting header block under §12.
_MIN_VARS = 3


def _is_complex(measure_masked: str) -> bool:
    return count_vars(measure_masked) >= _MIN_VARS


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        if has_block_comment(measure.dax):
            continue  # already documented with a /* ... */ header
        if not _is_complex(masked(measure)):
            continue  # simple measure — a header is not expected
        findings.append(
            ctx.finding(
                object=f"[{measure.name}]",
                file=measure.file,
                line=measure.line,
                message=(
                    f"complex measure ({_MIN_VARS}+ VARs) has no /* ... */ header block — "
                    "add a header documenting Purpose/Context/Dependencies (§12)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-COMPLEX-NO-HEADER",
    title="Complex measures carry a /* ... */ header comment",
    severity="info",
    category="comments",
    standard_ref="§12",
    tier=3,
    check=check,
)
