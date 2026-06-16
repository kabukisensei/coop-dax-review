"""DAX-MEASURE-NOT-PREFIXED (§1): measures take no table prefix.

§1: measures are referenced bare (``[Measure]``), never ``Table[Measure]``.
A qualified reference ``Table[X]`` where ``X`` is a known measure name is the
violation. Needs the catalog — only it knows which bracket names are measures.
We skip names that are also a column on some table (``Table[X]`` is then a
legitimate column reference) to stay precise.
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
            if ref.table and key in measures and key not in columns:
                findings.append(
                    ctx.finding(
                        object=f"[{measure.name}]",
                        file=measure.file,
                        line=line_at(measure, ref.offset),
                        message=(
                            f"measure reference '{ref.table}[{ref.name}]' is table-prefixed; "
                            f"measures take no table prefix — use '[{ref.name}]' (§1)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="DAX-MEASURE-NOT-PREFIXED",
    title="Measure references are not table-prefixed",
    severity="warning",
    category="naming",
    standard_ref="§1",
    tier=1,
    check=check,
)
