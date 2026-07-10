"""DAX-EARLIER-TO-VAR (§22): replace EARLIER/EARLIEST with a VAR.

§22: ``EARLIER``/``EARLIEST`` are the legacy pre-VAR way to reach an outer row
context — they read as a puzzle and break when another row-context level is
added. Capture the outer value in a ``VAR`` instead (§2 already mandates
VAR/RETURN structure).

Detection is a masked-text scan for an ``EARLIER(`` / ``EARLIEST(`` call, over
every DAX-bearing object: measures, calculated columns (where EARLIER most
often lives), calculated tables, and calculation items. Identifier contents
are blanked first so a column named ``[Earlier]`` can never fire; one finding
per occurrence, at the call's line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import blank_identifiers, dax_targets, line_at

_EARLIER_RE = re.compile(r"\b(EARLIER|EARLIEST)\s*\(", re.IGNORECASE)


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = blank_identifiers(mask_dax(target.dax))
        for match in _EARLIER_RE.finditer(text):
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, match.start()),
                    message=(
                        f"uses {match.group(1).upper()}() — the legacy pre-VAR idiom; capture the "
                        "outer row's value in a VAR before entering the inner row context (§22)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-EARLIER-TO-VAR",
    title="Replace EARLIER/EARLIEST with a VAR",
    severity="warning",
    category="structure",
    standard_ref="§22",
    tier=2,
    check=check,
)
