"""DAX-VALIDATION (§11, agent): remind to validate non-trivial measures.

§11 is a *process* — test the base measure, exercise key slicers, cover edge
cases (blank/zero/no rows), and compare against known control totals. None of
that is statically verifiable, so this is an agent-judgment rule.

To avoid nagging on every aggregation, detection is scoped to measures that
are non-trivial enough to be worth a deliberate validation pass: those that
use time intelligence (TIME_INTEL_FUNCS), use CALCULATE/CALCULATETABLE, or
carry two or more VARs. A trivial aggregation (e.g. a bare ``SUM`` with no
filters) is left silent.

We emit exactly ONE item per MODEL (issue #16). The per-measure form repeated
an identical, un-actionable "confirm §11 was performed" note for every
non-trivial measure — 163 of 216 agent items on a real estate — burying the
genuinely reviewable items. The model-level item keeps the checklist nudge
(with the qualifying-measure count and a few example names) without the flood.
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
_EXAMPLES_SHOWN = 3


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    non_trivial: list[str] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        funcs = function_names(text)
        if bool(funcs & TIME_INTEL_FUNCS) or bool(funcs & _CALCULATE_FUNCS) or count_vars(text) >= 2:
            non_trivial.append(measure.name)
    if not non_trivial:
        return []
    count = len(non_trivial)
    examples = ", ".join(f"[{name}]" for name in non_trivial[:_EXAMPLES_SHOWN])
    if count > _EXAMPLES_SHOWN:
        examples += ", ..."
    label = "non-trivial measure" if count == 1 else "non-trivial measures"
    return [
        ctx.review(
            object=ctx.model,
            note=(
                f"{count} {label} (e.g. {examples}) — confirm the §11 validation was "
                "performed for each: test the base measure with no filters, test "
                "with/without key slicers, cover edge cases (blank/zero/no rows), and "
                "compare against known control totals."
            ),
        )
    ]


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
