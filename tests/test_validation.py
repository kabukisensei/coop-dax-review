from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_validation")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def test_is_agent_rule():
    mod = import_module("coop_dax_review.rules.dax_validation")
    assert mod.RULE.kind == "agent"
    assert mod.RULE.severity == "info"
    assert mod.RULE.category == "validation"


def test_time_intel_fires_one_model_item(make_catalog):
    cat = make_catalog(
        measures=[
            (
                "Sales: Revenue YTD",
                "CALCULATE([Sales: Total Revenue], DATESYTD(DimDate[Date]))",
            )
        ]
    )
    items = _run(cat)
    # issue #16: ONE model-level item (object = model name), naming the measure.
    assert [i.object for i in items] == ["Test"]
    assert "1 non-trivial measure " in items[0].note
    assert "[Sales: Revenue YTD]" in items[0].note


def test_calculate_fires(make_catalog):
    cat = make_catalog(
        measures=[
            (
                "Sales: Enterprise Revenue",
                'CALCULATE([Sales: Total Revenue], DimCustomer[MarketSegment] = "Enterprise")',
            )
        ]
    )
    items = _run(cat)
    assert len(items) == 1
    assert items[0].standard_ref == "§11"


def test_two_vars_fires(make_catalog):
    dax = "VAR A = SUM(FactSales[Revenue])\nVAR B = SUM(FactSales[Cost])\nRETURN A - B"
    cat = make_catalog(measures=[("Sales: Margin", dax)])
    items = _run(cat)
    assert len(items) == 1


def test_plain_sum_silent(make_catalog):
    # The trivial aggregation must NOT produce an item.
    cat = make_catalog(measures=[("Sales: Total Revenue", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_single_var_trivial_silent(make_catalog):
    # One VAR, no CALCULATE / time-intel -> still trivial.
    dax = "VAR R = SUM(FactSales[Revenue])\nRETURN R"
    cat = make_catalog(measures=[("Sales: Revenue", dax)])
    assert _run(cat) == []


def test_many_measures_collapse_to_one_item(make_catalog):
    # issue #16: N qualifying measures -> ONE item carrying the count and the
    # first few names (ellipsized) — never one item per measure.
    calc = "CALCULATE([Sales: Total Revenue], TRUE())"
    cat = make_catalog(
        measures=[
            ("Sales: A", calc),
            ("Sales: B", calc),
            ("Sales: C", calc),
            ("Sales: D", calc),
            ("Sales: Trivial", "SUM(FactSales[Revenue])"),
        ]
    )
    items = _run(cat)
    assert len(items) == 1
    note = items[0].note
    assert "4 non-trivial measures" in note
    assert "[Sales: A], [Sales: B], [Sales: C], ..." in note
    assert "[Sales: D]" not in note  # only the first few are named


def test_keyword_in_comment_silent(make_catalog):
    # CALCULATE only appears in a comment -> masked out -> trivial -> silent.
    dax = "-- could use CALCULATE here later\nSUM(FactSales[Revenue])"
    cat = make_catalog(measures=[("Sales: Total Revenue", dax)])
    assert _run(cat) == []


def test_model_level_file_and_line(make_catalog):
    # The single item is model-level: the model's primary file, no line anchor.
    cat = make_catalog(measures=[("M", "CALCULATE(SUM(FactSales[Revenue]), TRUE())")])
    item = _run(cat)[0]
    assert item.line == 0
    assert item.file == cat.file
