"""TMDL semantic-model parsing into a :class:`ModelCatalog`.

TMDL is an indentation-scoped, line-oriented format. Like coop-data-doc's
parser this is a tolerant line scanner, not a grammar — it tracks table /
column / measure / partition / relationship headers and their property lines
and skips anything it doesn't recognize. Unlike coop-data-doc (which builds a
lineage graph) we keep every object's **1-based file line** so findings point
somewhere, and capture the linter-specific metadata: a relationship's
``crossFilteringBehavior`` and ``isActive`` (§7), a partition's storage
``mode`` (§13 Direct Lake), and a column's ``dataCategory`` / calculated-ness
(§8 marked Date table, §13).

A PBIP/TMDL model is a *folder* (``Foo.SemanticModel/definition/...``) with
one ``.tmdl`` file per table plus ``model.tmdl`` / ``relationships.tmdl``. We
group all the files of one model and merge them into a single catalog.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path, PurePosixPath

from coop_dax_review.diagnostics import PARSE_FAILED, Diagnostic
from coop_dax_review.model import CalculationItem, Column, Measure, ModelCatalog, Relationship, Table

# A table header line (plain or calculated). Name extraction is quote-aware
# below so an '=' inside a quoted name isn't mistaken for the calc separator.
# TMDL property/object keywords are NOT case-rigid — the Microsoft TMDL overview
# writes `datatype: int64` while Desktop exports write `dataType:` — so every
# keyword regex is matched case-insensitively (mainstream PBIP/Desktop exports
# serialize canonical camelCase and are unaffected; this only rescues hand-
# written / docs-derived / third-party-emitted TMDL). isHidden/summarizeBy/
# displayFolder/formatString already did this; the rest are brought in line here
# (issue #24) so a case-varied dataType/from-/toColumn/isActive/crossFilter is
# never silently dropped.
_TABLE_HEADER_RE = re.compile(r"^table\s+\S", re.IGNORECASE)
_TABLE_PLAIN_RE = re.compile(r"^table\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*$", re.IGNORECASE)
_CALC_TABLE_RE = re.compile(r"^table\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*=\s*(.*)$", re.IGNORECASE)
_MEASURE_RE = re.compile(r"^measure\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*=\s*(.*)$", re.IGNORECASE)
_CALC_ITEM_RE = re.compile(r"^calculationItem\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*=\s*(.*)$", re.IGNORECASE)
_COLUMN_RE = re.compile(r"^column\s+('[^']*'|\"[^\"]*\"|[^=\s]+)\s*(=\s*(.*))?$", re.IGNORECASE)
_DATATYPE_RE = re.compile(r"^dataType\s*:\s*(\S+)", re.IGNORECASE)
_DATACATEGORY_RE = re.compile(r"^dataCategory\s*:\s*(\S+)", re.IGNORECASE)
# TMDL serializes a true boolean as the BARE keyword (`isHidden` on its own
# line — what every real PBIP/Desktop export writes); the colon form
# (`isHidden: true|false`) appears only in hand-written TMDL. Accept both.
_ISHIDDEN_RE = re.compile(r"^isHidden(?:\s*:\s*(\S+))?\s*$", re.IGNORECASE)
_SUMMARIZEBY_RE = re.compile(r"^summarizeBy\s*:\s*(\S+)", re.IGNORECASE)
_DISPLAYFOLDER_RE = re.compile(r"^displayFolder\s*:\s*(.+?)\s*$", re.IGNORECASE)
_PARTITION_RE = re.compile(r"^partition\s+(.+?)\s*=\s*(\w+)\s*$", re.IGNORECASE)
_MODE_RE = re.compile(r"^mode\s*:\s*(\S+)", re.IGNORECASE)
# A partition's `source = <expr>` line. For a `calculated` partition the RHS is
# the calculated table's DAX (inline, a verbatim ``` block, or a multi-line
# body on the following deeper-indented lines) — the real-export form of a
# calculated table (issue #21). The other source types (`m`, `entity`, ...) put
# a query here too; we only keep the expression when the source is calculated.
_SOURCE_RE = re.compile(r"^source\s*=\s*(.*)$", re.IGNORECASE)
_RELATIONSHIP_RE = re.compile(r"^relationship\s+(\S+)", re.IGNORECASE)
_FROM_COLUMN_RE = re.compile(r"^fromColumn\s*:\s*(.+?)\s*$", re.IGNORECASE)
_TO_COLUMN_RE = re.compile(r"^toColumn\s*:\s*(.+?)\s*$", re.IGNORECASE)
_CROSSFILTER_RE = re.compile(r"^crossFilteringBehavior\s*:\s*(\S+)", re.IGNORECASE)
_ISACTIVE_RE = re.compile(r"^isActive\s*:\s*(\S+)", re.IGNORECASE)
_PROPERTY_RE = re.compile(r"^[A-Za-z][\w]*\s*:")
# Column/measure-scope booleans that real exports write bare (see _ISHIDDEN_RE).
# Like a `name: value` property line, a bare boolean ends a multi-line DAX body.
_BARE_BOOL_RE = re.compile(
    r"^(?:isHidden|isKey|isUnique|isNullable|isNameInferred|isDataTypeInferred"
    r"|isAvailableInMdx|isDefaultLabel|isDefaultImage|isSimpleMeasure)\s*$",
    re.IGNORECASE,
)
# Child objects of a `table` block (TOM Table children). Only one of THESE ends
# the current column's property run — a property-shaped line the scanner doesn't
# recognize (`lineageTag:`, `formatString:`, `sourceColumn:`, ...) must not,
# because real exports serialize recognized properties AFTER unrecognized ones
# (`summarizeBy:` comes after `lineageTag:`).
_CHILD_OBJECT_RE = re.compile(
    r"^(?:column|measure|partition|hierarchy|level|annotation|extendedProperty"
    r"|calculationGroup|calculationItem|variation|changedProperty|relatedColumnDetails|kpi)\b",
    re.IGNORECASE,
)
_FORMATSTRING_RE = re.compile(r"^formatString\s*:\s*(.+?)\s*$", re.IGNORECASE)
_FORMATSTRING_DEF_RE = re.compile(r"^formatStringDefinition\b", re.IGNORECASE)
# The finite set of real TMDL measure properties / child objects (per the TOM
# Measure object). The DAX-continuation loop must stop ONLY on one of these:
# treating ANY `Word:` line as a property truncates measure bodies at the
# standards' own §12 `/* Measure: ... Purpose: ... */` header lines, whose
# `Purpose:` etc. match the generic property shape but are comment text.
# Four shapes: `name: value` properties, BARE booleans (`isHidden` — the form
# real exports write; without it a bare isHidden after a measure body would be
# glued into the measure's DAX), `name = <expr>` children, and the named/bare
# child objects (`annotation X = ...`, `kpi`).
_MEASURE_PROP_RE = re.compile(
    r"^(?:"
    r"(?:formatString|displayFolder|lineageTag|sourceLineageTag|description"
    r"|isHidden|isSimpleMeasure|dataCategory|dataType|errorMessage|state)\s*:"
    r"|(?:isHidden|isSimpleMeasure)\s*$"
    r"|(?:formatStringDefinition|detailRowsDefinition|changedProperty)\s*="
    r"|(?:annotation|extendedProperty)\s+\S"
    r"|kpi\s*$"
    r")",
    re.IGNORECASE,
)
_DATE_TABLE_ANNOTATION = "__pbi_templatedatetable"


def _hidden_value(match: re.Match) -> bool:
    """Whether an ``_ISHIDDEN_RE`` match means hidden.

    The bare keyword form (``isHidden`` alone — what real exports write) means
    true; the colon form is read literally (``isHidden: true`` / ``false``).
    """
    value = match.group(1)
    return True if value is None else value.lower() == "true"


def _unquote(name: str) -> str:
    """Strip the surrounding quotes of a TMDL identifier and collapse the
    doubled-quote escape (``'O''Brien'`` -> ``O'Brien``)."""
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
        quote = name[0]
        return name[1:-1].replace(quote * 2, quote)
    return name


def _indent(line: str, tabsize: int = 4) -> int:
    """Indentation width, with tabs expanded so a tab outweighs a space.

    PBIP emits all-tab indentation, but hand-edited TMDL can mix tabs and
    spaces; expanding tabs keeps the depth comparison correct either way.
    """
    leading = line[: len(line) - len(line.lstrip(" \t"))]
    return len(leading.expandtabs(tabsize))


def _split_table_column(ref: str) -> tuple[str, str]:
    """Split a ``Table.Column`` endpoint on the dot that is OUTSIDE quotes.

    ``DimDate.Date`` -> ("DimDate", "Date"); ``DimDate.'Order Date'`` ->
    ("DimDate", "Order Date"); ``'Sales.Detail'.Amount`` ->
    ("Sales.Detail", "Amount") (the dot inside the quoted table name is not
    the separator).
    """
    ref = ref.strip()
    quote = ""
    for idx, ch in enumerate(ref):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == ".":
            return _unquote(ref[:idx]), _unquote(ref[idx + 1 :])
    return "", _unquote(ref)


def model_root(path: str) -> tuple[str, str]:
    """(root_prefix, model_name) for a TMDL file path.

    ``Sales.SemanticModel/definition/tables/x.tmdl`` -> root is the
    ``.SemanticModel`` folder, model name ``Sales``. A file outside a
    recognized PBIP layout falls back to its parent directory, so all loose
    ``.tmdl`` files in one folder form ONE model named after that folder
    (never one phantom model per file stem).
    """
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        if part.lower().endswith(".semanticmodel"):
            return "/".join(parts[: index + 1]), part[: -len(".SemanticModel")]
    if "definition" in parts:
        index = parts.index("definition")
        if index > 0:
            return "/".join(parts[:index]), parts[index - 1]
    parent = PurePosixPath(path).parent
    if parent.name:
        return parent.as_posix(), parent.name
    return "", PurePosixPath(path).stem


def _block_comment_open(line: str, open_before: bool) -> bool:
    """Whether a ``/* ... */`` block comment is still open after ``line``.

    Scans left to right honoring DAX lexing: a string literal can't start a
    comment, ``//`` / ``--`` line comments consume the rest of the line, and
    ``*/`` only closes an open block. Lets the measure scanner know that a
    ``Word:`` line inside a §12 header comment is comment text, not a property.
    """
    open_now = open_before
    i, n = 0, len(line)
    while i < n:
        if open_now:
            end = line.find("*/", i)
            if end == -1:
                return True
            open_now = False
            i = end + 2
        elif line[i] == '"':  # a string literal; `""` is the escaped quote
            j = i + 1
            while j < n:
                if line[j] == '"':
                    if line.startswith('""', j):
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
        elif line.startswith("//", i) or line.startswith("--", i):
            return False  # the rest of the line is a comment
        elif line.startswith("/*", i):
            open_now = True
            i += 2
        else:
            i += 1
    return open_now


def _skip_block(lines: list[str], start: int) -> int:
    """Index of the first line past the indented block starting at ``start``."""
    i = start + 1
    while i < len(lines):
        if lines[i].strip() and _indent(lines[i]) == 0:
            break
        i += 1
    return i


_VERBATIM_FENCE = "```"


def _is_verbatim_open(inline: str) -> bool:
    """Whether an inline expression is the OPENING of a TMDL verbatim block.

    TMDL's serializer emits ``measure X = `​`​``` (three backticks right
    after ``=``, nothing else on the line) whenever the expression has trailing
    whitespace or blank lines with whitespace; the body then follows verbatim.
    Only a bare fence opens a block — a real expression may legitimately contain
    a triple-backtick *inside* it, so require the stripped inline to be exactly
    the fence.
    """
    return inline.strip() == _VERBATIM_FENCE


def _consume_verbatim(lines: list[str], decl_index: int) -> tuple[str, int, int]:
    """Read a TMDL verbatim (triple-backtick) block.

    ``decl_index`` is the file index of the ``... = `​`​``` declaration
    line (whose inline part is the opening fence). Body lines are taken
    **verbatim** — indentation is ignored and property/child-object break rules
    do NOT apply, per the spec's "read verbatim including indentation" — until
    the line whose stripped content is exactly the closing fence. Returns
    ``(body, dax_line, next_index)`` where ``body`` is the fence-stripped
    expression, ``dax_line`` is the 1-based file line of the first body line (or
    the declaration line for an empty block), and ``next_index`` is the index of
    the line just past the closing fence (or end-of-input if the block is
    unterminated — a malformed block never runs off and swallows the rest).
    """
    body: list[str] = []
    dax_line = 0
    i = decl_index + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == _VERBATIM_FENCE:  # closing fence
            i += 1
            break
        if dax_line == 0:
            dax_line = i + 1
        body.append(line)
        i += 1
    # Trailing whitespace is exactly what verbatim blocks preserve, but the
    # stored DAX is scanned/reported line-oriented; keep interior content, drop
    # only the trailing empty lines that the closing fence's own line implied.
    text = "\n".join(body).rstrip("\n")
    return text, (dax_line or decl_index + 1), i


def _parse_table_block(lines: list[str], start: int, file: str) -> tuple[Table | None, int]:
    """Parse one ``table`` block beginning at ``lines[start]``; return the
    Table and the index of the first line past the block. A header with no
    extractable name (e.g. ``table =``) returns ``(None, end)`` — the caller
    reports a parse diagnostic for THIS file and the other blocks/files still
    parse (one bad header must never degrade the whole model)."""
    header = lines[start].strip()
    # Prefer the plain (or quoted) name; only treat it as a calculated table
    # when the name genuinely has a trailing ``= <DAX>`` (an '=' inside quotes
    # is not a separator — handled by the quote-aware alternatives).
    plain = _TABLE_PLAIN_RE.match(header)
    if plain:
        name, is_calc = _unquote(plain.group(1)), False
    else:
        calc = _CALC_TABLE_RE.match(header)
        if calc is None:
            return None, _skip_block(lines, start)
        name, is_calc = _unquote(calc.group(1)), True
    table = Table(name=name, file=file, line=start + 1, is_calculated=is_calc)

    i = start + 1
    # Retain a calculated table's DAX so rules can lint it (issue #5). The common
    # form is inline (`table X = <DAX>`); the multi-line form puts the body on the
    # indented lines above the (derived) column list — consume them so the
    # expression is kept AND the column loop resumes past them.
    if is_calc:
        inline_expr = calc.group(2).strip()
        if inline_expr:
            table.expression = inline_expr
            table.dax_line = start + 1
        else:
            dax_parts: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                inner = nxt.strip()
                if not inner:
                    if dax_parts:
                        break
                    i += 1
                    continue
                if _indent(nxt) == 0:
                    break
                if (
                    _COLUMN_RE.match(inner)
                    or _MEASURE_RE.match(inner)
                    or _PARTITION_RE.match(inner)
                    or _PROPERTY_RE.match(inner)
                    or _BARE_BOOL_RE.match(inner)
                    or inner.lower().startswith(("hierarchy ", "annotation ", "calculationgroup"))
                ):
                    break
                if table.dax_line == 0:
                    table.dax_line = i + 1
                dax_parts.append(inner)
                i += 1
            table.expression = "\n".join(dax_parts).strip()
    current_column: Column | None = None
    seen_child = False  # the first child object ends the table-property region
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue
        if _indent(raw) == 0:  # next top-level object
            break

        col = _COLUMN_RE.match(stripped)
        if col:
            seen_child = True
            col_indent = _indent(raw)
            inline_col = (col.group(3) or "").strip()
            current_column = Column(
                name=_unquote(col.group(1)),
                line=i + 1,
                is_calculated=bool(col.group(2)),
                expression=inline_col,
            )
            # A verbatim (triple-backtick) calculated-column body: the inline
            # part is just the opening fence, so read the following lines
            # verbatim and store the fence-stripped DAX. Without this, group(3)
            # captures '```' as a truthy inline expression and the whole body is
            # silently LOST (issue #25).
            if bool(col.group(2)) and _is_verbatim_open(inline_col):
                body, dax_line, i = _consume_verbatim(lines, i)
                current_column.expression = body.strip()
                current_column.dax_line = dax_line
                table.columns.append(current_column)
                continue
            if current_column.expression:
                current_column.dax_line = i + 1  # inline `column X = <DAX>`
            table.columns.append(current_column)
            i += 1
            # A calculated column whose DAX body spans the following indented
            # lines: consume them as the expression WITHOUT clearing the
            # current column, so a trailing dataType:/dataCategory: still binds.
            # `dax_line` records where the body's first line sits (issue #13 —
            # mirrors the measure parser) so findings/syntax errors inside a
            # multi-line body map to the right source line.
            if current_column.is_calculated and not current_column.expression:
                dax_parts: list[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    inner = nxt.strip()
                    if inner and (
                        _indent(nxt) <= col_indent or _PROPERTY_RE.match(inner) or _BARE_BOOL_RE.match(inner)
                    ):
                        break
                    if inner:
                        if current_column.dax_line == 0:
                            current_column.dax_line = i + 1
                        dax_parts.append(inner)
                    elif dax_parts:  # interior blank: keep for offset->line mapping
                        dax_parts.append("")
                    i += 1
                current_column.expression = "\n".join(dax_parts).strip()
            continue

        dt = _DATATYPE_RE.match(stripped)
        if dt and current_column is not None:
            current_column.data_type = dt.group(1)
            i += 1
            continue

        dc = _DATACATEGORY_RE.match(stripped)
        if dc:
            if current_column is not None:
                current_column.data_category = dc.group(1)
            if dc.group(1).lower() == "time":
                table.is_date_table = True
            i += 1
            continue

        ih = _ISHIDDEN_RE.match(stripped)
        if ih:
            # Column scope binds the current column; TABLE scope (the property
            # region before any child object) hides the whole table. Once a
            # child has been seen, an unbound isHidden belongs to a measure /
            # hierarchy / variation and is not the table's (measures re-parse
            # their own in _parse_measures).
            if current_column is not None:
                current_column.is_hidden = _hidden_value(ih)
            elif not seen_child:
                table.is_hidden = _hidden_value(ih)
            i += 1
            continue

        sb = _SUMMARIZEBY_RE.match(stripped)
        if sb and current_column is not None:
            current_column.summarize_by = sb.group(1)
            i += 1
            continue

        part = _PARTITION_RE.match(stripped)
        if part:
            seen_child = True
            current_column = None
            source_type = part.group(2)
            mode, source_expr, source_line, i = _consume_partition(lines, i, _indent(raw))
            if mode:
                table.storage_mode = mode
            # A `partition X = calculated` with a `source = <DAX>` body is the
            # real-export form of a calculated table (issue #21). The inline/
            # multi-line `table X = <DAX>` header form handled above does not
            # occur in exports; this branch is what Desktop / Tabular Editor /
            # pbi-tools actually serialize, so is_calculated + the DAX must be
            # captured here or every calc_tables=True rule silently skips it.
            if source_type.lower() == "calculated":
                table.is_calculated = True
                # Keep any expression already captured from the inline header form
                # (kept for back-compat); otherwise take the partition's source.
                if source_expr and not table.expression:
                    table.expression = source_expr
                    table.dax_line = source_line
            continue

        if stripped.lower().startswith("annotation ") and _DATE_TABLE_ANNOTATION in stripped.lower():
            table.is_date_table = True

        # A child `measure`/`calculationItem` with a VERBATIM (triple-backtick)
        # body: skip the block here so a body line dedented to column 0 (verbatim
        # is "read including indentation") is NOT mistaken for the next top-level
        # object and does not truncate the whole table (issue #25). The measure /
        # calc-item is re-parsed in full from the table slice by _parse_measures
        # / _parse_calculation_items; here we only need to step past it.
        header = _MEASURE_RE.match(stripped) or _CALC_ITEM_RE.match(stripped)
        if header and _is_verbatim_open(header.group(2)):
            seen_child = True
            current_column = None
            _, _, i = _consume_verbatim(lines, i)
            continue

        # Only a NEW CHILD OBJECT (measure/hierarchy/annotation/...) ends the
        # current column's property run. An unrecognized property-shaped line
        # (`lineageTag:`, `formatString:`, `sourceColumn:`, ...) or bare boolean
        # (`isKey`) must NOT reset the tracker: real exports serialize
        # `summarizeBy:` AFTER `lineageTag:`, so resetting there would leave
        # summarize_by (and anything else trailing) forever unbound.
        if _CHILD_OBJECT_RE.match(stripped):
            seen_child = True
            current_column = None
        i += 1
    return table, i


def _consume_partition(lines: list[str], start: int, header_indent: int) -> tuple[str, str, int, int]:
    """Read a partition block; return (storage_mode, source_expr, source_line, next_index).

    ``source_expr`` is the RHS of the partition's ``source = <expr>`` line — the
    calculated table's DAX for a ``calculated`` partition (issue #21) — captured
    inline, as a verbatim ``` block, or as a multi-line body on the following
    deeper-indented lines (mirroring the measure body-continuation rules, keeping
    interior blank lines for offset->line mapping). ``source_line`` is the 1-based
    line where the DAX body starts (the ``source =`` line for an inline value, or
    the first body line below it). Both are empty/0 when there is no ``source =``.
    """
    mode = ""
    source_expr = ""
    source_line = 0
    i = start + 1
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped and _indent(raw) <= header_indent:
            break
        m = _MODE_RE.match(stripped)
        if m:
            mode = m.group(1)
            i += 1
            continue
        src = _SOURCE_RE.match(stripped)
        if src:
            source_indent = _indent(raw)
            inline = src.group(1).strip()
            # A verbatim (triple-backtick) source body: the inline part is just
            # the opening fence; read the following lines verbatim and store the
            # fence-stripped DAX (mirrors the measure/calculated-column handling
            # of issue #25).
            if _is_verbatim_open(inline):
                source_expr, source_line, i = _consume_verbatim(lines, i)
                source_expr = source_expr.strip()
                continue
            if inline:  # inline `source = <DAX>`
                source_expr = inline
                source_line = i + 1
                i += 1
                continue
            # Multi-line `source =` body: the DAX is on the following lines
            # indented deeper than the `source` keyword, up to the next partition
            # property (`mode:`, ...) or the end of the partition block.
            i += 1
            dax_parts: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                inner = nxt.strip()
                if inner and (_indent(nxt) <= source_indent or _PROPERTY_RE.match(inner)):
                    break
                if inner:
                    if source_line == 0:
                        source_line = i + 1
                    dax_parts.append(inner)
                elif dax_parts:  # interior blank inside the body: keep for line mapping
                    dax_parts.append("")
                i += 1
            source_expr = "\n".join(dax_parts).strip()
            continue
        i += 1
    return mode, source_expr, (source_line or start + 1), i


def _parse_relationships(lines: list[str], file: str) -> list[Relationship]:
    """Collect every ``relationship`` block (in model.tmdl / relationships.tmdl)."""
    out: list[Relationship] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not (_RELATIONSHIP_RE.match(stripped) and _indent(raw) == 0):
            i += 1
            continue
        line_no = i + 1
        ft = fc = tt = tc = ""
        cross = "single"
        active = True
        i += 1
        while i < len(lines):
            inner_raw = lines[i]
            inner = inner_raw.strip()
            if inner and _indent(inner_raw) == 0:
                break
            if fm := _FROM_COLUMN_RE.match(inner):
                ft, fc = _split_table_column(fm.group(1))
            elif tm := _TO_COLUMN_RE.match(inner):
                tt, tc = _split_table_column(tm.group(1))
            elif cm := _CROSSFILTER_RE.match(inner):
                # Contract is "single" | "both"; normalize every non-both value
                # (oneDirection / automatic / ...) to "single", matching .bim.
                cross = "both" if cm.group(1).lower() == "bothdirections" else "single"
            elif am := _ISACTIVE_RE.match(inner):
                active = am.group(1).lower() != "false"
            i += 1
        if ft and tt:
            out.append(
                Relationship(
                    from_table=ft,
                    from_column=fc,
                    to_table=tt,
                    to_column=tc,
                    cross_filter=cross,
                    is_active=active,
                    file=file,
                    line=line_no,
                )
            )
    return out


def _doc_comment_above(lines: list[str], idx: int) -> str:
    """The TMDL `///` description block immediately above ``lines[idx]``.

    TMDL serializes an object's TOM description as one or more contiguous
    ``/// text`` lines directly above its declaration (a blank line would
    disassociate them). Returns the joined text (source order), or ``""``.
    """
    collected: list[str] = []
    j = idx - 1
    while j >= 0 and lines[j].strip().startswith("///"):
        collected.append(lines[j].strip()[3:].strip())
        j -= 1
    return " ".join(reversed(collected)).strip()


def _parse_measures(lines: list[str], file: str, table_name: str, line_offset: int = 0) -> list[Measure]:
    """Extract ``measure X = <DAX>`` blocks (with continuation lines).

    ``line_offset`` is the file index of ``lines[0]`` so reported lines are
    file-relative even when ``lines`` is a slice of one table block. ``dax_line``
    records where the DAX body actually starts (the declaration line for an
    inline measure, or the first body line below ``measure X =``), and interior
    blank lines are kept in the stored DAX so offset->line mapping matches the
    source.
    """
    out: list[Measure] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        m = _MEASURE_RE.match(stripped)
        if not m:
            i += 1
            continue
        indent = _indent(raw)
        name = _unquote(m.group(1))
        line_no = line_offset + i + 1
        description = _doc_comment_above(lines, i)
        inline = m.group(2)
        dax_parts: list[str] = []
        dax_line = 0
        in_comment = False
        # A verbatim (triple-backtick) measure body: the inline part is just the
        # opening fence. Read the following lines verbatim (ignoring indentation
        # and property-break rules) up to the closing fence, store the
        # fence-stripped DAX, then fall through to the property scan below with
        # `i` past the block (issue #25). Without this the fences are stored as
        # part of the measure's DAX and a dedented body line truncates it.
        if inline and _is_verbatim_open(inline):
            body, body_line, i = _consume_verbatim(lines, i)
            dax_parts = [body]
            dax_line = line_offset + body_line
        else:
            if inline:
                dax_parts.append(inline)
                dax_line = line_no
                in_comment = _block_comment_open(inline, False)
            i += 1
            while i < len(lines):
                nxt = lines[i]
                inner = nxt.strip()
                # DAX continues on lines indented deeper than the `measure`
                # keyword; a line at the same/shallower indent (the next measure/
                # column/partition) or a real measure property (the finite TMDL
                # set — `formatString:`, the `=`-introduced
                # `formatStringDefinition` block, ...) ends it. A line inside a
                # still-open `/* ... */` block is always body text: the §12
                # header's `Purpose:` lines look like properties but are comment
                # content.
                if (
                    inner
                    and not in_comment
                    and (
                        _indent(nxt) <= indent
                        or _MEASURE_PROP_RE.match(inner)
                        or _FORMATSTRING_DEF_RE.match(inner)
                    )
                ):
                    break
                if inner:
                    if dax_line == 0:
                        dax_line = line_offset + i + 1
                    dax_parts.append(inner)
                    in_comment = _block_comment_open(inner, in_comment)
                elif dax_parts:  # interior blank inside the body: keep for line mapping
                    dax_parts.append("")
                i += 1
        # The DAX loop stops at the measure's first property line; scan the
        # remaining property block (lines indented deeper than the measure) for
        # formatString / displayFolder. Stops at the next object (indent <= measure).
        format_string = ""
        display_folder = ""
        is_hidden = False
        while i < len(lines):
            nxt = lines[i]
            inner = nxt.strip()
            if inner and _indent(nxt) <= indent:
                break
            if inner:
                if not format_string and (fm := _FORMATSTRING_RE.match(inner)):
                    format_string = _unquote(fm.group(1).strip())
                elif not format_string and _FORMATSTRING_DEF_RE.match(inner):
                    format_string = "<dynamic>"  # formatStringDefinition: a dynamic format
                elif not display_folder and (df := _DISPLAYFOLDER_RE.match(inner)):
                    display_folder = _unquote(df.group(1).strip())
                elif (hm := _ISHIDDEN_RE.match(inner)) and _hidden_value(hm):
                    is_hidden = True
            i += 1
        out.append(
            Measure(
                name=name,
                dax="\n".join(dax_parts).strip(),
                table=table_name,
                file=file,
                line=line_no,
                dax_line=dax_line or line_no,
                format_string=format_string,
                display_folder=display_folder,
                is_hidden=is_hidden,
                description=description,
            )
        )
    return out


def _parse_calculation_items(
    lines: list[str], file: str, table_name: str, line_offset: int = 0
) -> list[CalculationItem]:
    """Extract ``calculationItem Name = <DAX>`` blocks from a calculation group's
    table slice (issue #8), mirroring the ``measure`` body-continuation rules.

    Kept separate from measures because their DAX is intricate (SELECTEDMEASURE
    transforms, time-intel wrappers) but their NAMES aren't measure names — so
    naming rules must never see them. A per-item ``formatStringDefinition`` (a
    dynamic format) is recorded as ``"<dynamic>"``.
    """
    out: list[CalculationItem] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        m = _CALC_ITEM_RE.match(raw.strip())
        if not m:
            i += 1
            continue
        indent = _indent(raw)
        name = _unquote(m.group(1))
        line_no = line_offset + i + 1
        inline = m.group(2)
        dax_parts: list[str] = []
        dax_line = 0
        in_comment = False
        # Verbatim (triple-backtick) calculationItem body — same handling as the
        # measure parser (issue #25).
        if inline and _is_verbatim_open(inline):
            body, body_line, i = _consume_verbatim(lines, i)
            dax_parts = [body]
            dax_line = line_offset + body_line
        else:
            if inline:
                dax_parts.append(inline)
                dax_line = line_no
                in_comment = _block_comment_open(inline, False)
            i += 1
            while i < len(lines):
                nxt = lines[i]
                inner = nxt.strip()
                if (
                    inner
                    and not in_comment
                    and (
                        _indent(nxt) <= indent
                        or _MEASURE_PROP_RE.match(inner)
                        or _FORMATSTRING_DEF_RE.match(inner)
                    )
                ):
                    break
                if inner:
                    if dax_line == 0:
                        dax_line = line_offset + i + 1
                    dax_parts.append(inner)
                    in_comment = _block_comment_open(inner, in_comment)
                elif dax_parts:
                    dax_parts.append("")
                i += 1
        format_string = ""
        while i < len(lines):
            nxt = lines[i]
            inner = nxt.strip()
            if inner and _indent(nxt) <= indent:
                break
            if inner and not format_string and _FORMATSTRING_DEF_RE.match(inner):
                format_string = "<dynamic>"
            i += 1
        out.append(
            CalculationItem(
                name=name,
                dax="\n".join(dax_parts).strip(),
                table=table_name,
                file=file,
                line=line_no,
                dax_line=dax_line or line_no,
                format_string=format_string,
            )
        )
    return out


def parse_tmdl_model(name: str, files: dict[str, str]) -> ModelCatalog:
    """Build a catalog from one model's ``{relative_path: text}`` TMDL files.

    ``model.tmdl`` / ``relationships.tmdl`` contribute relationships; every
    file is scanned for ``table`` and ``measure`` blocks (a measure can live
    in its table's file).
    """
    catalog = ModelCatalog(name=name)
    for path in sorted(files):
        text = files[path].replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        base = PurePosixPath(path).name.lower()
        if base in ("model.tmdl", "relationships.tmdl") and not catalog.file:
            catalog.file = path
        catalog.relationships.extend(_parse_relationships(lines, path))

        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()
            if _indent(raw) == 0 and _TABLE_HEADER_RE.match(stripped):
                table, end = _parse_table_block(lines, i, path)
                if table is None:  # unparseable header: skip THIS block, keep the rest
                    catalog.diagnostics.append(
                        Diagnostic(
                            severity="warning",
                            category=PARSE_FAILED,
                            file=path,
                            line=i + 1,
                            message=f"could not parse table header {stripped!r} - table skipped",
                        )
                    )
                    i = end
                    continue
                catalog.tables.append(table)
                catalog.measures.extend(_parse_measures(lines[i:end], path, table.name, line_offset=i))
                catalog.calculation_items.extend(
                    _parse_calculation_items(lines[i:end], path, table.name, line_offset=i)
                )
                i = end
                continue
            i += 1
    if not catalog.file:
        catalog.file = sorted(files)[0] if files else f"{name}.SemanticModel"
    return catalog


def decode_tmdl(raw: bytes) -> str:
    """Decode a ``.tmdl`` (or ``.bim``) file's bytes, BOM-aware.

    A UTF-16 BOM (either endianness — what a Windows PowerShell 5 redirect
    produces) decodes as UTF-16; a UTF-8 BOM is stripped; everything else must
    be valid UTF-8. Undecodable bytes raise ``UnicodeDecodeError`` so the
    caller reports a diagnostic naming the file — decoding with
    ``errors="replace"`` would silently parse mojibake into an EMPTY catalog
    and certify an unscanned model as clean.

    UTF-16-*without* a BOM is the dead spot the BOM checks miss: UTF-16-LE/BE of
    ASCII source text is 100% valid UTF-8 (NUL is a legal UTF-8 codepoint), so
    ``utf-8-sig`` decodes it to NUL-riddled text that matches no parser regex —
    an EMPTY catalog certified clean (issue #22). A NUL byte never appears in
    legitimate UTF-8 TMDL/JSON, so its presence means the bytes are not what we
    can safely decode: raise ``UnicodeDecodeError`` (the same signal a genuine
    decode failure gives) so the caller's error-severity file_unreadable path
    fires, rather than certifying an unscanned model as clean. We deliberately do
    NOT guess a UTF-16 encoding for a BOM-less file — a wrong guess would decode
    non-TMDL garbage into an empty-looking catalog, reintroducing the very
    silent-clean bug; a real UTF-16 export carries a BOM (handled above).
    """
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    if b"\x00" in raw:
        raise UnicodeDecodeError("utf-8", raw, 0, 1, "NUL byte - not valid UTF-8 (UTF-16 without a BOM?)")
    return raw.decode("utf-8-sig")


def group_tmdl_files(
    paths: list[Path], display: dict[Path, str], on_file=None
) -> tuple[dict[tuple[str, str], dict[str, str]], list[tuple[str, str, Exception]]]:
    """Group ``.tmdl`` files by semantic model.

    Returns ``(groups, unreadable)`` where ``groups`` maps a
    ``(model_root, model_name)`` key to ``{display_path: text}`` and
    ``unreadable`` lists ``(model_name, display_path, error)`` for files that
    could not be read or decoded. Models are keyed by their ROOT DIRECTORY
    (the ``*.SemanticModel`` / ``definition`` root, else the file's parent
    folder), resolved against the filesystem — so two same-named models in
    different folders stay distinct, and a flat folder of loose ``.tmdl``
    files forms ONE model (named after the folder); the name is display-only.
    A single unreadable file degrades only its own model — the rest still
    parse — so one bad file never collapses a whole multi-model run.
    ``on_file`` (optional) is ticked once per file for progress reporting.
    """
    groups: dict[tuple[str, str], dict[str, str]] = {}
    unreadable: list[tuple[str, str, Exception]] = []
    for path in paths:
        disp = display[path]
        root, model_name = model_root(path.resolve().as_posix())
        try:
            text = decode_tmdl(path.read_bytes())
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append((model_name, disp, exc))
        else:
            groups.setdefault((root, model_name), {})[disp] = text
        if on_file is not None:
            on_file(disp)
    return groups, unreadable
