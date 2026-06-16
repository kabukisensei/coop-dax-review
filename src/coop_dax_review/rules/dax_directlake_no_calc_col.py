"""DAX-DIRECTLAKE-NO-CALC-COL (§13): no calculated columns in Direct Lake.

§13 Direct Lake constraints: calculated columns are not supported in a Direct
Lake model. We flag every calculated column (``column.is_calculated``) that
lives on a Direct Lake table — either the table is itself ``directLake``, or
the model as a whole resolves to Direct Lake (``catalog.storage_mode ==
"directLake"``). One finding per offending column, at the column's line.

An import-mode model with calculated columns is fine (no findings); a Direct
Lake model with only regular columns is fine too.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    # Compare case-insensitively: the TMDL parser stores the partition `mode:`
    # token verbatim, so "DirectLake" / "directlake" must also match.
    model_is_dl = ctx.catalog.storage_mode.lower() == "directlake"
    findings: list[Finding] = []
    for table in ctx.catalog.tables:
        if not (table.storage_mode.lower() == "directlake" or model_is_dl):
            continue
        for column in table.columns:
            if not column.is_calculated:
                continue
            findings.append(
                ctx.finding(
                    object=f"{table.name}[{column.name}]",
                    file=table.file,
                    line=column.line,
                    message=(
                        "calculated column in a Direct Lake model — calculated columns are "
                        "not supported in Direct Lake; move the logic upstream into the "
                        "lakehouse/source instead (§13)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-DIRECTLAKE-NO-CALC-COL",
    title="No calculated columns in a Direct Lake model",
    severity="warning",
    category="direct-lake",
    standard_ref="§13",
    tier=2,
    check=check,
)
