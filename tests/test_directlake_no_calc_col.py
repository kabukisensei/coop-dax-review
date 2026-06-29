"""Tests for DAX-DIRECTLAKE-NO-CALC-COL (§13)."""

from importlib import import_module

from coop_dax_review.model import Column, ModelCatalog, Table
from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_directlake_no_calc_col")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def _cat(*tables):
    return ModelCatalog(name="Test", file="Test.tmdl", tables=list(tables))


def test_fires_on_directlake_calc_column(make_catalog):
    # Bad: a Direct Lake table carrying a calculated column.
    table = Table(
        name="FactSales",
        file="FactSales.tmdl",
        storage_mode="directLake",
        columns=[
            Column(name="Revenue", line=10),
            Column(name="RevenueWithTax", line=20, is_calculated=True, expression="FactSales[Revenue] * 1.1"),
        ],
    )
    findings = _run(_cat(table))
    assert len(findings) == 1
    f = findings[0]
    assert f.object == "FactSales[RevenueWithTax]"
    assert f.file == "FactSales.tmdl"
    assert f.line == 20
    assert "§13" in f.message
    assert f.severity == "warning"
    assert f.rule_id == "DAX-DIRECTLAKE-NO-CALC-COL"


def test_fires_when_model_is_directlake_even_if_table_mode_blank():
    # Model resolves to directLake (one DL table), so a calc column on another
    # table without an explicit mode still fires.
    dl = Table(name="FactSales", storage_mode="directLake", columns=[Column(name="Revenue")])
    dim = Table(
        name="DimCustomer",
        file="DimCustomer.tmdl",
        storage_mode="",
        columns=[Column(name="FullName", line=7, is_calculated=True, expression="[First] & [Last]")],
    )
    findings = _run(_cat(dl, dim))
    assert len(findings) == 1
    assert findings[0].object == "DimCustomer[FullName]"
    assert findings[0].line == 7


def test_composite_explicit_import_table_not_flagged():
    # Composite model: one Direct Lake table plus an explicit import-mode table
    # carrying a calculated column. Calculated columns are supported on the
    # non-DL table, so it must NOT fire (only blank/unknown modes inherit the
    # model-level DL fallback).
    dl = Table(name="FactSales", storage_mode="directLake", columns=[Column(name="Revenue")])
    imp = Table(
        name="DimImport",
        storage_mode="import",
        columns=[Column(name="CalcCol", line=5, is_calculated=True)],
    )
    assert _run(_cat(dl, imp)) == []


def test_composite_explicit_dual_table_not_flagged():
    dl = Table(name="FactSales", storage_mode="directLake", columns=[Column(name="Revenue")])
    dual = Table(
        name="DimDual",
        storage_mode="dual",
        columns=[Column(name="CalcCol", line=5, is_calculated=True)],
    )
    assert _run(_cat(dl, dual)) == []


def test_multiple_calc_columns_one_finding_each():
    table = Table(
        name="FactSales",
        storage_mode="directLake",
        columns=[
            Column(name="A", line=1, is_calculated=True),
            Column(name="B", line=2, is_calculated=True),
            Column(name="C", line=3),  # regular column, not flagged
        ],
    )
    findings = _run(_cat(table))
    assert {f.object for f in findings} == {"FactSales[A]", "FactSales[B]"}


def test_import_model_with_calc_columns_silent():
    # Import-mode model with calculated columns -> no findings.
    table = Table(
        name="FactSales",
        storage_mode="import",
        columns=[Column(name="RevenueWithTax", line=20, is_calculated=True)],
    )
    findings = _run(_cat(table))
    assert findings == []


def test_directlake_only_regular_columns_silent():
    # Direct Lake model with no calculated columns -> no findings.
    table = Table(
        name="FactSales",
        storage_mode="directLake",
        columns=[Column(name="Revenue"), Column(name="Quantity")],
    )
    findings = _run(_cat(table))
    assert findings == []


def test_unknown_storage_mode_silent():
    # No storage mode anywhere (model resolves to "") -> rule does not apply.
    table = Table(
        name="FactSales",
        storage_mode="",
        columns=[Column(name="RevenueWithTax", is_calculated=True)],
    )
    findings = _run(_cat(table))
    assert findings == []
