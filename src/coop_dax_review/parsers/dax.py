"""DAX text utilities: comment/string stripping and reference extraction.

Lifted from coop-data-doc's ``dax.py`` and kept position-preserving so a rule
that scans the masked text can map a match offset straight back to a line.
Every text rule masks first (``mask_dax``) so a keyword inside a comment or a
string literal can never trigger a finding.

Reference extraction distinguishes ``Table[Column]`` (a column ref) from a
bare ``[Name]`` (a measure ref *or* a same-table column ref) the same way the
DAX engine does — by whether an identifier/quote immediately precedes the
``[``. Resolving a bare ``[Name]`` to measure-vs-column needs the catalog and
is done by the rules, not here.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

# A single combined scanner: a string literal, a block comment, or a line
# comment — whichever starts first wins. Masking must be one left-to-right
# pass: if comments were stripped before strings, a `//`/`--`/`/*` *inside* a
# string literal (think image/SVG URLs, e.g. "http://...") would be treated as
# a real comment and blank out the rest of the line — silently hiding real
# refs after it. Putting the string alternative first guarantees a quoted run
# is consumed as a unit before any comment marker inside it can match (and vice
# versa for a `"` inside a block comment).
#
# DAX has no backslash escapes (backslash is a literal char); a double-quote
# inside a string is escaped by doubling it (""). Matching with a C-style
# `\\.` escape would mis-handle a string ending in a backslash (e.g. "C:\")
# and leave its contents — and everything after — unmasked.
#
# The closing `"` and `*/` are OPTIONAL so an UNTERMINATED trailing string or
# block comment (no matching close before end-of-text) is masked to EOF rather
# than left visible — otherwise its content leaks into the text rules AND the
# structural syntax checker would double-count parens/brackets living inside the
# unterminated run. (The block-comment alt `\*(?!/)` steps over a lone `*` so a
# `*/` still closes the shortest comment; the trailing `(?:\*/)?` catches the
# unterminated case.)
_MASK_RE = re.compile(r'"(?:[^"]|"")*"?|/\*(?:[^*]|\*(?!/))*(?:\*/)?|(?://|--)[^\n]*', re.S)
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
# A single-quoted table identifier, tolerating the `''` escape for a literal
# apostrophe (`'O''Brien'`). Its content is NOT blanked by mask_dax (only strings
# and comments are), so it is intact here — used both to anchor a Table[Column]
# qualifier and to skip a phantom `[...]` that lives inside a quoted name.
_QUOTED_IDENT_RE = re.compile(r"'(?:[^'\n]|'')*'")
# Table[Column]: a quoted 'Table Name'[Col] or a bare TableName[Col]. In both,
# group 2 is the column, so the *reference* bracket is at ``match.start(2) - 1``
# — never re-scanned with ``index`` (which would find a `[` INSIDE a quoted name
# like `'Weird[Name]'[Col]` and mis-anchor the qualifier).
_QUOTED_TABLE_RE = re.compile(r"'((?:[^'\n]|'')*)'[ \t]*\[([^\[\]]+)\]")
_BARE_TABLE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*\[([^\[\]]+)\]")

# DAX keywords/operators that can legally sit immediately before a `[` (e.g.
# ``RETURN [Measure]``, ``x IN [Region]``, ``NOT [Flag]``). A real table name is
# never one of these, so a bare-table match whose identifier is one of these
# keywords is a keyword-then-bracket-ref, not a ``Table[Column]`` qualifier.
_DAX_KEYWORDS = frozenset(
    {
        "var",
        "return",
        "in",
        "not",
        "and",
        "or",
        "if",
        "then",
        "else",
        "true",
        "false",
        "evaluate",
        "define",
        "measure",
        "column",
        "table",
        "order",
        "by",
        "start",
        "at",
        "asc",
        "desc",
    }
)


def _blank_runs(text: str, pattern: re.Pattern) -> str:
    """Replace each match with same-length whitespace, preserving newlines so
    every character offset (and thus every line number) is unchanged."""

    def repl(match: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return pattern.sub(repl, text)


@functools.lru_cache(maxsize=None)
def mask_dax(dax: str) -> str:
    """A copy of ``dax`` with comment and string-literal *content* blanked to
    spaces but every offset and newline preserved. Scan this, not the raw DAX.

    Cached (pure function of a ``str``): ~13 rules re-mask the same measure body
    each run, so memoizing collapses that to one regex pass per distinct DAX.
    ``maxsize=None`` is safe for the short-lived CLI process (bounded by the
    model's distinct expression count); the cache never changes the output, so
    determinism is unaffected."""
    return _blank_runs(dax, _MASK_RE)


@dataclass(frozen=True)
class BracketRef:
    """One ``[...]`` reference found in DAX, with its position and shape.

    ``table`` is the qualifying table name when the reference was written as
    ``Table[name]`` (so it is unambiguously a column); empty for a bare
    ``[name]`` (a measure ref, or a same-table column ref — the catalog
    decides which).
    """

    name: str  # text inside the brackets
    table: str  # qualifying table, or "" for a bare [name]
    offset: int  # offset of the opening '[' in the masked/raw text (they align)


def bracket_refs(masked: str) -> list[BracketRef]:
    """Every ``[...]`` reference in already-masked DAX, in source order.

    A reference is qualified (``table`` set) when a table name immediately
    precedes the ``[`` — ``Table[Column]`` or ``'Table Name'[Column]`` — which
    is the DAX form for a column. Otherwise it is bare (a measure ref, or a
    same-table column ref).
    """
    # Offset of each '[' that is qualified by a table -> the table name.
    qualified: dict[int, str] = {}
    for pat in (_QUOTED_TABLE_RE, _BARE_TABLE_RE):
        for match in pat.finditer(masked):
            # A quoted name unescapes `''` -> `'` so it matches the catalog's
            # stored table name ('O''Brien' in DAX is the table O'Brien).
            table = match.group(1).replace("''", "'").strip()
            # A DAX keyword (RETURN/VAR/IN/NOT/...) immediately before a `[` is
            # an operator preceding a bracket ref, not a `Table[Column]`
            # qualifier — a real table name is never a reserved keyword.
            if pat is _BARE_TABLE_RE and table.lower() in _DAX_KEYWORDS:
                continue
            # The reference bracket is group 2's `[` (the char before the column
            # content), NOT the first `[` at/after match.start() — which for
            # `'Weird[Name]'[Col]` would be the bracket inside the quoted name.
            open_idx = match.start(2) - 1
            qualified.setdefault(open_idx, table)

    # Brackets that sit INSIDE a single-quoted table name ('Weird[Name]') are part
    # of the name, not references — skip them so they don't surface as phantom
    # bare refs. (The qualifier's own [Col] bracket lives outside the quotes.)
    quoted_spans = [(m.start(), m.end()) for m in _QUOTED_IDENT_RE.finditer(masked)]

    def _inside_quoted(pos: int) -> bool:
        return any(start <= pos < end for start, end in quoted_spans)

    refs: list[BracketRef] = []
    for match in _BRACKET_RE.finditer(masked):
        if _inside_quoted(match.start()):
            continue
        refs.append(
            BracketRef(
                name=match.group(1).strip(),
                table=qualified.get(match.start(), ""),
                offset=match.start(),
            )
        )
    return refs
