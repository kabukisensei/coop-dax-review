"""DAX-MARKED-DATE-TABLE (§8): time intelligence needs a marked Date table.

§8 requires a contiguous, *marked* Date table for time intelligence. This is
a model+text rule: it triggers only when the model actually uses a
time-intelligence function — in a measure OR in a calculated column, which
carries exactly the same requirement — and then fires once at the model level
if no table is marked as a Date table (no column with ``dataCategory: Time`` /
date-table template). The finding names the measures (``[Name]``), calculated
columns (``Table[Name]``), and calculation-group items (``Group[Item]``, issue
#8 — time-intel wrappers are a calc group's whole point) whose use motivated it.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import TIME_INTEL_FUNCS, function_names, masked


def check(ctx: RuleContext) -> list[Finding]:
    if ctx.catalog.date_table is not None:
        return []  # a Date table is marked — time intelligence is supported

    users: list[str] = []
    for measure in ctx.catalog.measures:
        if function_names(masked(measure)) & TIME_INTEL_FUNCS:
            users.append(f"[{measure.name}]")
    for table in ctx.catalog.tables:
        for column in table.columns:
            if column.expression and function_names(mask_dax(column.expression)) & TIME_INTEL_FUNCS:
                users.append(f"{table.name}[{column.name}]")
    for item in ctx.catalog.calculation_items:
        if item.dax and function_names(mask_dax(item.dax)) & TIME_INTEL_FUNCS:
            users.append(f"{item.table}[{item.name}]")
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
            # The example list / (+N more) count churns as time-intel users come and
            # go; the identity is "no marked Date table" (issue #14 — volatile-message rule).
            fingerprint_key="no marked date table",
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
