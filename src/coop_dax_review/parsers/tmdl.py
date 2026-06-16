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

import re
from pathlib import Path, PurePosixPath

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
    ``.SemanticModel`` folder, model name ``Sales``.
    """
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        if part.lower().endswith(".semanticmodel"):
            return "/".join(parts[: index + 1]), part[: -len(".SemanticModel")]
    if "definition" in parts:
        index = parts.index("definition")
        if index > 0:
            return "/".join(parts[:index]), parts[index - 1]
    return (parts[0] if len(parts) > 1 else ""), PurePosixPath(path).stem


def _parse_table_block(lines: list[str], start: int, file: str) -> tuple[Table, int]:
    """Parse one ``table`` block beginning at ``lines[start]``; return the
    Table and the index of the first line past the block."""
    header = lines[start].strip()
    # Prefer the plain (or quoted) name; only treat it as a calculated table
    # when the name genuinely has a trailing ``= <DAX>`` (an '=' inside quotes
    # is not a separator — handled by the quote-aware alternatives).
    plain = _TABLE_PLAIN_RE.match(header)
    if plain:
        name, is_calc = _unquote(plain.group(1)), False
    else:
        name, is_calc = _unquote(_CALC_TABLE_RE.match(header).group(1)), True
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
        if inline:
            dax_parts.append(inline)
            dax_line = line_no
        i += 1
        while i < len(lines):
            nxt = lines[i]
            inner = nxt.strip()
            # DAX continues on lines indented deeper than the `measure` keyword;
            # a line at the same/shallower indent (the next measure/column/
            # partition) or a measure property (`formatString:`, or the
            # `=`-introduced `formatStringDefinition` block) ends it.
            if inner and (
                _indent(nxt) <= indent or _PROPERTY_RE.match(inner) or _FORMATSTRING_DEF_RE.match(inner)
            ):
                break
            if inner:
                if dax_line == 0:
                    dax_line = line_offset + i + 1
                dax_parts.append(inner)
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
                catalog.tables.append(table)
                catalog.measures.extend(_parse_measures(lines[i:end], path, table.name, line_offset=i))
                i = end
                continue
            i += 1
    if not catalog.file:
        catalog.file = sorted(files)[0] if files else f"{name}.SemanticModel"
    return catalog


def group_tmdl_files(
    paths: list[Path], display: dict[Path, str]
) -> tuple[dict[str, dict[str, str]], list[tuple[str, str, OSError]]]:
    """Group ``.tmdl`` files by semantic model.

    Returns ``(groups, unreadable)`` where ``groups`` is
    ``{model_name: {display_path: text}}`` and ``unreadable`` lists
    ``(model_name, display_path, error)`` for files that could not be read.
    A single unreadable file degrades only its own model — the rest still
    parse — so one bad file never collapses a whole multi-model run.
    """
    groups: dict[str, dict[str, str]] = {}
    unreadable: list[tuple[str, str, OSError]] = []
    for path in paths:
        disp = display[path]
        _, model_name = model_root(disp)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            unreadable.append((model_name, disp, exc))
            continue
        groups.setdefault(model_name, {})[disp] = text
    return groups, unreadable
