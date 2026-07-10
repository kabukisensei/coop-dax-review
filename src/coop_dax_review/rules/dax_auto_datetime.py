"""DAX-AUTO-DATETIME (§21): flag Power BI auto date/time artifacts.

§21: with auto date/time on, Power BI silently creates one hidden
``LocalDateTable_<guid>`` per date column (plus a ``DateTableTemplate_<guid>``).
These bloat the model and undermine the §8 marked-Date-table discipline. Their
presence in a published model is a deterministic signal the option was left on.
One finding per model, naming the count and a few examples; ``warning``.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext

# Both parsers expose table names verbatim; the guid suffixes vary but the
# prefixes are fixed. Compared lower-cased for case-insensitive robustness.
_AUTO_PREFIXES = ("localdatetable_", "datetabletemplate_")


def check(ctx: RuleContext) -> list[Finding]:
    hits = [t.name for t in ctx.catalog.tables if t.name.lower().startswith(_AUTO_PREFIXES)]
    if not hits:
        return []
    shown = ", ".join(sorted(hits)[:3])
    extra = "" if len(hits) <= 3 else f" (+{len(hits) - 3} more)"
    return [
        ctx.finding(
            object=ctx.catalog.name,
            line=0,
            message=(
                f"{len(hits)} auto date/time table(s) present ({shown}{extra}) — disable Power BI's "
                "auto date/time option and use a single marked Date table for time intelligence (§21)."
            ),
            # The artifact count / example names churn as date columns come and go; the
            # identity is "artifacts are present" (issue #14 — volatile-message rule).
            fingerprint_key="auto date/time artifacts present",
        )
    ]


RULE = Rule(
    id="DAX-AUTO-DATETIME",
    title="Disable auto date/time (no LocalDateTable_/DateTableTemplate_ artifacts)",
    severity="warning",
    category="modeling",
    standard_ref="§21",
    tier=2,
    check=check,
)
