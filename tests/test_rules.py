"""Each Tier-1 rule: a positive (fires) and a negative (compliant) case."""

from coop_dax_review.rules.base import RuleContext


def _run(rule_module, catalog):
    from importlib import import_module

    mod = import_module(rule_module)
    ctx = RuleContext(mod.RULE, catalog)
    if mod.RULE.kind == "agent":
        return mod.detect(ctx)
    return mod.check(ctx)


# -- DAX-NO-NESTED-CALCULATE ------------------------------------------------


def test_nested_calculate_fires(make_catalog):
    cat = make_catalog(measures=[("M", "CALCULATE(CALCULATE(SUM(t[x]), a), b)")])
    assert len(_run("coop_dax_review.rules.dax_no_nested_calculate", cat)) == 1


def test_sibling_calculates_do_not_fire(make_catalog):
    cat = make_catalog(measures=[("M", "VAR a = CALCULATE(x) VAR b = CALCULATE(y) RETURN a - b")])
    assert _run("coop_dax_review.rules.dax_no_nested_calculate", cat) == []


def test_calculate_inside_string_is_ignored(make_catalog):
    cat = make_catalog(measures=[("M", 'CALCULATE(SUM(t[x]), "CALCULATE(")')])
    assert _run("coop_dax_review.rules.dax_no_nested_calculate", cat) == []


# -- DAX-MEASURE-CATEGORY ---------------------------------------------------


def test_measure_category_fires_on_bare_name(make_catalog):
    cat = make_catalog(measures=[("TotalRevenue", "1")])
    assert len(_run("coop_dax_review.rules.dax_measure_category", cat)) == 1


def test_measure_category_passes_on_prefixed_name(make_catalog):
    cat = make_catalog(measures=[("Sales: Total Revenue", "1")])
    assert _run("coop_dax_review.rules.dax_measure_category", cat) == []


# -- DAX-MEASURE-NOT-PREFIXED -----------------------------------------------


def test_measure_prefixed_fires(make_catalog):
    cat = make_catalog(
        measures=[("Sales: A", "1"), ("Sales: B", "FactSales[Sales: A]")],
        tables=[("FactSales", ["Revenue"])],
    )
    findings = _run("coop_dax_review.rules.dax_measure_not_prefixed", cat)
    assert len(findings) == 1
    assert "Sales: A" in findings[0].message


def test_qualified_column_does_not_fire(make_catalog):
    cat = make_catalog(measures=[("Sales: B", "FactSales[Revenue]")], tables=[("FactSales", ["Revenue"])])
    assert _run("coop_dax_review.rules.dax_measure_not_prefixed", cat) == []


# -- DAX-COLUMN-PREFIXED ----------------------------------------------------


def test_bare_column_fires(make_catalog):
    cat = make_catalog(measures=[("Sales: B", "SUM([Revenue])")], tables=[("FactSales", ["Revenue"])])
    assert len(_run("coop_dax_review.rules.dax_column_prefixed", cat)) == 1


def test_bare_measure_ref_does_not_fire(make_catalog):
    cat = make_catalog(
        measures=[("Sales: A", "1"), ("Sales: B", "[Sales: A] * 2")],
        tables=[("FactSales", ["Revenue"])],
    )
    assert _run("coop_dax_review.rules.dax_column_prefixed", cat) == []


# -- DAX-BIDI-RELATIONSHIP --------------------------------------------------


def test_bidi_relationship_fires(make_catalog):
    cat = make_catalog(
        relationships=[
            {
                "from_table": "F",
                "from_column": "k",
                "to_table": "D",
                "to_column": "k",
                "cross_filter": "both",
            }
        ]
    )
    assert len(_run("coop_dax_review.rules.dax_bidi_relationship", cat)) == 1


def test_single_relationship_does_not_fire(make_catalog):
    cat = make_catalog(
        relationships=[{"from_table": "F", "from_column": "k", "to_table": "D", "to_column": "k"}]
    )
    assert _run("coop_dax_review.rules.dax_bidi_relationship", cat) == []


# -- DAX-MARKED-DATE-TABLE --------------------------------------------------


def test_date_table_fires_when_time_intel_used_without_marked_table(make_catalog):
    cat = make_catalog(measures=[("Sales: YTD", "DATESYTD(DimDate[Date])")])
    assert len(_run("coop_dax_review.rules.dax_marked_date_table", cat)) == 1


def test_date_table_silent_without_time_intel(make_catalog):
    cat = make_catalog(measures=[("Sales: Rev", "SUM(F[x])")])
    assert _run("coop_dax_review.rules.dax_marked_date_table", cat) == []


def test_date_table_silent_when_marked(make_catalog):
    cat = make_catalog(
        measures=[("Sales: YTD", "DATESYTD(DimDate[Date])")],
        tables=[("DimDate", ["Date"])],
        date_table="DimDate",
    )
    assert _run("coop_dax_review.rules.dax_marked_date_table", cat) == []


# -- DAX-KEEPFILTERS-NEEDED (agent) -----------------------------------------


def test_keepfilters_emits_agent_review(make_catalog):
    cat = make_catalog(measures=[("Sales: A", 'CALCULATE([x], D[Tier] = "Premium")')])
    items = _run("coop_dax_review.rules.dax_keepfilters_needed", cat)
    assert len(items) == 1 and items[0].rule_id == "DAX-KEEPFILTERS-NEEDED"


def test_keepfilters_silent_when_present(make_catalog):
    cat = make_catalog(measures=[("Sales: A", 'CALCULATE([x], KEEPFILTERS(D[Tier] = "Premium"))')])
    assert _run("coop_dax_review.rules.dax_keepfilters_needed", cat) == []


def test_keepfilters_no_false_positive_on_unrelated_comparison(make_catalog):
    # CALCULATE carries only a table/column filter; the comparison is elsewhere.
    cat = make_catalog(
        measures=[("Sales: A", "IF([Total] > 0, CALCULATE([x], DimDate[Year]), 0)")],
    )
    assert _run("coop_dax_review.rules.dax_keepfilters_needed", cat) == []


def test_keepfilters_per_calculate_not_suppressed_by_a_sibling(make_catalog):
    # First CALCULATE uses KEEPFILTERS; the second (bare) one must still surface.
    dax = (
        'VAR A = CALCULATE([x], KEEPFILTERS(D[Tier] = "P")) VAR B = CALCULATE([x], C[Seg] = "E") RETURN A + B'
    )
    items = _run("coop_dax_review.rules.dax_keepfilters_needed", make_catalog(measures=[("Sales: A", dax)]))
    assert len(items) == 1  # only the bare-filter CALCULATE
