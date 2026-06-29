"""DAX-MEASURE-IN-ITERATOR (§9): measure references inside row iterators.

§9: a measure reference inside a row iterator (SUMX, AVERAGEX, FILTER, ...) is
wrapped in an implicit CALCULATE — a hidden context transition — so it is worth
surfacing for review. We walk each iterator call via ``iter_calls`` and, within
its argument text, flag every *bare* ``[Name]`` (``ref.table == ""``) whose
normalized name is a known measure. A column-only iterator (``SUMX(Sales,
Sales[Qty] * Sales[Price])``) never fires because those refs are qualified.

This is the deterministic *detector*; a separate agent rule judges whether the
transition is actually a problem, so here we only locate the construct.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import bracket_refs
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import ITERATOR_FUNCS, iter_calls, line_at, masked


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    measures = ctx.catalog.measure_names
    columns = ctx.catalog.column_names
    for measure in ctx.catalog.measures:
        text = masked(measure)
        # Each iterator's (func_name, argument span) in the full masked text.
        # arg_span end = args_start + len(args_text).
        iterators: list[tuple[str, int, int]] = []
        for func, name_offset, args_text in iter_calls(text, ITERATOR_FUNCS):
            args_start = text.index("(", name_offset) + 1
            iterators.append((func, args_start, args_start + len(args_text)))

        seen: set[int] = set()  # absolute ref offsets already flagged (nested iterators)
        for ref in bracket_refs(text):
            if ref.table:
                continue  # Table[Col] — a column, not a measure
            if normalize(ref.name) not in measures:
                continue
            if normalize(ref.name) in columns:
                continue  # name also a column — DAX resolves the bare ref to the column
            if ref.offset in seen:
                continue
            # Attribute the ref to the innermost enclosing iterator — the one
            # whose argument span most tightly contains it — so a nested
            # SUMX(..., AVERAGEX(..., [M])) names AVERAGEX, not SUMX.
            enclosing = [(end - start, func) for func, start, end in iterators if start <= ref.offset < end]
            if not enclosing:
                continue  # not inside any iterator
            seen.add(ref.offset)
            _func = min(enclosing)[1]
            findings.append(
                ctx.finding(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=line_at(measure, ref.offset),
                    message=(
                        f"measure '[{ref.name}]' is referenced inside iterator "
                        f"{_func} — each row triggers an implicit CALCULATE "
                        f"(context transition); confirm this is intended (§9)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-MEASURE-IN-ITERATOR",
    title="Measure reference inside a row iterator (context transition)",
    severity="info",
    category="context-transition",
    standard_ref="§9",
    tier=2,
    check=check,
)
