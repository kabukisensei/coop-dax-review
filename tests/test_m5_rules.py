"""Tests for the M5 best-practice rules (§14 DIVIDE, §15 format string, §16 float keys)."""

from importlib import import_module

from coop_dax_review.model import Column, Measure, ModelCatalog, Relationship, Table
from coop_dax_review.rules.base import RuleContext


def _run(module, cat):
    mod = import_module(f"coop_dax_review.rules.{module}")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# -- DAX-USE-DIVIDE (§14) ----------------------------------------------------


def test_divide_operator_fires(make_catalog):
    cat = make_catalog(measures=[("Sales: Margin %", "[Sales: Profit] / [Sales: Revenue]")])
    findings = _run("dax_use_divide", cat)
    assert len(findings) == 1


def test_divide_function_is_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Margin %", "DIVIDE([Sales: Profit], [Sales: Revenue])")])
    assert _run("dax_use_divide", cat) == []


def test_slash_in_comment_or_string_is_ignored(make_catalog):
    cat = make_catalog(measures=[("Sales: M", '-- ratio a/b\nVAR note = "n/a"\nRETURN DIVIDE([a], [b])')])
    assert _run("dax_use_divide", cat) == []


def test_slash_inside_bracketed_identifier_is_ignored(make_catalog):
    # A column/measure named with a slash must not count as a division operator.
    cat = make_catalog(measures=[("Sales: M", "SUM(Sales[Net/Gross]) + [Win/Loss Ratio]")])
    assert _run("dax_use_divide", cat) == []


# -- issue #5: calc columns + calc tables are linted by §14 / §3 -------------


def _calc_col_catalog(expr: str) -> ModelCatalog:
    return ModelCatalog(
        name="M",
        tables=[
            Table(
                name="Fact",
                file="f.tmdl",
                columns=[Column(name="Ratio", is_calculated=True, expression=expr, line=5)],
            )
        ],
    )


def _calc_table_catalog(expr: str) -> ModelCatalog:
    return ModelCatalog(
        name="M", tables=[Table(name="Calc", file="f.tmdl", is_calculated=True, expression=expr, line=1)]
    )


def test_divide_fires_on_calculated_column():
    (f,) = _run("dax_use_divide", _calc_col_catalog("[Rev] / [Cost]"))
    assert f.object == "Fact[Ratio]" and f.line == 5


def test_divide_fires_on_calculated_table():
    (f,) = _run("dax_use_divide", _calc_table_catalog("FILTER(Sales, Sales[Amt] / 0 > 1)"))
    assert f.object == "Calc" and f.line == 1


def test_divide_calc_column_compliant_silent():
    assert _run("dax_use_divide", _calc_col_catalog("DIVIDE([Rev], [Cost])")) == []


def test_divide_ignores_a_plain_data_column():
    # a non-calculated column has no DAX to lint even if given a stray expression.
    cat = ModelCatalog(
        name="M",
        tables=[Table(name="Fact", columns=[Column(name="Amt", is_calculated=False, expression="a / b")])],
    )
    assert _run("dax_use_divide", cat) == []


def test_nested_calculate_fires_on_calculated_column():
    (f,) = _run("dax_no_nested_calculate", _calc_col_catalog("CALCULATE(CALCULATE([M]))"))
    assert f.object == "Fact[Ratio]"


def test_nested_calculate_fires_on_calculated_table():
    (f,) = _run("dax_no_nested_calculate", _calc_table_catalog("CALCULATETABLE(CALCULATETABLE(Sales))"))
    assert f.object == "Calc"


def test_nested_calculate_calc_column_compliant_silent():
    assert _run("dax_no_nested_calculate", _calc_col_catalog("CALCULATE([M])")) == []


# -- DAX-FORMAT-STRING (§15) -------------------------------------------------


def test_measure_without_format_string_fires():
    cat = ModelCatalog(name="M", measures=[Measure(name="Sales: Rev", dax="1", format_string="")])
    assert len(_run("dax_format_string", cat)) == 1


def test_measure_with_format_string_silent():
    cat = ModelCatalog(name="M", measures=[Measure(name="Sales: Rev", dax="1", format_string="0.00")])
    assert _run("dax_format_string", cat) == []


def test_dynamic_format_string_silent():
    cat = ModelCatalog(name="M", measures=[Measure(name="Sales: Rev", dax="1", format_string="<dynamic>")])
    assert _run("dax_format_string", cat) == []


def test_hidden_measure_without_format_string_silent():
    # issue #7: a hidden measure is never rendered, so no formatString is needed.
    cat = ModelCatalog(
        name="M", measures=[Measure(name="Sales: _Helper", dax="1", format_string="", is_hidden=True)]
    )
    assert _run("dax_format_string", cat) == []


# -- DAX-NO-FLOAT-KEYS (§16) -------------------------------------------------


def _rel_catalog(from_type: str, to_type: str) -> ModelCatalog:
    return ModelCatalog(
        name="M",
        tables=[
            Table(
                name="Fact",
                file="tables/Fact.tmdl",
                columns=[Column(name="CustKey", data_type=from_type, line=7)],
            ),
            Table(name="DimCustomer", columns=[Column(name="CustomerKey", data_type=to_type)]),
        ],
        relationships=[
            Relationship(
                from_table="Fact",
                from_column="CustKey",
                to_table="DimCustomer",
                to_column="CustomerKey",
                file="relationships.tmdl",
                line=99,
            )
        ],
    )


def test_double_relationship_key_fires():
    findings = _run("dax_no_float_keys", _rel_catalog("double", "int64"))
    assert len(findings) == 1
    assert "Fact[CustKey]" in findings[0].object


def test_float_key_finding_points_at_the_column_not_the_relationship():
    # issue #6: the finding must land on the column definition (where the dataType
    # fix is made), like the sibling §17/§18 rules — not the relationships file.
    (finding,) = _run("dax_no_float_keys", _rel_catalog("double", "int64"))
    assert finding.file == "tables/Fact.tmdl"  # the column's file, not "relationships.tmdl"
    assert finding.line == 7  # the column's line, not the relationship's line 99


def test_both_double_endpoints_each_fire():
    assert len(_run("dax_no_float_keys", _rel_catalog("double", "double"))) == 2


def test_integer_keys_silent():
    assert _run("dax_no_float_keys", _rel_catalog("int64", "int64")) == []
