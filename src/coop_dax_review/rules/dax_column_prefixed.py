"""DAX-COLUMN-PREFIXED (§1): columns must be table-prefixed.

§1: columns are referenced ``Table[Column]``, never bare ``[Column]``. A bare
``[X]`` where ``X`` is a known column (and not also a measure) is the
violation. Needs the catalog. Names that are also a measure are skipped — a
bare ``[X]`` is then the correct measure reference, not a naked column — as is
any name that is ambiguous, to keep the rule precise (a false positive on
compliant code erodes trust fastest).
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import bracket_refs
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import line_at, masked


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    measures = ctx.catalog.measure_names
    columns = ctx.catalog.column_names
    for measure in ctx.catalog.measures:
        for ref in bracket_refs(masked(measure)):
            key = normalize(ref.name)
            # Bare reference, known column, not a measure -> needs Table[ ] prefix.
            if not ref.table and key in columns and key not in measures:
                findings.append(
                    ctx.finding(
                        object=f"[{measure.name}]",
                        file=measure.file,
                        line=line_at(measure, ref.offset),
                        message=(
                            f"column reference '[{ref.name}]' is not table-prefixed; "
                            f"columns need a table prefix — use 'Table[{ref.name}]' (§1)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="DAX-COLUMN-PREFIXED",
    title="Column references are table-prefixed",
    severity="warning",
    category="naming",
    standard_ref="§1",
    tier=1,
    check=check,
)
