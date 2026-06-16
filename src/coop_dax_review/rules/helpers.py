"""Shared helpers for rule modules.

Not a rule module (the name doesn't start with ``dax_``), so the registry
skips it. Rules import from here for the cross-cutting needs: masking DAX
before text scans and mapping a match offset back to a file line.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator

from coop_dax_review.model import Measure, ModelCatalog, normalize
from coop_dax_review.parsers.dax import mask_dax

# Time-intelligence functions: their presence is what makes a marked Date
# table required (§8). Kept lowercase for case-insensitive membership tests.
TIME_INTEL_FUNCS = frozenset(
    {
        "datesytd",
        "datesmtd",
        "datesqtd",
        "totalytd",
        "totalmtd",
        "totalqtd",
        "sameperiodlastyear",
        "dateadd",
        "datesbetween",
        "datesinperiod",
        "parallelperiod",
        "previousyear",
        "previousmonth",
        "previousquarter",
        "previousday",
        "nextyear",
        "nextmonth",
        "nextquarter",
        "nextday",
        "openingbalancemonth",
        "openingbalancequarter",
        "openingbalanceyear",
        "closingbalancemonth",
        "closingbalancequarter",
        "closingbalanceyear",
        "firstdate",
        "lastdate",
        "startofyear",
        "startofmonth",
        "startofquarter",
        "endofyear",
        "endofmonth",
        "endofquarter",
    }
)

# Row-iterator functions whose body re-enters row context — a measure
# reference inside one triggers an implicit CALCULATE (context transition), §9.
ITERATOR_FUNCS = frozenset(
    {
        "sumx",
        "averagex",
        "minx",
        "maxx",
        "countx",
        "countax",
        "concatenatex",
        "rankx",
        "productx",
        "geomeanx",
        "medianx",
        "filter",
        "addcolumns",
        "selectcolumns",
        "generate",
        "generateall",
    }
)

# Numeric column data types (TMDL/TOM spelling) — these auto-aggregate by
# default, so they drive the key-summarizeBy and implicit-measure rules.
NUMERIC_TYPES = frozenset({"int64", "double", "decimal", "int", "integer"})

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A function call: an identifier (dotted names like PERCENTILEX.INC allowed)
# immediately followed by an opening paren.
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_VAR_RE = re.compile(r"\bVAR\b", re.IGNORECASE)
_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_BRACKET_CONTENT_RE = re.compile(r"\[[^\[\]]*\]")


def blank_brackets(text: str) -> str:
    """Blank ``[...]`` reference contents (length-preserving) so an identifier
    named ``[VAR]`` / ``[Net/Gross]`` can't masquerade as a keyword or operator.
    Offsets and newlines are preserved, so a scanner's hits still map to lines."""
    return _BRACKET_CONTENT_RE.sub(lambda m: " " * len(m.group(0)), text)


def masked(measure: Measure) -> str:
    """The measure's DAX with comments/strings blanked (offsets preserved)."""
    return mask_dax(measure.dax)


def arg_span(text: str, open_paren: int) -> str:
    """The text between the ``(`` at ``open_paren`` and its matching ``)``.

    ``open_paren`` is the index of an opening paren in ``text`` (typically
    already masked). On an unbalanced span the rest of the string is returned.
    """
    depth = 0
    for idx in range(open_paren, len(text)):
        if text[idx] == "(":
            depth += 1
        elif text[idx] == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : idx]
    return text[open_paren + 1 :]


def iter_calls(masked_dax: str, names: frozenset[str]) -> Iterator[tuple[str, int, str]]:
    """Yield ``(func_name, name_offset, args_text)`` for every call in
    ``masked_dax`` whose (lower-cased) function name is in ``names``."""
    for match in _CALL_RE.finditer(masked_dax):
        if match.group(1).lower() in names:
            yield match.group(1), match.start(), arg_span(masked_dax, match.end() - 1)


def count_vars(masked_dax: str) -> int:
    """Number of ``VAR`` keywords in already-masked DAX (bracket refs ignored)."""
    return len(_VAR_RE.findall(blank_brackets(masked_dax)))


def has_var_return(masked_dax: str) -> bool:
    """True if the DAX uses a ``VAR`` ... ``RETURN`` structure.

    Bracket-reference contents are blanked first so a column/measure named
    ``[VAR]`` or ``[Net RETURN]`` does not look like a VAR/RETURN keyword.
    """
    text = blank_brackets(masked_dax)
    return bool(_VAR_RE.search(text) and _RETURN_RE.search(text))


def has_block_comment(dax: str) -> bool:
    """True if the (raw, unmasked) DAX contains a ``/* ... */`` header block."""
    return bool(_BLOCK_COMMENT_RE.search(dax))


def snowflake_intermediates(catalog: ModelCatalog) -> list[str]:
    """Display names of tables that sit *between* other tables in the
    relationship graph — a dimension related to another dimension (§6).

    Edges run many-side -> one-side. A fact has only outgoing edges; a leaf
    dimension only incoming. A table with BOTH an incoming and an outgoing
    edge is an intermediate dimension — the snowflake chain link.
    """
    out_edges: dict[str, set[str]] = defaultdict(set)
    in_edges: dict[str, set[str]] = defaultdict(set)
    for rel in catalog.relationships:
        if not rel.is_active:
            continue  # inactive (role-playing/disabled) edges aren't structural snowflakes
        f, t = normalize(rel.from_table), normalize(rel.to_table)
        if f == t:
            continue  # self-relationship is not a snowflake chain
        out_edges[f].add(t)
        in_edges[t].add(f)
    return sorted(
        table.name
        for table in catalog.tables
        if in_edges.get(normalize(table.name)) and out_edges.get(normalize(table.name))
    )


def line_at(measure: Measure, offset: int) -> int:
    """The file line of a character ``offset`` within the measure's DAX.

    The DAX body's first character sits on ``measure.dax_line`` (which equals
    the declaration line for an inline measure, or the line below it when the
    body starts after ``measure X =``), so the file line is that base plus the
    number of newlines before ``offset``. The parser preserves interior blank
    lines in the stored DAX so this newline count matches the source.
    """
    base = measure.dax_line or measure.line
    return base + measure.dax[: max(0, offset)].count("\n")


def function_names(masked_dax: str) -> set[str]:
    """Lower-cased identifiers immediately followed by ``(`` — i.e. function
    calls — in already-masked DAX."""
    out: set[str] = set()
    for match in _WORD_RE.finditer(masked_dax):
        tail = masked_dax[match.end() :]
        if tail.lstrip().startswith("("):
            out.add(match.group(0).lower())
    return out
