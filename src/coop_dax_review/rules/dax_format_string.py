"""DAX-FORMAT-STRING (§15): every measure declares an explicit formatString.

§15: a measure without an explicit ``formatString`` renders inconsistently
across visuals. We flag every measure whose ``format_string`` is empty. A
dynamic ``formatStringDefinition`` counts as having a format (the parser records
it as ``"<dynamic>"``), so those are not flagged. Model-level rule; one finding
per measure, at the measure's declaration line.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        if measure.format_string.strip():
            continue
        findings.append(
            ctx.finding(
                object=f"[{measure.name}]",
                file=measure.file,
                line=measure.line,
                message=(
                    f"measure '{measure.name}' has no formatString — declare one so it renders "
                    "consistently across visuals (§15)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-FORMAT-STRING",
    title="Every measure declares an explicit format string",
    severity="warning",
    category="formatting",
    standard_ref="§15",
    tier=2,
    check=check,
)
