"""DAX-MEASURE-CATEGORY (§1): measures are named ``[Category: Name]``.

§1's naming table requires every measure to carry a ``Category: Name`` prefix
(e.g. ``Sales: Total Revenue``). We flag any measure whose name lacks a
``<category>: <name>`` shape — a non-empty category, a colon, then a
non-empty name. The catalog stores the name un-bracketed, so we match on the
bare name.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext

# "<category>: <name>": at least one non-colon char, a colon, a space, a name.
_CATEGORY_RE = re.compile(r"^[^:]+:\s+.+$")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        if not _CATEGORY_RE.match(measure.name.strip()):
            findings.append(
                ctx.finding(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=measure.line,
                    message=(
                        f"measure '{measure.name}' is not named '[Category: Name]' "
                        "(e.g. '[Sales: Total Revenue]') (§1)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-MEASURE-CATEGORY",
    title="Measures are named [Category: Name]",
    severity="warning",
    category="naming",
    standard_ref="§1",
    tier=1,
    check=check,
)
