"""DAX-CONTEXT-TRANSITION (§9, agent): verify iterator context transitions.

§9: a measure reference inside a row iterator is implicitly wrapped in
``CALCULATE`` — each iterated row triggers a context transition. Whether that
transition is *intended* (and not happening over a non-unique / duplicate-row
table) needs intent, so this is an agent-judgment rule: we detect the same
construct as the deterministic measure-in-iterator check (an iterator call
containing a bare ``[Measure]`` reference) and hand each such measure to the
agent for review. We emit ONE item per measure, not one per reference.
"""

from __future__ import annotations

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import bracket_refs
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import ITERATOR_FUNCS, iter_calls, line_at, masked


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    measure_names = ctx.catalog.measure_names
    column_names = ctx.catalog.column_names
    items: list[AgentReviewItem] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        refs = bracket_refs(text)
        hit_offset: int | None = None
        for _name, name_offset, args in iter_calls(text, ITERATOR_FUNCS):
            # arg_span returned `args`; its first char sits just past the '('.
            start = text.index("(", name_offset) + 1
            end = start + len(args)
            if any(
                ref.table == ""
                and start <= ref.offset < end
                and normalize(ref.name) in measure_names
                and normalize(ref.name) not in column_names  # collision -> resolves to column
                for ref in refs
            ):
                hit_offset = name_offset if hit_offset is None else min(hit_offset, name_offset)
        if hit_offset is not None:
            items.append(
                ctx.review(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=line_at(measure, hit_offset),
                    note=(
                        "measure reference inside a row iterator — each row triggers an implicit "
                        "CALCULATE (context transition); verify it is intended and not over a "
                        "non-unique / duplicate-row table (§9)."
                    ),
                )
            )
    return items


RULE = Rule(
    id="DAX-CONTEXT-TRANSITION",
    title="Verify iterator context transition is intended",
    severity="info",
    category="context-transition",
    standard_ref="§9",
    tier=2,
    kind="agent",
    detect=detect,
)
