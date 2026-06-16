"""DAX-STAR-SCHEMA (§6): one agent-review item per snowflake intermediate."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_star_schema")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def _rel(ft, fc, tt, tc):
    return dict(from_table=ft, from_column=fc, to_table=tt, to_column=tc)


def test_snowflake_intermediate_flagged(make_catalog):
    # Fact -> DimProduct -> DimCategory : DimProduct is the snowflake link.
    cat = make_catalog(
        tables=[
            ("FactSales", ["ProductId", "Revenue"]),
            ("DimProduct", ["ProductId", "CategoryId"]),
            ("DimCategory", ["CategoryId", "Name"]),
        ],
        relationships=[
            _rel("FactSales", "ProductId", "DimProduct", "ProductId"),
            _rel("DimProduct", "CategoryId", "DimCategory", "CategoryId"),
        ],
    )
    items = _run(cat)
    assert [i.object for i in items] == ["DimProduct"]
    assert items[0].rule_id == "DAX-STAR-SCHEMA"
    assert items[0].standard_ref == "§6"
    assert items[0].file == cat.file
    assert "§6" in items[0].note


def test_pure_star_silent(make_catalog):
    # Every dimension hangs directly off the fact — no intermediates.
    cat = make_catalog(
        tables=[
            ("FactSales", ["ProductId", "DateKey", "Revenue"]),
            ("DimProduct", ["ProductId", "Name"]),
            ("DimDate", ["DateKey", "Date"]),
        ],
        relationships=[
            _rel("FactSales", "ProductId", "DimProduct", "ProductId"),
            _rel("FactSales", "DateKey", "DimDate", "DateKey"),
        ],
    )
    assert _run(cat) == []


def test_no_relationships_silent(make_catalog):
    # The §6 "Good" shape: flat denormalized dimensions, nothing to flatten.
    cat = make_catalog(
        tables=[("FactSales", ["Revenue"]), ("DimProduct", ["ProductId", "CategoryName"])],
    )
    assert _run(cat) == []


def test_multiple_intermediates(make_catalog):
    # Fact -> DimProduct -> DimCategory -> DimDepartment : two intermediates.
    cat = make_catalog(
        tables=[
            ("FactSales", ["ProductId"]),
            ("DimProduct", ["ProductId", "CategoryId"]),
            ("DimCategory", ["CategoryId", "DeptId"]),
            ("DimDepartment", ["DeptId", "Name"]),
        ],
        relationships=[
            _rel("FactSales", "ProductId", "DimProduct", "ProductId"),
            _rel("DimProduct", "CategoryId", "DimCategory", "CategoryId"),
            _rel("DimCategory", "DeptId", "DimDepartment", "DeptId"),
        ],
    )
    items = _run(cat)
    assert sorted(i.object for i in items) == ["DimCategory", "DimProduct"]
