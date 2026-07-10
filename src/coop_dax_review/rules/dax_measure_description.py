"""DAX-MEASURE-DESCRIPTION (§25): every visible measure carries a description.

§25: a description is the documentation report authors see on hover, and what
Copilot/Q&A read to choose and explain measures. The parser captures TMDL
``///`` doc-comments and the ``.bim`` ``description`` property into
``Measure.description``, so this is a catalog lookup: flag each VISIBLE
measure whose description is empty. Hidden measures — and measures on hidden
tables, which the field list hides the same way — are internal helpers and
exempt (mirrors DAX-FORMAT-STRING's visibility rule).
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    hidden_tables = ctx.catalog.hidden_tables
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        if measure.is_hidden or normalize(measure.table) in hidden_tables:
            continue  # internal helper — not shown in the field list
        if measure.description.strip():
            continue
        findings.append(
            ctx.finding(
                object=f"[{measure.name}]",
                file=measure.file,
                line=measure.line,
                message=(
                    f"visible measure '{measure.name}' has no description — add a /// "
                    "doc-comment (TMDL) or description (.bim); descriptions are what report "
                    "authors and Copilot/Q&A read (§25)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-MEASURE-DESCRIPTION",
    title="Every visible measure carries a description",
    severity="info",
    category="documentation",
    standard_ref="§25",
    tier=3,
    check=check,
)
