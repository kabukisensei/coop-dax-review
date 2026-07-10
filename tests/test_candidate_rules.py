"""Tests for the issue #19 candidate rules (§22-§25): DAX-EARLIER-TO-VAR,
DAX-DEAD-INACTIVE-RELATIONSHIP, DAX-IFERROR-WRAPPING, DAX-MEASURE-DESCRIPTION."""

from importlib import import_module

from coop_dax_review.model import CalculationItem, Column, Measure, ModelCatalog, Relationship, Table
from coop_dax_review.rules.base import RuleContext


def _run(module, cat):
    mod = import_module(f"coop_dax_review.rules.{module}")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# -- DAX-EARLIER-TO-VAR (§22) --------------------------------------------------


def test_earlier_fires_in_measure(make_catalog):
    dax = "SUMX(FILTER(ALL(FactSales), FactSales[Date] <= EARLIER(FactSales[Date])), FactSales[Rev])"
    cat = make_catalog(measures=[("Sales: Running", dax)])
    findings = _run("dax_earlier_to_var", cat)
    assert len(findings) == 1
    assert "EARLIER()" in findings[0].message
    assert findings[0].standard_ref == "§22"


def test_earliest_fires_too(make_catalog):
    cat = make_catalog(measures=[("Sales: M", "COUNTROWS(FILTER(T, T[A] = EARLIEST(T[A])))")])
    findings = _run("dax_earlier_to_var", cat)
    assert len(findings) == 1
    assert "EARLIEST()" in findings[0].message


def test_earlier_fires_in_calculated_column():
    cat = ModelCatalog(
        name="M",
        tables=[
            Table(
                name="Fact",
                file="f.tmdl",
                columns=[
                    Column(
                        name="Running",
                        is_calculated=True,
                        expression="CALCULATE(SUM(Fact[Rev]), FILTER(Fact, Fact[D] <= EARLIER(Fact[D])))",
                        line=4,
                    )
                ],
            )
        ],
    )
    (finding,) = _run("dax_earlier_to_var", cat)
    assert finding.object == "Fact[Running]"


def test_var_capture_compliant_silent(make_catalog):
    # §22 Good: the VAR-captured form must stay clean.
    dax = (
        "VAR CurrentDate = FactSales[OrderDate]\n"
        "RETURN CALCULATE(SUM(FactSales[Revenue]), "
        "FILTER(ALL(FactSales), FactSales[OrderDate] <= CurrentDate))"
    )
    cat = make_catalog(measures=[("Sales: Running", dax)])
    assert _run("dax_earlier_to_var", cat) == []


def test_earlier_in_comment_or_identifier_silent(make_catalog):
    dax = "-- consider EARLIER(x) here?\nSUM(Sales[Earlier]) + [Earlier Total]"
    cat = make_catalog(measures=[("Sales: M", dax)])
    assert _run("dax_earlier_to_var", cat) == []


# -- DAX-DEAD-INACTIVE-RELATIONSHIP (§23) ---------------------------------------


_REL = dict(
    from_table="FactSales",
    from_column="ShipDate",
    to_table="DimDate",
    to_column="Date",
    is_active=False,
)


def test_unused_inactive_relationship_fires(make_catalog):
    cat = make_catalog(
        measures=[("Sales: Total", "SUM(FactSales[Revenue])")],
        relationships=[dict(_REL)],
    )
    findings = _run("dax_dead_inactive_relationship", cat)
    assert len(findings) == 1
    assert findings[0].object == "FactSales[ShipDate] -> DimDate[Date]"
    assert "USERELATIONSHIP" in findings[0].message


def test_used_inactive_relationship_silent(make_catalog):
    dax = "CALCULATE([Sales: Total], USERELATIONSHIP(FactSales[ShipDate], DimDate[Date]))"
    cat = make_catalog(measures=[("Sales: By Ship", dax)], relationships=[dict(_REL)])
    assert _run("dax_dead_inactive_relationship", cat) == []


def test_used_inactive_relationship_reversed_args_silent(make_catalog):
    # USERELATIONSHIP argument order is free — either order keeps it alive.
    dax = "CALCULATE([Sales: Total], USERELATIONSHIP(DimDate[Date], FactSales[ShipDate]))"
    cat = make_catalog(measures=[("Sales: By Ship", dax)], relationships=[dict(_REL)])
    assert _run("dax_dead_inactive_relationship", cat) == []


def test_userelationship_on_other_columns_does_not_keep_alive(make_catalog):
    # A USERELATIONSHIP naming a DIFFERENT endpoint pair must not save this one.
    dax = "CALCULATE([Sales: Total], USERELATIONSHIP(FactSales[DueDate], DimDate[Date]))"
    cat = make_catalog(measures=[("Sales: By Due", dax)], relationships=[dict(_REL)])
    assert len(_run("dax_dead_inactive_relationship", cat)) == 1


def test_active_relationship_never_flagged(make_catalog):
    rel = dict(_REL, is_active=True)
    cat = make_catalog(measures=[("Sales: Total", "SUM(FactSales[Revenue])")], relationships=[rel])
    assert _run("dax_dead_inactive_relationship", cat) == []


def test_userelationship_in_comment_does_not_keep_alive(make_catalog):
    dax = "-- USERELATIONSHIP(FactSales[ShipDate], DimDate[Date])\nSUM(FactSales[Revenue])"
    cat = make_catalog(measures=[("Sales: Total", dax)], relationships=[dict(_REL)])
    assert len(_run("dax_dead_inactive_relationship", cat)) == 1


def test_userelationship_in_calculation_item_keeps_alive():
    cat = ModelCatalog(
        name="M",
        relationships=[Relationship(**_REL)],
        tables=[Table(name="TI", file="ti.tmdl")],
        calculation_items=[
            CalculationItem(
                name="Ship",
                dax="CALCULATE(SELECTEDMEASURE(), USERELATIONSHIP(FactSales[ShipDate], DimDate[Date]))",
                table="TI",
            )
        ],
    )
    assert _run("dax_dead_inactive_relationship", cat) == []


def test_quoted_table_in_userelationship_matches(make_catalog):
    rel = dict(_REL, from_table="Fact Sales")
    dax = "CALCULATE([m], USERELATIONSHIP('Fact Sales'[ShipDate], DimDate[Date]))"
    cat = make_catalog(measures=[("Sales: By Ship", dax)], relationships=[rel])
    assert _run("dax_dead_inactive_relationship", cat) == []


# -- DAX-IFERROR-WRAPPING (§24) --------------------------------------------------


def test_iferror_around_division_fires(make_catalog):
    cat = make_catalog(measures=[("Sales: Margin %", "IFERROR([Sales: Profit] / [Sales: Revenue], BLANK())")])
    findings = _run("dax_iferror_wrapping", cat)
    assert len(findings) == 1
    assert "DIVIDE" in findings[0].message
    assert findings[0].standard_ref == "§24"


def test_iferror_around_other_arithmetic_fires(make_catalog):
    cat = make_catalog(measures=[("Sales: M", "IFERROR(SUM(T[A]) * SUM(T[B]), 0)")])
    assert len(_run("dax_iferror_wrapping", cat)) == 1


def test_iferror_guarding_conversion_silent(make_catalog):
    # A genuine error source with no arithmetic is a legitimate guard.
    cat = make_catalog(measures=[("Sales: Code", "IFERROR(VALUE(Sales[Code]), BLANK())")])
    assert _run("dax_iferror_wrapping", cat) == []


def test_divide_compliant_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Margin %", "DIVIDE([Sales: Profit], [Sales: Revenue])")])
    assert _run("dax_iferror_wrapping", cat) == []


def test_arithmetic_in_second_argument_only_silent(make_catalog):
    # Only the WRAPPED (first) argument matters; an arithmetic alternate is fine.
    cat = make_catalog(measures=[("Sales: M", "IFERROR(VALUE(Sales[Code]), 1 + 2)")])
    assert _run("dax_iferror_wrapping", cat) == []


def test_operator_inside_identifier_or_string_silent(make_catalog):
    dax = 'IFERROR(VALUE(Sales[Net-Gross]), "n/a")'
    cat = make_catalog(measures=[("Sales: M", dax)])
    assert _run("dax_iferror_wrapping", cat) == []


def test_iferror_fires_on_calculated_column():
    cat = ModelCatalog(
        name="M",
        tables=[
            Table(
                name="Fact",
                file="f.tmdl",
                columns=[Column(name="R", is_calculated=True, expression="IFERROR([A] / [B], 0)", line=3)],
            )
        ],
    )
    (finding,) = _run("dax_iferror_wrapping", cat)
    assert finding.object == "Fact[R]"


# -- DAX-MEASURE-DESCRIPTION (§25) -------------------------------------------------


def _measure(name, *, description="", is_hidden=False, table="Fact"):
    return Measure(name=name, dax="1", table=table, file="f.tmdl", line=1, description=description)


def test_visible_measure_without_description_fires():
    cat = ModelCatalog(name="M", measures=[_measure("Sales: Revenue")])
    findings = _run("dax_measure_description", cat)
    assert len(findings) == 1
    assert findings[0].object == "[Sales: Revenue]"
    assert findings[0].severity == "info"
    assert findings[0].standard_ref == "§25"


def test_described_measure_silent():
    cat = ModelCatalog(
        name="M", measures=[_measure("Sales: Revenue", description="Total revenue before returns.")]
    )
    assert _run("dax_measure_description", cat) == []


def test_hidden_measure_exempt():
    m = _measure("Sales: _Helper")
    m.is_hidden = True
    cat = ModelCatalog(name="M", measures=[m])
    assert _run("dax_measure_description", cat) == []


def test_measure_on_hidden_table_exempt():
    cat = ModelCatalog(
        name="M",
        tables=[Table(name="Fact", is_hidden=True)],
        measures=[_measure("Sales: Revenue", table="Fact")],
    )
    assert _run("dax_measure_description", cat) == []


def test_whitespace_description_still_fires():
    cat = ModelCatalog(name="M", measures=[_measure("Sales: Revenue", description="   ")])
    assert len(_run("dax_measure_description", cat)) == 1
