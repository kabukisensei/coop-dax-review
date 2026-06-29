"""DAX-MEASURE-IN-ITERATOR (§9): a measure ref inside a row iterator fires;
a column-only iterator stays silent."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext

_MODULE = "coop_dax_review.rules.dax_measure_in_iterator"


def _run(cat):
    mod = import_module(_MODULE)
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# -- the §9 example fires ---------------------------------------------------


def test_section9_example_fires(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            (
                "Sales: Average Customer Revenue",
                "AVERAGEX(\n    VALUES(DimCustomer[CustomerId]),\n    [Sales: Total Revenue]\n)",
            ),
        ],
        tables=[("DimCustomer", ["CustomerId"]), ("FactSales", ["Revenue"])],
    )
    findings = _run(cat)
    assert len(findings) == 1
    f = findings[0]
    assert f.object == "[Sales: Average Customer Revenue]"
    assert "Sales: Total Revenue" in f.message
    assert f.severity == "info"
    assert f.standard_ref == "§9"
    # the measure ref sits on the 3rd line of the DAX body
    assert f.line == 3


# -- a column-only iterator stays silent ------------------------------------


def test_column_only_iterator_silent(make_catalog):
    cat = make_catalog(
        measures=[("Sales: X", "SUMX(Sales, Sales[Qty] * Sales[Price])")],
        tables=[("Sales", ["Qty", "Price"])],
    )
    assert _run(cat) == []


# -- a bare column (same-table) that is NOT a measure stays silent ----------


def test_bare_non_measure_ref_silent(make_catalog):
    # [Qty] is a bare ref but resolves to a column, not a measure -> no fire.
    cat = make_catalog(
        measures=[("Sales: X", "SUMX(Sales, [Qty] * 2)")],
        tables=[("Sales", ["Qty"])],
    )
    assert _run(cat) == []


# -- a measure referenced OUTSIDE any iterator stays silent -----------------


def test_measure_outside_iterator_silent(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Doubled", "[Sales: Total Revenue] * 2"),
        ],
        tables=[("FactSales", ["Revenue"])],
    )
    assert _run(cat) == []


# -- a measure ref hidden in a comment/string does not fire -----------------


def test_measure_ref_in_comment_silent(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Y", "SUMX(Sales, Sales[Qty]) -- [Sales: Total Revenue]"),
        ],
        tables=[("Sales", ["Qty"]), ("FactSales", ["Revenue"])],
    )
    assert _run(cat) == []


# -- table-prefixed measure ref inside iterator is a column ref, not flagged -


def test_qualified_ref_silent(make_catalog):
    # Even though [Sales: Total Revenue] is a measure name, written as
    # Table[...] it is a (column) reference -> this rule does not fire.
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Z", "SUMX(FactSales, FactSales[Sales: Total Revenue])"),
        ],
        tables=[("FactSales", ["Revenue"])],
    )
    assert _run(cat) == []


# -- nested iterators do not double-count the same ref ----------------------


def test_nested_iterators_no_double_count(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            (
                "Sales: Nested",
                "SUMX(VALUES(DimRegion[Region]), AVERAGEX(VALUES(DimCustomer[Id]), [Sales: Total Revenue]))",
            ),
        ],
        tables=[
            ("DimRegion", ["Region"]),
            ("DimCustomer", ["Id"]),
            ("FactSales", ["Revenue"]),
        ],
    )
    findings = _run(cat)
    assert len(findings) == 1


# -- a measure ref after RETURN inside an iterator still fires ---------------


def test_return_measure_ref_inside_iterator_fires(make_catalog):
    # `RETURN [Base]` inside SUMX is a bare measure ref (not a `RETURN[...]`
    # table prefix), so the iterator context-transition rule must still fire
    # (regression: the keyword-before-bracket mis-parse made it skip the ref).
    cat = make_catalog(
        measures=[
            ("Sales: Base", "SUM(FactSales[Revenue])"),
            ("Sales: M", "SUMX(FactSales, VAR z = 1 RETURN [Sales: Base])"),
        ],
        tables=[("FactSales", ["Revenue"])],
    )
    findings = _run(cat)
    assert len(findings) == 1
    assert "Sales: Base" in findings[0].message


# -- nested iterators name the innermost enclosing iterator ------------------


def test_nested_iterator_names_innermost(make_catalog):
    # [Total] sits directly inside AVERAGEX (itself inside SUMX) — the message
    # must name AVERAGEX, the iterator that actually wraps the reference.
    cat = make_catalog(
        measures=[
            ("Sales: Total", "SUM(FactSales[Revenue])"),
            ("Sales: M", "SUMX(FactSales, AVERAGEX(FactSales, [Sales: Total]))"),
        ],
        tables=[("FactSales", ["Revenue"])],
    )
    findings = _run(cat)
    assert len(findings) == 1
    assert "AVERAGEX" in findings[0].message
    assert "SUMX" not in findings[0].message


# -- multiple distinct measure refs in one iterator each fire ---------------


def test_multiple_measure_refs_fire(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: A", "SUM(FactSales[Revenue])"),
            ("Sales: B", "SUM(FactSales[Cost])"),
            ("Sales: Combo", "SUMX(VALUES(Dim[Id]), [Sales: A] + [Sales: B])"),
        ],
        tables=[("Dim", ["Id"]), ("FactSales", ["Revenue", "Cost"])],
    )
    findings = _run(cat)
    assert len(findings) == 2


# -- metadata sanity --------------------------------------------------------


def test_rule_metadata():
    mod = import_module(_MODULE)
    assert mod.RULE.id == "DAX-MEASURE-IN-ITERATOR"
    assert mod.RULE.kind == "deterministic"
    assert mod.RULE.severity == "info"
    assert mod.RULE.category == "context-transition"
    assert mod.RULE.tier == 2
