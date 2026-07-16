"""DAX-HIGH-CARDINALITY-TEXT: flag text/string columns with cardinality over a threshold.

High-cardinality text columns are primary offenders for exploding dictionary sizes in
VertiPaq. This rule uses VPAX cardinality stats (if provided) and flags any column
typed `string` with cardinality > `threshold`.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    threshold = int(ctx.param("threshold", 1_000_000))
    findings: list[Finding] = []
    
    for table in ctx.catalog.tables:
        for column in table.columns:
            if column.cardinality is None:
                continue
            
            if column.data_type.lower() == "string" and column.cardinality > threshold:
                findings.append(
                    ctx.finding(
                        object=f"{table.name}[{column.name}]",
                        file=table.file,
                        line=column.line,
                        message=(
                            f"text column '{table.name}[{column.name}]' has high cardinality "
                            f"({column.cardinality:,} > {threshold:,}). Text dictionaries "
                            "scale poorly; consider splitting, removing, or changing the type."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="DAX-HIGH-CARDINALITY-TEXT",
    title="High-cardinality text columns",
    severity="warning",
    category="performance",
    standard_ref="§PERF",
    tier=2,
    check=check,
    params={"threshold": 1_000_000},
)
