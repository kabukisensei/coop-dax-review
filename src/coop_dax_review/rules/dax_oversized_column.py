"""DAX-OVERSIZED-COLUMN: flag columns that dominate the model's footprint.

Uses VPAX size_bytes (if provided). Flags any column that exceeds both a raw
byte threshold (default 50MB) and a percentage of the total model size (default 20%).
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    threshold_pct = float(ctx.param("threshold_pct", 20.0))
    min_bytes = int(ctx.param("min_bytes", 50_000_000))
    
    total_model_size = 0
    for table in ctx.catalog.tables:
        for column in table.columns:
            if column.size_bytes is not None:
                total_model_size += column.size_bytes
                
    if total_model_size == 0:
        return []

    findings: list[Finding] = []
    
    for table in ctx.catalog.tables:
        for column in table.columns:
            if column.size_bytes is None:
                continue
            
            if column.size_bytes >= min_bytes:
                pct = (column.size_bytes / total_model_size) * 100
                if pct > threshold_pct:
                    mb = column.size_bytes / (1024 * 1024)
                    findings.append(
                        ctx.finding(
                            object=f"{table.name}[{column.name}]",
                            file=table.file,
                            line=column.line,
                            message=(
                                f"column '{table.name}[{column.name}]' is oversized: "
                                f"{mb:.1f}MB ({pct:.1f}% of total model size). "
                                f"Consider if it can be optimized or removed."
                            ),
                        )
                    )
    return findings


RULE = Rule(
    id="DAX-OVERSIZED-COLUMN",
    title="Oversized columns",
    severity="warning",
    category="performance",
    standard_ref="§PERF",
    tier=2,
    check=check,
    params={"threshold_pct": 20.0, "min_bytes": 50000000},
)
