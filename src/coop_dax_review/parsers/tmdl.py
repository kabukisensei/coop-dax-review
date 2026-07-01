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
from coop_dax_review.model import Column, Measure, ModelCatalog, Relationship, Table

# A table header line (plain or calculated). Name extraction is quote-aware
# below so an '=' inside a quoted name isn't mistaken for the calc separator.
_TABLE_HEADER_RE = re.compile(r"^table\s+\S")
_TABLE_PLAIN_RE = re.compile(r"^table\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*$")
_CALC_TABLE_RE = re.compile(r"^table\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*=\s*(.*)$")
_MEASURE_RE = re.compile(r"^measure\s+('[^']*'|\"[^\"]*\"|[^=]+?)\s*=\s*(.*)$")
_COLUMN_RE = re.compile(r"^column\s+('[^']*'|\"[^\"]*\"|[^=\s]+)\s*(=\s*(.*))?$")
_DATATYPE_RE = re.compile(r"^dataType\s*:\s*(\S+)")
_DATACATEGORY_RE = re.compile(r"^dataCategory\s*:\s*(\S+)")
_ISHIDDEN_RE = re.compile(r"^isHidden\s*:\s*(\S+)", re.IGNORECASE)
_SUMMARIZEBY_RE = re.compile(r"^summarizeBy\s*:\s*(\S+)", re.IGNORECASE)
_DISPLAYFOLDER_RE = re.compile(r"^displayFolder\s*:\s*(.+?)\s*$", re.IGNORECASE)
_PARTITION_RE = re.compile(r"^partition\s+(.+?)\s*=\s*(\w+)\s*$")
_MODE_RE = re.compile(r"^mode\s*:\s*(\S+)")
_RELATIONSHIP_RE = re.compile(r"^relationship\s+(\S+)")
_FROM_COLUMN_RE = re.compile(r"^fromColumn\s*:\s*(.+?)\s*$")
_TO_COLUMN_RE = re.compile(r"^toColumn\s*:\s*(.+?)\s*$")
_CROSSFILTER_RE = re.compile(r"^crossFilteringBehavior\s*:\s*(\S+)")
_ISACTIVE_RE = re.compile(r"^isActive\s*:\s*(\S+)")
_PROPERTY_RE = re.compile(r"^[A-Za-z][\w]*\s*:")
_FORMATSTRING_RE = re.compile(r"^formatString\s*:\s*(.+?)\s*$", re.IGNORECASE)
_FORMATSTRING_DEF_RE = re.compile(r"^formatStringDefinition\b", re.IGNORECASE)
# The finite set of real TMDL measure properties / child objects (per the TOM
# Measure object). The DAX-continuation loop must stop ONLY on one of these:
# treating ANY `Word:` line as a property truncates measure bodies at the
# standards' own §12 `/* Measure: ... Purpose: ... */` header lines, whose
# `Purpose:` etc. match the generic property shape but are comment text.
# Three shapes: `name: value` properties, `name = <expr>` children, and the
# named/bare child objects (`annotation X = ...`, `kpi`).
_MEASURE_PROP_RE = re.compile(
    r"^(?:"
    r"(?:formatString|displayFolder|lineageTag|sourceLineageTag|description"
    r"|isHidden|isSimpleMeasure|dataCategory|dataType|errorMessage|state)\s*:"
    r"|(?:formatStringDefinition|detailRowsDefinition|changedProperty)\s*="
    r"|(?:annotation|extendedProperty)\s+\S"
    r"|kpi\s*$"
    r")",
    re.IGNORECASE,
)
_DATE_TABLE_ANNOTATION = "__pbi_templatedatetable"


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
    current_column: Column | None = None
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
            col_indent = _indent(raw)
            current_column = Column(
                name=_unquote(col.group(1)),
                line=i + 1,
                is_calculated=bool(col.group(2)),
                expression=(col.group(3) or "").strip(),
            )
            table.columns.append(current_column)
            i += 1
            # A calculated column whose DAX body spans the following indented
            # lines: consume them as the expression WITHOUT clearing the
            # current column, so a trailing dataType:/dataCategory: still binds.
            if current_column.is_calculated and not current_column.expression:
                dax_parts: list[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    inner = nxt.strip()
                    if inner and (_indent(nxt) <= col_indent or _PROPERTY_RE.match(inner)):
                        break
                    if inner:
                        dax_parts.append(inner)
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

        if current_column is not None:
            ih = _ISHIDDEN_RE.match(stripped)
            if ih:
                current_column.is_hidden = ih.group(1).lower() == "true"
                i += 1
                continue
            sb = _SUMMARIZEBY_RE.match(stripped)
            if sb:
                current_column.summarize_by = sb.group(1)
                i += 1
                continue

        part = _PARTITION_RE.match(stripped)
        if part:
            current_column = None
            mode, i = _consume_partition(lines, i, _indent(raw))
            if mode:
                table.storage_mode = mode
            continue

        if stripped.lower().startswith("annotation ") and _DATE_TABLE_ANNOTATION in stripped.lower():
            table.is_date_table = True

        current_column = None
        i += 1
    return table, i


def _consume_partition(lines: list[str], start: int, header_indent: int) -> tuple[str, int]:
    """Read a partition block; return (storage_mode, next_index)."""
    mode = ""
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
    return mode, i


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
        inline = m.group(2)
        dax_parts: list[str] = []
        dax_line = 0
        in_comment = False
        if inline:
            dax_parts.append(inline)
            dax_line = line_no
            in_comment = _block_comment_open(inline, False)
        i += 1
        while i < len(lines):
            nxt = lines[i]
            inner = nxt.strip()
            # DAX continues on lines indented deeper than the `measure` keyword;
            # a line at the same/shallower indent (the next measure/column/
            # partition) or a real measure property (the finite TMDL set —
            # `formatString:`, the `=`-introduced `formatStringDefinition`
            # block, ...) ends it. A line inside a still-open `/* ... */` block
            # is always body text: the §12 header's `Purpose:` lines look like
            # properties but are comment content.
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
                i = end
                continue
            i += 1
    if not catalog.file:
        catalog.file = sorted(files)[0] if files else f"{name}.SemanticModel"
    return catalog


def decode_tmdl(raw: bytes) -> str:
    """Decode a ``.tmdl`` file's bytes, BOM-aware.

    A UTF-16 BOM (either endianness — what a Windows PowerShell 5 redirect
    produces) decodes as UTF-16; a UTF-8 BOM is stripped; everything else must
    be valid UTF-8. Undecodable bytes raise ``UnicodeDecodeError`` so the
    caller reports a diagnostic naming the file — decoding with
    ``errors="replace"`` would silently parse mojibake into an EMPTY catalog
    and certify an unscanned model as clean.
    """
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
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
