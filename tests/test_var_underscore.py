"""DAX-VAR-UNDERSCORE (§27): local variables carry a leading underscore."""

from importlib import import_module

from coop_dax_review.model import Column
from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_var_underscore")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# The §27 BEFORE example: descriptive VAR names without the prefix.
_BEFORE = (
    "VAR CurrentYearSales =\n"
    "    SUM(FactSales[Revenue])\n"
    "VAR PriorYearSales =\n"
    "    CALCULATE(\n"
    "        SUM(FactSales[Revenue]),\n"
    "        SAMEPERIODLASTYEAR(DimDate[Date])\n"
    "    )\n"
    "RETURN\n"
    "    CurrentYearSales - PriorYearSales"
)

# The §27 AFTER example: every VAR carries the leading underscore.
_AFTER = (
    "VAR _CurrentYearSales =\n"
    "    SUM(FactSales[Revenue])\n"
    "VAR _PriorYearSales =\n"
    "    CALCULATE(\n"
    "        SUM(FactSales[Revenue]),\n"
    "        SAMEPERIODLASTYEAR(DimDate[Date])\n"
    "    )\n"
    "RETURN\n"
    "    _CurrentYearSales - _PriorYearSales"
)


def test_before_example_fires_on_each_var(make_catalog):
    cat = make_catalog(measures=[("Sales: YoY Growth", _BEFORE)])
    findings = _run(cat)
    assert len(findings) == 2
    assert all(f.object == "[Sales: YoY Growth]" for f in findings)
    assert "CurrentYearSales" in findings[0].message
    assert "PriorYearSales" in findings[1].message
    assert findings[0].line == 1  # first VAR sits on the measure's first line
    assert findings[1].line == 3  # second VAR sits two lines down


def test_after_example_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: YoY Growth", _AFTER)])
    assert _run(cat) == []


def test_double_underscore_book_style_also_compliant(make_catalog):
    # DAX for Humans writes __Table / __Result; any leading underscore passes.
    dax = "VAR __Table =\n    FILTER(FactSales, FactSales[Quantity] > 10)\nRETURN\n    SUMX(__Table, FactSales[Revenue])"
    cat = make_catalog(measures=[("Sales: Large Orders", dax)])
    assert _run(cat) == []


def test_var_keyword_in_string_or_comment_ignored(make_catalog):
    dax = "SUM(FactSales[Revenue]) -- VAR Foo = 1\n + 0 /* VAR Bar = 2 */ + 0"
    cat = make_catalog(measures=[("Sales: Total", dax)])
    assert _run(cat) == []


def test_column_named_var_ignored(make_catalog):
    # A bracketed column ref whose name starts with VAR must not parse as a
    # variable declaration.
    cat = make_catalog(measures=[("Sales: Total", "SUM(FactSales[VAR Amount])")])
    assert _run(cat) == []


def test_no_var_measure_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Total", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_calculated_column_var_also_checked(make_catalog):
    # §27 says "every local variable" — the rule opts into calculated columns.
    cat = make_catalog(tables=[("FactSales", ["Amount", "Cost"])])
    cat.tables[0].columns.append(
        Column(
            name="Margin",
            is_calculated=True,
            expression="VAR Total = FactSales[Amount] - FactSales[Cost]\nRETURN\n    Total",
        )
    )
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].object == "FactSales[Margin]"
    assert "Total" in findings[0].message
