"""DAX-KEEPFILTERS-NEEDED (§5): a CALCULATE boolean filter may need KEEPFILTERS.

§5: use ``KEEPFILTERS`` when an outer filter's shape must be preserved. Whether
it is *required* depends on the intended filter behaviour, which a linter
cannot decide — so this is an agent-judgment rule. The tool detects the
construct it applies to: a ``CALCULATE``/``CALCULATETABLE`` carrying a boolean
*column* predicate (``Table[Col] = ...``) in its filter arguments where that
call does not already use ``KEEPFILTERS``, and hands each such call to the
agent.

Detection is scoped to a single CALCULATE's argument span (balanced-paren
scan) rather than the whole measure, so (a) an unrelated comparison elsewhere
in the measure does not trigger it, and (b) a KEEPFILTERS on one CALCULATE
does not suppress a sibling CALCULATE that lacks it. The predicate must be a
*qualified* column (``Table[Col]`` or ``'Table'[Col]``) — DAX boolean
CALCULATE filters are columns, not bare measure comparisons.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import arg_span, line_at, masked

_CALC_RE = re.compile(r"\bCALCULATE(?:TABLE)?\b\s*\(", re.IGNORECASE)
# A boolean predicate on a qualified column: Table[Col] or 'Table Name'[Col]
# followed by a comparison operator (multi-char operators tried first).
_BOOL_FILTER_RE = re.compile(r"(?:'[^']+'|\w+)\s*\[[^\]]+\]\s*(?:<=|>=|<>|=|<|>)")
_KEEPFILTERS_RE = re.compile(r"\bKEEPFILTERS\b", re.IGNORECASE)


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        for match in _CALC_RE.finditer(text):
            args = arg_span(text, match.end() - 1)
            if _BOOL_FILTER_RE.search(args) and not _KEEPFILTERS_RE.search(args):
                items.append(
                    ctx.review(
                        object=f"[{measure.name}]",
                        file=measure.file,
                        line=line_at(measure, match.start()),
                        note=(
                            "CALCULATE applies a boolean column filter without KEEPFILTERS — "
                            "judge whether the outer filter shape should be preserved (§5)."
                        ),
                    )
                )
    return items


RULE = Rule(
    id="DAX-KEEPFILTERS-NEEDED",
    title="CALCULATE boolean filter may need KEEPFILTERS",
    severity="info",
    category="filters",
    standard_ref="§5",
    tier=1,
    kind="agent",
    detect=detect,
)
