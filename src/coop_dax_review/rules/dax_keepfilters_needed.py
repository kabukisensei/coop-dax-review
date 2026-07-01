"""DAX-KEEPFILTERS-NEEDED (§5): a CALCULATE boolean filter may need KEEPFILTERS.

§5: use ``KEEPFILTERS`` when an outer filter's shape must be preserved. Whether
it is *required* depends on the intended filter behaviour, which a linter
cannot decide — so this is an agent-judgment rule. The tool detects the
construct it applies to: a ``CALCULATE``/``CALCULATETABLE`` carrying a boolean
*column* predicate (``Table[Col] = ...``) as a filter argument that is not
wrapped in ``KEEPFILTERS(...)``, and hands each such call to the agent.

Detection is scoped **per top-level filter argument** of a single CALCULATE
(balanced-paren scan + depth-0 comma split), so (a) an unrelated comparison
elsewhere in the measure does not trigger it, (b) a KEEPFILTERS on one
argument — or one sibling CALCULATE — does not suppress a bare predicate next
to it, and (c) a comparison living *inside* a nested call (``FILTER``/``ALL``/
``MAX``...) is not mistaken for the boolean shorthand, where KEEPFILTERS
semantics don't apply. The predicate must be a *qualified* column
(``Table[Col]`` or ``'Table'[Col]``) — DAX boolean CALCULATE filters are
columns, not bare measure comparisons.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import arg_span, line_at, masked, split_top_commas

_CALC_RE = re.compile(r"\bCALCULATE(?:TABLE)?\b\s*\(", re.IGNORECASE)
# A boolean predicate on a qualified column: Table[Col] or 'Table Name'[Col]
# followed by a comparison operator (multi-char operators tried first).
_BOOL_FILTER_RE = re.compile(r"(?:'[^']+'|\w+)\s*\[[^\]]+\]\s*(?:<=|>=|<>|=|<|>)")
_WS_RE = re.compile(r"\s+")


def _blank_nested_parens(text: str) -> str:
    """``text`` with everything inside parens blanked (length-preserving), so a
    scan sees only the depth-0 shape of one argument. A ``(`` inside a bracket
    ref (``[Net (USD)]``) or a quoted table name (``'Sales (2024)'``) is
    identifier content, not a call, and never changes the depth."""
    out: list[str] = []
    depth = 0
    ident = ""  # "'" inside a quoted table name, "[" inside a bracket ref
    for ch in text:
        keep = depth == 0
        if ident:
            out.append(ch if keep else " ")
            if (ident == "'" and ch == "'") or (ident == "[" and ch == "]"):
                ident = ""
        elif ch in "'[":
            ident = ch
            out.append(ch if keep else " ")
        elif ch == "(":
            depth += 1
            out.append("(")
        elif ch == ")":
            depth = max(0, depth - 1)
            out.append(")")
        else:
            out.append(ch if keep else " ")
    return "".join(out)


def _bare_predicates(args: str) -> list[str]:
    """The top-level filter arguments of one CALCULATE arg span that are bare
    boolean column predicates (not wrapped in KEEPFILTERS or any other call).
    The first argument is the evaluated expression, never a filter."""
    out: list[str] = []
    for arg in split_top_commas(args)[1:]:
        if _BOOL_FILTER_RE.search(_blank_nested_parens(arg)):
            out.append(_WS_RE.sub(" ", arg.strip()))
    return out


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        for match in _CALC_RE.finditer(text):
            predicates = _bare_predicates(arg_span(text, match.end() - 1))
            if predicates:
                shown = "; ".join(p if len(p) <= 60 else p[:57] + "..." for p in predicates)
                items.append(
                    ctx.review(
                        object=f"[{measure.name}]",
                        file=measure.file,
                        line=line_at(measure, match.start()),
                        note=(
                            f"CALCULATE applies a boolean column filter without KEEPFILTERS ({shown}) — "
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
