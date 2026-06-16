"""DAX-MARKED-DATE-TABLE (§8): time intelligence needs a marked Date table.

§8 requires a contiguous, *marked* Date table for time intelligence. This is
a model+text rule: it triggers only when the model actually uses a
time-intelligence function (so a model with no time logic is never nagged),
and then fires once at the model level if no table is marked as a Date table
(no column with ``dataCategory: Time`` / date-table template). The finding
names the measures whose time-intel use motivated it.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import TIME_INTEL_FUNCS, function_names, masked


def check(ctx: RuleContext) -> list[Finding]:
    if ctx.catalog.date_table is not None:
        return []  # a Date table is marked — time intelligence is supported

    users: list[str] = []
    for measure in ctx.catalog.measures:
        if function_names(masked(measure)) & TIME_INTEL_FUNCS:
            users.append(f"[{measure.name}]")
    if not users:
        return []  # no time intelligence in the model -> rule does not apply

    shown = ", ".join(sorted(users)[:5])
    extra = "" if len(users) <= 5 else f" (+{len(users) - 5} more)"
    return [
        ctx.finding(
            object=ctx.catalog.name,
            line=0,
            message=(
                f"time-intelligence functions are used ({shown}{extra}) but no table is marked as a "
                "Date table — mark a contiguous Date table for time intelligence (§8)."
            ),
        )
    ]


RULE = Rule(
    id="DAX-MARKED-DATE-TABLE",
    title="A marked Date table exists when time intelligence is used",
    severity="warning",
    category="time-intelligence",
    standard_ref="§8",
    tier=1,
    check=check,
)
