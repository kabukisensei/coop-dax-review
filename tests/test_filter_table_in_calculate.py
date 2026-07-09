"""Tests for DAX-FILTER-TABLE-IN-CALCULATE (§4)."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext

_TABLES = [("DimCustomer", ["MarketSegment", "CustomerId"]), ("FactSales", ["Revenue"])]


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_filter_table_in_calculate")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def test_fires_on_bad_example(make_catalog):
    # §4 Bad: FILTER over the whole table inside CALCULATE.
    dax = (
        "CALCULATE(\n"
        "    [Sales: Total Revenue],\n"
        "    FILTER(\n"
        "        DimCustomer,\n"
        '        DimCustomer[MarketSegment] = "Enterprise"\n'
        "    )\n"
        ")"
    )
    cat = make_catalog(measures=[("Sales: Enterprise Revenue", dax)], tables=_TABLES)
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].object == "[Sales: Enterprise Revenue]"
    # Points at the FILTER line (line 3 of the body, dax_line defaults to line 1).
    assert findings[0].line == 3


def test_compliant_column_filter_silent(make_catalog):
    # §4 Good: plain column filter, no FILTER wrapper.
    dax = 'CALCULATE(\n    [Sales: Total Revenue],\n    DimCustomer[MarketSegment] = "Enterprise"\n)'
    cat = make_catalog(measures=[("Sales: Enterprise Revenue", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_quoted_table_fires(make_catalog):
    dax = "CALCULATE([m], FILTER('DimCustomer', 'DimCustomer'[MarketSegment] = \"Enterprise\"))"
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert len(_run(cat)) == 1


def test_filter_over_all_silent(make_catalog):
    # FILTER(ALL(...)) is a legitimate pattern, not a whole-table filter.
    dax = 'CALCULATE([m], FILTER(ALL(DimCustomer), DimCustomer[MarketSegment] = "Enterprise"))'
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_filter_over_values_silent(make_catalog):
    dax = 'CALCULATE([m], FILTER(VALUES(DimCustomer[CustomerId]), DimCustomer[MarketSegment] = "X"))'
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_multi_table_predicate_silent(make_catalog):
    # Predicate spans two tables -> legitimate FILTER.
    dax = "CALCULATE([m], FILTER(DimCustomer, DimCustomer[CustomerId] = FactSales[Revenue]))"
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_logical_predicate_silent(make_catalog):
    # Compound condition (&&) is not a single simple comparison.
    dax = (
        'CALCULATE([m], FILTER(DimCustomer, DimCustomer[MarketSegment] = "X" && DimCustomer[CustomerId] > 5))'
    )
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_measure_predicate_silent(make_catalog):
    # Predicate compares a measure ref -> not a plain column filter; leave alone.
    dax = "CALCULATE([m], FILTER(DimCustomer, [Sales: Total Revenue] > 100))"
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_function_predicate_silent(make_catalog):
    # Predicate uses a function -> legitimate FILTER, not flagged.
    dax = 'CALCULATE([m], FILTER(DimCustomer, LEFT(DimCustomer[MarketSegment], 3) = "Ent"))'
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_filter_outside_calculate_silent(make_catalog):
    # A FILTER not inside CALCULATE is out of scope for §4.
    dax = 'SUMX(FILTER(DimCustomer, DimCustomer[MarketSegment] = "X"), FactSales[Revenue])'
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_iterator_table_arg_in_expression_silent(make_catalog):
    # Issue #11: FILTER as an iterator's table argument inside CALCULATE's
    # FIRST (expression) argument is the endorsed §9 idiom — never a §4 smell.
    dax = (
        "CALCULATE(\n"
        "    SUMX(FILTER(DimCustomer, DimCustomer[CustomerId] > 0), FactSales[Revenue]),\n"
        "    FactSales[Revenue] > 100\n"
        ")"
    )
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_iterator_in_expression_plus_filter_arg_fires_once(make_catalog):
    # Issue #11: the FILTER in the expression argument stays silent, while the
    # FILTER used as a direct filter argument still fires — with the right line.
    dax = (
        "CALCULATE(\n"
        "    SUMX(FILTER(DimCustomer, DimCustomer[CustomerId] > 0), FactSales[Revenue]),\n"
        '    FILTER(DimCustomer, DimCustomer[MarketSegment] = "Enterprise")\n'
        ")"
    )
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].line == 3  # the filter-argument FILTER, not the iterator's


def test_keyword_in_comment_silent(make_catalog):
    # Masking: the FILTER lives in a comment, so nothing fires.
    dax = (
        "CALCULATE(\n"
        "    [Sales: Total Revenue],\n"
        '    -- FILTER(DimCustomer, DimCustomer[MarketSegment] = "X")\n'
        '    DimCustomer[MarketSegment] = "Enterprise"\n'
        ")"
    )
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []


def test_unknown_table_silent(make_catalog):
    # First arg is not a known table name -> not flagged.
    dax = 'CALCULATE([m], FILTER(NotATable, NotATable[Col] = "X"))'
    cat = make_catalog(measures=[("Sales: Q", dax)], tables=_TABLES)
    assert _run(cat) == []
