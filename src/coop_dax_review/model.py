"""The model catalog the rule engine runs against.

Many DAX rules cannot be judged from a measure's text alone — telling a
measure reference ``[X]`` from a column reference ``[X]`` (§1), spotting
bidirectional relationships (§7), a marked Date table (§8), a snowflake
chain (§6), or Direct Lake calculated-column constraints (§13) all need the
*model* around the measure. So both parsers (TMDL and .bim) build one
``ModelCatalog`` per semantic model — tables, columns, measures (+DAX),
relationships, storage mode, date table — and rules run with that context.

Names are kept twice: ``name`` is the display (original-case) name used in
findings, and the lookup indexes are normalized (lower-cased, brackets
stripped) so reference matching is case-insensitive like DAX itself. Every
object keeps its source ``file`` and ``line`` so findings point somewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional

from coop_dax_review.diagnostics import Diagnostic


def normalize(name: str) -> str:
    """Lower-case an identifier and strip surrounding brackets/quotes.

    ``'DimDate'`` -> ``dimdate``;  ``[Sales: Total Revenue]`` -> ``sales: total revenue``.
    """
    name = name.strip()
    while len(name) >= 2 and name[0] in "'\"[" and name[-1] in "'\"]":
        name = name[1:-1].strip()
    return name.lower()


@dataclass
class Column:
    """A column on a table, with its source line and normalized type."""

    name: str
    data_type: str = ""  # e.g. "int64", "dateTime", "string" (TMDL/TOM spelling)
    line: int = 0
    is_calculated: bool = False  # `column X = <DAX>` (TMDL) / "type": "calculated" (.bim)
    data_category: str = ""  # e.g. "Time" — marks the date column of a Date table
    expression: str = ""  # the DAX of a calculated column, if any
    is_hidden: bool = False  # isHidden: true
    summarize_by: str = ""  # summarizeBy value (e.g. "none", "sum"); "" = model default


@dataclass
class Measure:
    """A measure: its name, DAX expression, and where it is defined."""

    name: str
    dax: str
    table: str = ""  # home table (display name)
    file: str = ""
    line: int = 0  # 1-based file line of the `measure` declaration
    dax_line: int = 0  # 1-based file line where the DAX body's first char sits
    # (== line for an inline measure; line+ for `measure X =\n  <body>`)
    format_string: str = ""  # the measure's formatString property, "" if none
    display_folder: str = ""  # the measure's displayFolder property, "" if none
    is_hidden: bool = False  # isHidden: true — not rendered on a visual
    description: str = ""  # TOM description (TMDL `///` doc-comment / .bim "description")


@dataclass
class CalculationItem:
    """One ``calculationItem`` in a calculation group, with its DAX expression."""

    name: str
    dax: str
    table: str = ""  # the calculation group's table (display name)
    file: str = ""
    line: int = 0  # 1-based line of the `calculationItem` declaration
    dax_line: int = 0  # 1-based line where the item's DAX body starts
    format_string: str = ""  # a per-item formatStringExpression, if any


@dataclass
class Relationship:
    """A model relationship (the from-side is the many side by convention)."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cross_filter: str = "single"  # "single" | "both" (bidirectional)
    is_active: bool = True
    file: str = ""
    line: int = 0

    @property
    def label(self) -> str:
        return f"{self.from_table}[{self.from_column}] -> {self.to_table}[{self.to_column}]"


@dataclass
class Table:
    """A table: its columns, storage mode, and whether it's a marked Date table."""

    name: str
    file: str = ""
    line: int = 0
    columns: list[Column] = field(default_factory=list)
    storage_mode: str = ""  # "import" | "directLake" | "directQuery" | "dual" | ""
    is_date_table: bool = False  # marked Date table (dataCategory Time or template)
    is_hidden: bool = False  # table-level isHidden — hides ALL its columns/measures
    is_calculated: bool = False  # a calculated table (`table X = <DAX>`)
    expression: str = ""  # the DAX of a calculated table, if any
    dax_line: int = 0  # 1-based line where a calculated table's DAX body starts


@dataclass
class ModelCatalog:
    """One parsed semantic model — the context every rule receives."""

    name: str  # display name of the semantic model
    file: str = ""  # primary file (model.tmdl / model.bim) for model-level findings
    tables: list[Table] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    # Calculation-group items are kept OUT of `measures` on purpose: naming rules
    # like DAX-MEASURE-CATEGORY (§1) would misfire on item names (issue #8).
    calculation_items: list[CalculationItem] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    # -- lookup indexes (normalized keys) ----------------------------------

    @cached_property
    def measure_names(self) -> set[str]:
        """Normalized names of every measure in the model."""
        return {normalize(m.name) for m in self.measures}

    @cached_property
    def column_names(self) -> set[str]:
        """Normalized names of every column, across all tables (un-qualified)."""
        return {normalize(c.name) for t in self.tables for c in t.columns}

    @cached_property
    def columns_by_table(self) -> dict[str, set[str]]:
        """``{normalized table: {normalized column, ...}}``."""
        out: dict[str, set[str]] = {}
        for table in self.tables:
            out[normalize(table.name)] = {normalize(c.name) for c in table.columns}
        return out

    @cached_property
    def table_names(self) -> set[str]:
        return {normalize(t.name) for t in self.tables}

    @cached_property
    def hidden_tables(self) -> set[str]:
        """Normalized names of tables marked ``isHidden``.

        Hiding a table removes it — columns AND measures — from the report
        field list, so rules that skip hidden objects treat everything on a
        hidden table as hidden too.
        """
        return {normalize(t.name) for t in self.tables if t.is_hidden}

    @property
    def storage_mode(self) -> str:
        """The model's effective storage mode.

        ``"directLake"`` if any table is Direct Lake (the mode that carries
        the §13 calculated-column constraint); otherwise the most common
        explicit table mode, or ``""`` when unknown.
        """
        modes = [t.storage_mode for t in self.tables if t.storage_mode]
        if any(m.lower() == "directlake" for m in modes):  # case-insensitive: TMDL mode is verbatim
            return "directLake"
        if not modes:
            return ""
        # sorted() before max() makes the tie-break deterministic (smallest
        # mode name wins) rather than depending on set-iteration / hash seed.
        return max(sorted(set(modes)), key=modes.count)

    @property
    def date_table(self) -> Optional[str]:
        """Display name of the marked Date table, or None if none is marked."""
        for table in self.tables:
            if table.is_date_table:
                return table.name
        return None

    def is_measure(self, name: str) -> bool:
        return normalize(name) in self.measure_names

    def is_column(self, name: str) -> bool:
        return normalize(name) in self.column_names
