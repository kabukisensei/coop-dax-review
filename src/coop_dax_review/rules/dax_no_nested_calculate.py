"""DAX-NO-NESTED-CALCULATE (§3): never nest CALCULATE inside CALCULATE.

§3 says a ``CALCULATE`` directly inside another ``CALCULATE`` should be broken
apart with ``VAR``. We scan the comment/string-masked DAX, match parentheses,
and flag any ``CALCULATE(`` opened while another ``CALCULATE(`` is still open
on the paren stack. CALCULATETABLE counts too (same context-transition trap).
The finding points at the inner ``CALCULATE``'s line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import line_at, masked

_CALC_RE = re.compile(r"\bCALCULATE(?:TABLE)?\b", re.IGNORECASE)


def _nested_offsets(text: str) -> list[int]:
    """Offsets of every ``CALCULATE`` whose paren opens inside another open
    CALCULATE's parens."""
    # Map each '(' that immediately follows a CALCULATE keyword to its offset.
    calc_paren: dict[int, int] = {}
    for match in _CALC_RE.finditer(text):
        rest = text[match.end() :]
        stripped = rest.lstrip()
        if stripped.startswith("("):
            paren_idx = match.end() + (len(rest) - len(stripped))
            calc_paren[paren_idx] = match.start()

    nested: list[int] = []
    stack: list[bool] = []  # True when the open paren belongs to a CALCULATE
    open_calcs = 0
    for idx, char in enumerate(text):
        if char == "(":
            is_calc = idx in calc_paren
            if is_calc and open_calcs > 0:
                nested.append(calc_paren[idx])
            stack.append(is_calc)
            open_calcs += is_calc
        elif char == ")" and stack:
            open_calcs -= stack.pop()
    return nested


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        for offset in _nested_offsets(text):
            findings.append(
                ctx.finding(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=line_at(measure, offset),
                    message="nested CALCULATE — break the inner CALCULATE out into a VAR (§3).",
                )
            )
    return findings


RULE = Rule(
    id="DAX-NO-NESTED-CALCULATE",
    title="No CALCULATE nested inside another CALCULATE",
    severity="warning",
    category="calculate",
    standard_ref="§3",
    tier=1,
    check=check,
)
