"""DAX-FILTER-TABLE-IN-CALCULATE (§4): filter columns, not whole tables.

§4: prefer a plain boolean column filter in ``CALCULATE`` over wrapping a whole
table in ``FILTER``. ``FILTER(DimCustomer, DimCustomer[Seg] = "X")`` materialises
the entire table and is slower than the equivalent ``DimCustomer[Seg] = "X"``.

We only flag the *exact* avoidable shape and nothing else (precision over
recall): a ``FILTER`` inside a ``CALCULATE`` whose first argument is EXACTLY a
bare table reference and whose predicate is a single simple comparison over that
same table's columns. ``FILTER(ALL(...))`` / ``FILTER(VALUES(...))`` / a filter
over an expression, a multi-table predicate, a logical ``&&``/``||`` predicate,
or a predicate referencing a measure are all legitimate and left alone.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import bracket_refs
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import arg_span, iter_calls, line_at, masked

_CALC_RE = re.compile(r"\bCALCULATE(?:TABLE)?\b\s*\(", re.IGNORECASE)
_FILTER = frozenset({"filter"})
# A bare (optionally single-quoted) table token and nothing else.
_BARE_TABLE_RE = re.compile(r"^(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))$")
_COMPARISON_RE = re.compile(r"<=|>=|<>|=|<|>")
_CALL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\s*\(")


def _split_top_comma(text: str) -> list[str]:
    """Split ``text`` on top-level (depth-0) commas, respecting parens/brackets."""
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    parts.append(text[start:])
    return parts


def _simple_table_predicate(predicate: str, table: str, ctx: RuleContext) -> bool:
    """True if ``predicate`` is a single simple comparison referencing only
    ``table``'s columns (no measures, no logical operators, no function calls)."""
    if "&&" in predicate or "||" in predicate:
        return False
    if _CALL_RE.search(predicate):  # FILTER over a function-laden predicate is fine
        return False
    ops = list(_COMPARISON_RE.finditer(predicate))
    if len(ops) != 1:
        return False
    cols = ctx.catalog.columns_by_table.get(table, set())
    refs = bracket_refs(predicate)
    if not refs:
        return False
    for ref in refs:
        if ref.table == "":
            return False  # bare [Name]: a measure ref or same-table col — leave alone
        if normalize(ref.table) != table:
            return False  # references another table
        if normalize(ref.name) not in cols:
            return False  # column not on this table
    # Column-vs-constant only. A column-vs-column comparison (a qualified ref on
    # BOTH sides of the operator, e.g. T[SalePrice] < T[ListPrice]) has no plain
    # boolean-column-filter equivalent, so that FILTER is legitimate — skip it.
    op = ops[0]
    if bracket_refs(predicate[: op.start()]) and bracket_refs(predicate[op.end() :]):
        return False
    return True


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for measure in ctx.catalog.measures:
        text = masked(measure)
        for calc in _CALC_RE.finditer(text):
            args = arg_span(text, calc.end() - 1)
            base = calc.end() - 1  # offset of the CALCULATE '(' within `text`
            for _name, off, fargs in iter_calls(args, _FILTER):
                parts = _split_top_comma(fargs)
                if len(parts) < 2:
                    continue
                first = parts[0].strip()
                m = _BARE_TABLE_RE.match(first)
                if not m:
                    continue  # not a bare table (e.g. ALL(...)/VALUES(...)/expr)
                token = m.group(1) or m.group(2)
                table = normalize(token)
                if table not in ctx.catalog.table_names:
                    continue
                predicate = ",".join(parts[1:])
                if not _simple_table_predicate(predicate, table, ctx):
                    continue
                filter_offset = base + 1 + off
                findings.append(
                    ctx.finding(
                        object=f"[{measure.name}]",
                        file=measure.file,
                        line=line_at(measure, filter_offset),
                        message=(
                            f"FILTER over whole table '{token}' in CALCULATE — a plain column "
                            f"filter ({token}[...] = ...) is simpler and faster (§4)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="DAX-FILTER-TABLE-IN-CALCULATE",
    title="Filter columns, not whole tables, in CALCULATE",
    severity="warning",
    category="filters",
    standard_ref="§4",
    tier=2,
    check=check,
)
