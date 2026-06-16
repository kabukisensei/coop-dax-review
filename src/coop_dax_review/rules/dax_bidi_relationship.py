"""DAX-BIDI-RELATIONSHIP (§7): avoid bidirectional physical relationships.

§7: bidirectional cross-filtering should not be baked into the model; where
cross-filtering is needed, do it with a targeted ``CROSSFILTER`` inside a
measure. We flag every relationship whose ``crossFilteringBehavior`` is
``bothDirections`` (captured as ``cross_filter == "both"``).
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for rel in ctx.catalog.relationships:
        if rel.cross_filter == "both":
            findings.append(
                ctx.finding(
                    object=rel.label,
                    file=rel.file,
                    line=rel.line,
                    message=(
                        "bidirectional relationship — avoid by default; use a targeted "
                        "CROSSFILTER(...) inside the measures that need it (§7)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-BIDI-RELATIONSHIP",
    title="No bidirectional physical relationships",
    severity="warning",
    category="relationships",
    standard_ref="§7",
    tier=1,
    check=check,
)
