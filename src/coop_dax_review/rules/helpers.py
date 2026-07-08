"""Shared helpers for rule modules.

Not a rule module (the name doesn't start with ``dax_``), so the registry
skips it. Rules import from here for the cross-cutting needs: masking DAX
before text scans and mapping a match offset back to a file line.
"""

from __future__ import annotations

import functools
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from coop_dax_review.model import Measure, ModelCatalog, normalize
from coop_dax_review.parsers.dax import mask_dax


@dataclass(frozen=True)
class DaxTarget:
    """A DAX-bearing object a text rule can scan uniformly: a measure, and
    (opt-in) a calculated column or calculated table. ``dax``/``dax_line``/
    ``line`` mirror the fields :func:`masked` and :func:`line_at` read, so both
    work on a target unchanged; ``object`` is the finding label."""

    object: str  # "[Measure]" · "Table[Column]" · "Table"
    dax: str
    file: str
    line: int
    dax_line: int


def dax_targets(
    catalog: ModelCatalog,
    *,
    calc_columns: bool = False,
    calc_tables: bool = False,
    calc_items: bool = False,
) -> Iterator[DaxTarget]:
    """Yield the model's DAX-bearing objects for a text rule to scan.

    Measures are always yielded first and IDENTICALLY to a plain
    ``catalog.measures`` loop (same object label / dax / line), so a rule that
    switches to this helper produces byte-identical measure findings — no
    baseline churn. Calculated columns / tables and calculation-group items are
    opt-in per rule (issues #5 / #8): only rules whose §-semantics clearly
    transfer (``DAX-USE-DIVIDE`` §14, ``DAX-NO-NESTED-CALCULATE`` §3) enable them
    today. Others stay measure-only — e.g. row-context / iterator rules, where a
    calculated column's row context is normal, not a smell — until the standards
    address calc-column / calc-item DAX explicitly.
    """
    for m in catalog.measures:
        yield DaxTarget(f"[{m.name}]", m.dax, m.file, m.line, m.dax_line or m.line)
    if calc_columns:
        for table in catalog.tables:
            for column in table.columns:
                if column.is_calculated and column.expression.strip():
                    yield DaxTarget(
                        f"{table.name}[{column.name}]",
                        column.expression,
                        table.file,
                        column.line,
                        column.line,
                    )
    if calc_tables:
        for table in catalog.tables:
            if table.is_calculated and table.expression.strip():
                yield DaxTarget(
                    table.name, table.expression, table.file, table.line, table.dax_line or table.line
                )
    if calc_items:
        for item in catalog.calculation_items:
            if item.dax.strip():
                yield DaxTarget(
                    f"{item.table}[{item.name}]", item.dax, item.file, item.line, item.dax_line or item.line
                )


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
        "percentilex.exc",
        "percentilex.inc",
        "stdevx.p",
        "stdevx.s",
        "varx.p",
        "varx.s",
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
# A string literal, a block comment, or a line comment — whichever starts
# first (single left-to-right pass over ALL three token kinds, mirroring
# dax._MASK_RE) — used to blank ONLY string literals while leaving real
# comments intact, so a ``/* ... */`` substring inside a quoted string is not
# mistaken for a documentation header. The line-comment alternative matters
# even though line comments pass through untouched: consuming a ``//`` / ``--``
# run as a unit stops an unpaired ``"`` inside it (an inch mark like ``5/8"``)
# from starting a phantom string that would swallow a following real header.
_STRING_OR_COMMENT_RE = re.compile(r'"(?:[^"]|"")*"|/\*.*?\*/|(?://|--)[^\n]*', re.S)


def _blank_string_literals(dax: str) -> str:
    """``dax`` with string-literal *content* blanked (length-preserving) but
    comments — ``/* ... */`` blocks AND ``//`` / ``--`` line comments — kept.
    A comment encountered first is consumed as a unit and left untouched, so a
    ``"`` inside it cannot start a phantom string run."""

    def repl(match: re.Match) -> str:
        run = match.group(0)
        if not run.startswith('"'):
            return run  # keep real comments (block and line) intact
        return "".join("\n" if ch == "\n" else " " for ch in run)

    return _STRING_OR_COMMENT_RE.sub(repl, dax)


@functools.lru_cache(maxsize=None)
def blank_brackets(text: str) -> str:
    """Blank ``[...]`` reference contents (length-preserving) so an identifier
    named ``[VAR]`` / ``[Net/Gross]`` can't masquerade as a keyword or operator.
    Offsets and newlines are preserved, so a scanner's hits still map to lines.
    Cached (pure) — several rules re-blank the same masked body each run (#9)."""
    return _BRACKET_CONTENT_RE.sub(lambda m: " " * len(m.group(0)), text)


# A single-quoted table identifier ('Sales (2024)', 'Plan/Actuals'). Applied
# AFTER mask_dax, so an apostrophe inside a string literal or comment is
# already blanked and can't start a phantom run; newlines are excluded from
# the class because an identifier never spans lines (a stray apostrophe must
# not blank across lines and corrupt offset->line mapping).
_QUOTED_IDENT_RE = re.compile(r"'(?:[^'\n]|'')*'")


@functools.lru_cache(maxsize=None)
def blank_quoted_identifiers(text: str) -> str:
    """Blank single-quoted table-identifier contents (length-preserving) so a
    ``/`` or ``(`` inside a table name like ``'Plan/Actuals'`` or
    ``'Sales (2024)'`` can't masquerade as an operator or a function call.
    Cached (pure) — re-blanked by several rules on the same body each run (#9)."""
    return _QUOTED_IDENT_RE.sub(lambda m: " " * len(m.group(0)), text)


@functools.lru_cache(maxsize=None)
def blank_identifiers(masked_dax: str) -> str:
    """Blank both identifier forms — ``[...]`` refs, then single-quoted table
    names — before scanning for operators, keywords or parens. Bracket contents
    go first so an apostrophe inside a name like ``[O'Brien]`` can't open a
    phantom quoted run. Length/newline-preserving, like both primitives.
    Cached (pure) — the hot path for the ~13 text rules (#9)."""
    return blank_quoted_identifiers(blank_brackets(masked_dax))


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


def split_top_commas(text: str) -> list[str]:
    """Split ``text`` on top-level (depth-0) commas, respecting parens/brackets.

    The argument-list splitter for an already-extracted call span (see
    :func:`arg_span`): a comma inside a nested call or a bracket ref never
    splits.
    """
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


def iter_calls(masked_dax: str, names: frozenset[str]) -> Iterator[tuple[str, int, str]]:
    """Yield ``(func_name, name_offset, args_text)`` for every call in
    ``masked_dax`` whose (lower-cased) function name is in ``names``."""
    for match in _CALL_RE.finditer(masked_dax):
        if match.group(1).lower() in names:
            yield match.group(1), match.start(), arg_span(masked_dax, match.end() - 1)


def count_vars(masked_dax: str) -> int:
    """Number of ``VAR`` keywords in already-masked DAX (identifiers ignored)."""
    return len(_VAR_RE.findall(blank_identifiers(masked_dax)))


def has_var_return(masked_dax: str) -> bool:
    """True if the DAX uses a ``VAR`` ... ``RETURN`` structure.

    Identifier contents (bracket refs AND quoted table names) are blanked
    first so a column named ``[VAR]`` or a table named ``'Var Data'`` does
    not look like a VAR/RETURN keyword.
    """
    text = blank_identifiers(masked_dax)
    return bool(_VAR_RE.search(text) and _RETURN_RE.search(text))


def has_block_comment(dax: str) -> bool:
    """True if the DAX contains a ``/* ... */`` header block.

    String-literal content is blanked first (comments kept) so a ``/* ... */``
    substring living inside a quoted string is not mistaken for a real header.
    Run on the raw DAX (not ``mask_dax`` output, which would blank a real
    header along with the strings)."""
    return bool(_BLOCK_COMMENT_RE.search(_blank_string_literals(dax)))


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
