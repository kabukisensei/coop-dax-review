"""DAX-VALIDATION (§11, agent): remind to validate non-trivial measures.

§11 is a *process* — test the base measure, exercise key slicers, cover edge
cases (blank/zero/no rows), and compare against known control totals. None of
that is statically verifiable, so this is an agent-judgment rule.

To avoid nagging on every aggregation, detection is scoped to measures that
are non-trivial enough to be worth a deliberate validation pass: those that
use time intelligence (TIME_INTEL_FUNCS), use CALCULATE/CALCULATETABLE, or
carry two or more VARs. A trivial aggregation (e.g. a bare ``SUM`` with no
filters) is left silent. We emit exactly ONE item per qualifying measure.
"""

from __future__ import annotations

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import (
    TIME_INTEL_FUNCS,
    count_vars,
    function_names,
    masked,
)

_CALCULATE_FUNCS = frozenset({"calculate", "calculatetable"})


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        funcs = function_names(text)
        non_trivial = (
            bool(funcs & TIME_INTEL_FUNCS) or bool(funcs & _CALCULATE_FUNCS) or count_vars(text) >= 2
        )
        if not non_trivial:
            continue
        items.append(
            ctx.review(
                object=f"[{measure.name}]",
                file=measure.file,
                line=measure.line,
                note=(
                    "non-trivial measure — confirm the §11 validation was performed: "
                    "test the base measure with no filters, test with/without key slicers, "
                    "cover edge cases (blank/zero/no rows), and compare against known "
                    "control totals."
                ),
            )
        )
    return items


RULE = Rule(
    id="DAX-VALIDATION",
    title="Confirm validation checklist for non-trivial measures",
    severity="info",
    category="validation",
    standard_ref="§11",
    tier=2,
    kind="agent",
    detect=detect,
)
