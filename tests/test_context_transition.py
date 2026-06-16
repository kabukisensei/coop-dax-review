"""Tests for DAX-CONTEXT-TRANSITION (§9, agent)."""

from importlib import import_module

from coop_dax_review.model import Measure, ModelCatalog
from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_context_transition")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# The §9 "Caution" example: a measure ref inside AVERAGEX (implicit CALCULATE).
CAUTION = "AVERAGEX(\n    VALUES(DimCustomer[CustomerId]),\n    [Sales: Total Revenue]\n)"


def test_is_agent_rule():
    mod = import_module("coop_dax_review.rules.dax_context_transition")
    assert mod.RULE.kind == "agent"
    assert mod.RULE.severity == "info"
    assert mod.RULE.category == "context-transition"
    assert mod.RULE.tier == 2


def test_fires_on_measure_ref_in_iterator(make_catalog):
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Average Customer Revenue", CAUTION),
        ]
    )
    items = _run(cat)
    assert [i.object for i in items] == ["[Sales: Average Customer Revenue]"]
    assert items[0].standard_ref == "§9"


def test_one_item_per_measure_not_per_ref(make_catalog):
    # Two iterators, each with a measure ref -> still ONE item for the measure.
    dax = (
        "SUMX(VALUES(Dim[Id]), [Sales: Total Revenue])\n"
        "    + AVERAGEX(VALUES(Dim[Id]), [Sales: Total Revenue])"
    )
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Combo", dax),
        ]
    )
    items = _run(cat)
    assert len(items) == 1
    assert items[0].object == "[Sales: Combo]"


def test_line_points_at_iterator(make_catalog):
    # AVERAGEX sits on line 2 of the body; the body starts on dax_line.
    dax = "VAR X = 1\nRETURN AVERAGEX(VALUES(Dim[Id]), [Sales: Total Revenue])"
    cat = ModelCatalog(name="T", file="T.tmdl")
    cat.measures.append(
        Measure(name="Sales: Total Revenue", dax="SUM(F[R])", table="", file="T.tmdl", line=1)
    )
    cat.measures.append(Measure(name="M", dax=dax, table="", file="T.tmdl", line=10, dax_line=10))
    items = _run(cat)
    assert len(items) == 1
    # AVERAGEX is on the second line of the body -> line 11.
    assert items[0].line == 11


def test_silent_no_iterator(make_catalog):
    # Measure ref inside CALCULATE (no row iterator) -> no context-transition item.
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: YTD", "CALCULATE([Sales: Total Revenue], DATESYTD(DimDate[Date]))"),
        ]
    )
    assert _run(cat) == []


def test_silent_iterator_over_column_only(make_catalog):
    # SUMX over a column expression, no measure reference inside -> silent.
    cat = make_catalog(
        measures=[("Sales: Total Revenue", "SUMX(FactSales, FactSales[Qty] * FactSales[Price])")]
    )
    assert _run(cat) == []


def test_silent_when_bracket_is_a_column(make_catalog):
    # A qualified column ref inside the iterator is not a measure ref -> silent.
    cat = make_catalog(
        measures=[("Sales: X", "SUMX(VALUES(Dim[Id]), DimCustomer[CustomerId])")],
        tables=[("DimCustomer", ["CustomerId"]), ("Dim", ["Id"])],
    )
    assert _run(cat) == []


def test_silent_when_ref_is_not_a_known_measure(make_catalog):
    # Bare [Amount] resolves to a same-table column, not a measure -> silent.
    cat = make_catalog(
        measures=[("Sales: X", "SUMX(FactSales, [Amount])")],
        tables=[("FactSales", ["Amount"])],
    )
    assert _run(cat) == []


def test_measure_ref_in_string_or_comment_does_not_fire(make_catalog):
    # The bare measure ref only appears inside a comment / string -> masked out.
    dax = "SUMX(FactSales, FactSales[Qty]) -- not [Sales: Total Revenue] here"
    cat = make_catalog(
        measures=[
            ("Sales: Total Revenue", "SUM(FactSales[Revenue])"),
            ("Sales: Qty", dax),
        ]
    )
    assert _run(cat) == []
