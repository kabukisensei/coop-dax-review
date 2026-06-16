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


# -- DAX-NO-FLOAT-KEYS (§16) -------------------------------------------------


def _rel_catalog(from_type: str, to_type: str) -> ModelCatalog:
    return ModelCatalog(
        name="M",
        tables=[
            Table(name="Fact", columns=[Column(name="CustKey", data_type=from_type)]),
            Table(name="DimCustomer", columns=[Column(name="CustomerKey", data_type=to_type)]),
        ],
        relationships=[
            Relationship(
                from_table="Fact", from_column="CustKey", to_table="DimCustomer", to_column="CustomerKey"
            )
        ],
    )


def test_double_relationship_key_fires():
    findings = _run("dax_no_float_keys", _rel_catalog("double", "int64"))
    assert len(findings) == 1
    assert "Fact[CustKey]" in findings[0].object


def test_both_double_endpoints_each_fire():
    assert len(_run("dax_no_float_keys", _rel_catalog("double", "double"))) == 2


def test_integer_keys_silent():
    assert _run("dax_no_float_keys", _rel_catalog("int64", "int64")) == []
