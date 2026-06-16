"""DAX-SNOWFLAKE (§6): prefer a flat star schema over a snowflake.

§6 prefers a star schema for Power BI semantic models: dimensions kept flat
and denormalized, related directly to the fact, with no chaining through
intermediate tables. An *intermediate* table — one that is on the one-side of
one relationship and the many-side of another (a dimension related to another
dimension) — is a snowflake chain link. We flag each such table once at the
model level. A pure star (fact -> dims only, no dim -> dim) fires nothing.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import snowflake_intermediates


def check(ctx: RuleContext) -> list[Finding]:
    intermediates = set(snowflake_intermediates(ctx.catalog))
    if not intermediates:
        return []
    findings: list[Finding] = []
    for table in ctx.catalog.tables:
        if table.name not in intermediates:
            continue
        findings.append(
            ctx.finding(
                object=table.name,
                file=table.file,
                line=table.line,
                message=(
                    f"snowflake chain link: '{table.name}' is an intermediate table "
                    "(on the one-side of one relationship and the many-side of another, "
                    "so relationships are chained through it). Prefer a flat star schema — "
                    "relate dimensions directly to the fact and denormalize intermediate "
                    "tables where practical (§6)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-SNOWFLAKE",
    title="Star schema preferred over snowflake",
    severity="info",
    category="modeling",
    standard_ref="§6",
    tier=2,
    check=check,
)
