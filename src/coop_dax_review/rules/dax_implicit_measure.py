"""DAX-IMPLICIT-MEASURE (§20, agent): prefer explicit measures over implicit ones.

§20: a visible numeric column with default summarization invites drag-to-aggregate
(implicit) measures instead of defined, documented ones. Whether such a column
*should* instead be hidden / get an explicit measure is a modeling-discipline
call, so this is an agent-judgment rule. We detect a visible, numeric,
auto-summarizing column that is NOT a relationship key (keys are covered by §18)
and hand it to the agent. One item per such column.
"""

from __future__ import annotations

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import NUMERIC_TYPES


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    # Relationship key columns are §18's domain, not implicit-measure candidates.
    keys: set[tuple[str, str]] = set()
    for rel in ctx.catalog.relationships:
        keys.add((normalize(rel.from_table), normalize(rel.from_column)))
        keys.add((normalize(rel.to_table), normalize(rel.to_column)))

    items: list[AgentReviewItem] = []
    for table in ctx.catalog.tables:
        for column in table.columns:
            if column.is_hidden or table.is_hidden:
                continue  # a hidden table hides all its columns from the field list
            if column.data_type.lower() not in NUMERIC_TYPES:
                continue
            if column.summarize_by.lower() == "none":
                continue  # does not auto-aggregate
            if (normalize(table.name), normalize(column.name)) in keys:
                continue  # a relationship key — handled by §18
            items.append(
                ctx.review(
                    object=f"{table.name}[{column.name}]",
                    file=table.file,
                    line=column.line,
                    note=(
                        f"visible numeric column '{table.name}[{column.name}]' auto-aggregates — "
                        "judge whether to replace the implicit aggregation with an explicit "
                        "measure (and hide the column / set summarizeBy: none) (§20)."
                    ),
                )
            )
    return items


RULE = Rule(
    id="DAX-IMPLICIT-MEASURE",
    title="Prefer explicit measures over implicit (drag-to-aggregate) ones",
    severity="info",
    category="modeling",
    standard_ref="§20",
    tier=2,
    kind="agent",
    detect=detect,
)
