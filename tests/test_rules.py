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


def test_paren_in_name_does_not_hide_nested_calculate(make_catalog):
    # A ')' inside a column/measure name must not pop the outer CALCULATE off the
    # depth stack early — the genuinely nested CALCULATE must still fire.
    cat = make_catalog(measures=[("M", "CALCULATE( [Net) Sales], CALCULATE([Other]) )")])
    assert len(_run("coop_dax_review.rules.dax_no_nested_calculate", cat)) == 1


def test_paren_in_name_does_not_flag_sibling_calculate(make_catalog):
    # A '(' inside a name must not inflate depth and flag an independent sibling
    # CALCULATE as nested.
    cat = make_catalog(measures=[("M", "CALCULATE( [Net( Sales] ) + CALCULATE( [Other] )")])
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


def test_return_before_measure_ref_is_not_table_prefixed(make_catalog):
    # `RETURN [Sales: A]` is a bare measure ref, NOT a `RETURN[...]` table prefix,
    # so the not-prefixed rule must stay silent (regression for the keyword-before-
    # bracket mis-parse).
    cat = make_catalog(
        measures=[("Sales: A", "1"), ("Sales: B", "VAR x = 1\nRETURN [Sales: A]")],
        tables=[("FactSales", ["Revenue"])],
    )
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


# -- DAX-ESTATE-MEASURE-DRIFT -----------------------------------------------


def _run_estate(rule_module, catalogs):
    from importlib import import_module
    from coop_dax_review.rules.base import EstateContext

    mod = import_module(rule_module)
    ctx = EstateContext(mod.RULE, catalogs)
    return mod.check_estate(ctx)


def test_estate_measure_drift_fires(make_catalog):
    c1 = make_catalog(name="ModA", measures=[("Sales", "SUM(x)")])
    c2 = make_catalog(name="ModB", measures=[("Sales", "SUM(y)")])
    res = _run_estate("coop_dax_review.rules.dax_estate_measure_drift", [c1, c2])
    assert len(res) == 1
    assert "ModA <> ModB" in res[0].model


def test_estate_measure_drift_compliant(make_catalog):
    c1 = make_catalog(name="ModA", measures=[("Sales", "SUM(x)")])
    c2 = make_catalog(name="ModB", measures=[("Sales", "SUM(x)")])
    assert not _run_estate("coop_dax_review.rules.dax_estate_measure_drift", [c1, c2])


# -- DAX-ESTATE-FORMAT-DRIFT ------------------------------------------------


def test_estate_format_drift_fires(make_catalog):
    c1 = make_catalog(name="ModA")
    c1.measures.append(type("Measure", (), {"name": "Sales", "format_string": "0"})())
    c2 = make_catalog(name="ModB")
    c2.measures.append(type("Measure", (), {"name": "Sales", "format_string": "0.00"})())
    res = _run_estate("coop_dax_review.rules.dax_estate_format_drift", [c1, c2])
    assert len(res) == 1
    assert "ModA <> ModB" in res[0].model


def test_estate_format_drift_compliant(make_catalog):
    c1 = make_catalog(name="ModA")
    c1.measures.append(type("Measure", (), {"name": "Sales", "format_string": "0"})())
    c2 = make_catalog(name="ModB")
    c2.measures.append(type("Measure", (), {"name": "Sales", "format_string": "0"})())
    assert not _run_estate("coop_dax_review.rules.dax_estate_format_drift", [c1, c2])
