"""DAX-NO-GRATUITOUS-CALCULATE (§29): no single-argument CALCULATE in measures."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_no_gratuitous_calculate")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def test_single_arg_calculate_fires(make_catalog):
    # The §29 BEFORE example.
    cat = make_catalog(measures=[("Sales: Total Revenue", "CALCULATE(SUM(FactSales[Revenue]))")])
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].object == "[Sales: Total Revenue]"
    assert findings[0].line == 1


def test_plain_aggregation_silent(make_catalog):
    # The §29 AFTER example.
    cat = make_catalog(measures=[("Sales: Total Revenue", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_calculate_with_filter_argument_silent(make_catalog):
    cat = make_catalog(
        measures=[("Sales: 2024 Revenue", "CALCULATE(SUM(FactSales[Revenue]), DimDate[Year] = 2024)")]
    )
    assert _run(cat) == []


def test_calculate_with_table_filter_silent(make_catalog):
    dax = "CALCULATE(\n    [Sales: Revenue],\n    DATESYTD(DimDate[Date])\n)"
    cat = make_catalog(measures=[("Sales: Revenue YTD", dax)])
    assert _run(cat) == []


def test_single_arg_inside_iterator_silent(make_catalog):
    # Inside a row context a single-argument CALCULATE is context transition —
    # §30 case 3 / §32 territory, never gratuitous.
    dax = "SUMX(FactSales, CALCULATE(SUM(FactSales[Revenue])))"
    cat = make_catalog(measures=[("Sales: Row Revenue", dax)])
    assert _run(cat) == []


def test_single_arg_inside_filter_predicate_silent(make_catalog):
    dax = (
        "VAR _BigCustomers =\n"
        "    FILTER(\n"
        "        VALUES(DimCustomer[CustomerId]),\n"
        "        CALCULATE(SUM(FactSales[Revenue])) > 10000\n"
        "    )\n"
        "RETURN\n"
        "    COUNTROWS(_BigCustomers)"
    )
    cat = make_catalog(measures=[("Customer: Big Count", dax)])
    assert _run(cat) == []


def test_single_arg_calculatetable_fires(make_catalog):
    # A one-argument CALCULATETABLE outside row context changes nothing either.
    cat = make_catalog(measures=[("Sales: Row Count", "COUNTROWS(CALCULATETABLE(FactSales))")])
    findings = _run(cat)
    assert len(findings) == 1
    assert "CALCULATETABLE" in findings[0].message


def test_nested_single_arg_calculate_fires_once(make_catalog):
    # CALCULATE(CALCULATE(SUM(...))): both calls are single-argument, but one
    # finding is enough — the rule defers to the innermost call.
    cat = make_catalog(measures=[("Sales: Total", "CALCULATE(CALCULATE(SUM(FactSales[Revenue])))")])
    assert len(_run(cat)) == 1


def test_calculate_in_string_or_comment_ignored(make_catalog):
    dax = "SUM(FactSales[Revenue]) -- CALCULATE(\n + 0 /* CALCULATE( */"
    cat = make_catalog(measures=[("Sales: Total", dax)])
    assert _run(cat) == []


def test_column_named_like_calculate_not_a_call(make_catalog):
    # Bracket contents are blanked: a column named [CALCULATE(] cannot parse as
    # a function call.
    cat = make_catalog(measures=[("Sales: Total", "SUM(FactSales[CALCULATE(])")])
    assert _run(cat) == []
