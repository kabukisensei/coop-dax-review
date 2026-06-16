"""DAX-STAR-SCHEMA (§6): prefer a star schema over a snowflake (agent judgment).

§6 prefers a flat star schema over a snowflake. Whether a given snowflake chain
*should* be flattened is a modeling judgment a linter cannot settle, so this is
an agent-judgment rule. It detects the construct with
:func:`snowflake_intermediates` — a table that both filters and is filtered
(a dimension related to another dimension, the snowflake link) — and hands one
review item per intermediate table to the agent. A pure star has no such
intermediates and produces nothing. This is the judgment counterpart to the
deterministic DAX-SNOWFLAKE rule; emitting both for one chain is by design.
"""

from __future__ import annotations

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import snowflake_intermediates


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    intermediates = snowflake_intermediates(ctx.catalog)
    if not intermediates:
        return []  # a pure star schema — nothing to judge
    by_name = {t.name: t for t in ctx.catalog.tables}
    items: list[AgentReviewItem] = []
    for name in intermediates:
        table = by_name.get(name)
        items.append(
            ctx.review(
                object=name,
                file=table.file if table else None,
                line=table.line if table else 0,
                note=(
                    f"'{name}' is an intermediate table with relationships chained through it "
                    "(snowflake) — judge whether to flatten it into a star schema (§6)."
                ),
            )
        )
    return items


RULE = Rule(
    id="DAX-STAR-SCHEMA",
    title="Prefer a star schema over a snowflake",
    severity="info",
    category="modeling",
    standard_ref="§6",
    tier=2,
    kind="agent",
    detect=detect,
)
