"""DAX-SIMPLE-FUNCTIONS (§10, agent): prefer simple functions, CALCULATE only when needed.

§10 ("Start Simple, Then Complexify" / "Prefer Simple Functions") says to lean on
``VAR`` and basic functions and reach for ``CALCULATE`` only when necessary. Whether a
given measure's use of ``CALCULATE`` (or other heavy machinery) is *justified* is a
stylistic call the linter cannot make, so this is an agent-judgment rule.

To stay PRECISE and avoid flooding, we detect a single, unambiguous over-use signal:
a measure that calls ``CALCULATE`` / ``CALCULATETABLE`` two or more times (counted on
the comment/string-masked DAX so keywords inside comments or strings never count).
A trivial measure — a single ``SUM``, or a single justified ``CALCULATE`` — never fires.
We emit at most ONE item per measure and hand it to the agent to judge whether simpler
functions would suffice (§10).
"""

from __future__ import annotations

import re

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import masked

# CALCULATE or CALCULATETABLE used as a call (keyword directly followed by '(').
_CALC_CALL_RE = re.compile(r"\bCALCULATE(?:TABLE)?\b\s*\(", re.IGNORECASE)

# Threshold of 3: the §3 Good example uses two separate CALCULATE in distinct
# VARs (the endorsed alternative to nesting), so 2 would flag compliant DAX.
# Three or more CALCULATE calls is a clearer "is this simpler-able?" signal.
_MIN_CALCULATES = 3


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    min_calculates = ctx.param("min_calculates", _MIN_CALCULATES)  # tunable in rules.yml
    for measure in ctx.catalog.measures:
        text = masked(measure)
        calc_count = len(_CALC_CALL_RE.findall(text))
        if calc_count >= min_calculates:
            items.append(
                ctx.review(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=measure.line,
                    note=(
                        f"uses CALCULATE {calc_count} times — judge whether simpler functions "
                        "(VAR + basic aggregations) would do, reserving CALCULATE for where it is "
                        "actually needed (§10)."
                    ),
                )
            )
    return items


RULE = Rule(
    id="DAX-SIMPLE-FUNCTIONS",
    title="Prefer simple functions; use CALCULATE only when needed",
    severity="info",
    category="style",
    standard_ref="§10",
    tier=2,
    kind="agent",
    detect=detect,
)
