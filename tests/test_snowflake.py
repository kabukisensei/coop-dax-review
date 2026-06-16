from importlib import import_module

from coop_dax_review.model import ModelCatalog, Relationship, Table
from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_snowflake")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def _rel(from_table, from_column, to_table, to_column):
    return Relationship(
        from_table=from_table,
        from_column=from_column,
        to_table=to_table,
        to_column=to_column,
    )


def test_fires_on_snowflake_chain(make_catalog):
    # FactSales -> DimProduct -> DimCategory: DimProduct is the intermediate
    # (many-side to DimCategory, one-side from FactSales).
    cat = make_catalog(
        tables=[
            ("FactSales", ["ProductId"]),
            ("DimProduct", ["ProductId", "CategoryId"]),
            ("DimCategory", ["CategoryId"]),
        ],
        relationships=[
            dict(
                from_table="FactSales", from_column="ProductId", to_table="DimProduct", to_column="ProductId"
            ),
            dict(
                from_table="DimProduct",
                from_column="CategoryId",
                to_table="DimCategory",
                to_column="CategoryId",
            ),
        ],
    )
    findings = _run(cat)
    assert [f.object for f in findings] == ["DimProduct"]
    assert findings[0].rule_id == "DAX-SNOWFLAKE"
    assert findings[0].severity == "info"
    assert findings[0].standard_ref == "§6"


def test_silent_on_pure_star(make_catalog):
    # Fact -> two dims, no dim -> dim. This mirrors the §6 "Good" shape:
    # flat dimensions related directly to the fact.
    cat = make_catalog(
        tables=[
            ("FactSales", ["ProductId", "CustomerId"]),
            ("DimProduct", ["ProductId"]),
            ("DimCustomer", ["CustomerId"]),
        ],
        relationships=[
            dict(
                from_table="FactSales", from_column="ProductId", to_table="DimProduct", to_column="ProductId"
            ),
            dict(
                from_table="FactSales",
                from_column="CustomerId",
                to_table="DimCustomer",
                to_column="CustomerId",
            ),
        ],
    )
    assert _run(cat) == []


def test_no_relationships_silent(make_catalog):
    cat = make_catalog(tables=[("FactSales", ["Amount"])])
    assert _run(cat) == []


def test_multiple_intermediates_each_flagged(make_catalog):
    # Fact -> A -> B -> C: both A and B are intermediates, C is a leaf.
    cat = make_catalog(
        tables=[
            ("FactSales", ["AKey"]),
            ("DimA", ["AKey", "BKey"]),
            ("DimB", ["BKey", "CKey"]),
            ("DimC", ["CKey"]),
        ],
        relationships=[
            dict(from_table="FactSales", from_column="AKey", to_table="DimA", to_column="AKey"),
            dict(from_table="DimA", from_column="BKey", to_table="DimB", to_column="BKey"),
            dict(from_table="DimB", from_column="CKey", to_table="DimC", to_column="CKey"),
        ],
    )
    assert sorted(f.object for f in _run(cat)) == ["DimA", "DimB"]


def test_self_relationship_not_a_chain():
    # A parent/child self-relationship must not be treated as a snowflake.
    cat = ModelCatalog(name="Test", file="Test.tmdl")
    cat.tables.append(Table(name="DimEmployee", file="Test.tmdl", line=5))
    cat.relationships.append(
        Relationship(
            from_table="DimEmployee",
            from_column="ManagerId",
            to_table="DimEmployee",
            to_column="EmployeeId",
        )
    )
    assert _run(cat) == []


def test_finding_points_to_table_file_and_line():
    cat = ModelCatalog(name="Test", file="model.tmdl")
    cat.tables.append(Table(name="FactSales", file="model.tmdl", line=1))
    cat.tables.append(Table(name="DimProduct", file="product.tmdl", line=42))
    cat.tables.append(Table(name="DimCategory", file="category.tmdl", line=3))
    cat.relationships.append(_rel("FactSales", "ProductId", "DimProduct", "ProductId"))
    cat.relationships.append(_rel("DimProduct", "CategoryId", "DimCategory", "CategoryId"))
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].file == "product.tmdl"
    assert findings[0].line == 42
