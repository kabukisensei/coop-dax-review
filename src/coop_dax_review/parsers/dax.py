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
_MASK_RE = re.compile(r'"(?:[^"]|"")*"|/\*.*?\*/|(?://|--)[^\n]*', re.S)
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
# Table[Column]: a quoted 'Table Name'[Col] or a bare TableName[Col].
_QUOTED_TABLE_RE = re.compile(r"'([^']+)'\s*\[([^\[\]]+)\]")
_BARE_TABLE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\[([^\[\]]+)\]")


def _blank_runs(text: str, pattern: re.Pattern) -> str:
    """Replace each match with same-length whitespace, preserving newlines so
    every character offset (and thus every line number) is unchanged."""

    def repl(match: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return pattern.sub(repl, text)


def mask_dax(dax: str) -> str:
    """A copy of ``dax`` with comment and string-literal *content* blanked to
    spaces but every offset and newline preserved. Scan this, not the raw DAX."""
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
            open_idx = masked.index("[", match.start())
            qualified.setdefault(open_idx, match.group(1).strip())

    refs: list[BracketRef] = []
    for match in _BRACKET_RE.finditer(masked):
        refs.append(
            BracketRef(
                name=match.group(1).strip(),
                table=qualified.get(match.start(), ""),
                offset=match.start(),
            )
        )
    return refs
