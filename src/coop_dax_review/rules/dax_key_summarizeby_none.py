"""DAX-KEY-SUMMARIZEBY-NONE (§18): key columns should not auto-aggregate.

§18: a numeric relationship key column with default summarization can be dragged
onto a visual and silently summed. We check both endpoints of every
relationship and flag a numeric key column whose ``summarizeBy`` is not
``none`` — including the empty/default case, since a numeric column defaults to
summing. A hidden key column (its own ``isHidden``, or a column of a hidden
table — hiding a table removes all its fields from the report field list) is
skipped: it cannot be dragged onto a visual, so the drag-to-sum risk §18 guards
against doesn't exist; whether the key SHOULD be hidden is §17's call. One
finding per offending key column.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import NUMERIC_TYPES


def check(ctx: RuleContext) -> list[Finding]:
    by_key = {(normalize(t.name), normalize(c.name)): (t, c) for t in ctx.catalog.tables for c in t.columns}
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rel in ctx.catalog.relationships:
        for table_name, col_name in (
            (rel.from_table, rel.from_column),
            (rel.to_table, rel.to_column),
        ):
            key = (normalize(table_name), normalize(col_name))
            if key in seen:
                continue
            entry = by_key.get(key)
            if entry is None:
                continue
            table, column = entry
            if column.data_type.lower() not in NUMERIC_TYPES:
                continue  # only numeric keys auto-aggregate
            if column.is_hidden or table.is_hidden:
                continue  # not in the field list — can't be dragged and summed
            if column.summarize_by.lower() == "none":
                continue  # already set correctly
            seen.add(key)
            findings.append(
                ctx.finding(
                    object=f"{table_name}[{col_name}]",
                    file=table.file,
                    line=column.line,
                    message=(
                        f"numeric key column '{table_name}[{col_name}]' auto-aggregates — set "
                        "summarizeBy: none so it isn't accidentally summed on a visual (§18)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-KEY-SUMMARIZEBY-NONE",
    title="Numeric key columns set summarizeBy none",
    severity="info",
    category="modeling",
    standard_ref="§18",
    tier=2,
    check=check,
)
