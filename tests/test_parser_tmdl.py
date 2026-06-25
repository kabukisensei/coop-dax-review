"""TMDL parsing into a catalog: measure boundaries, line numbers, model metadata."""

import json

from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import model_root, parse_tmdl_model

TABLE_TMDL = """table FactSales
\tcolumn Revenue
\t\tdataType: double
\tcolumn Margin = FactSales[Revenue] * 0.1
\t\tdataType: double

\tmeasure 'Sales: Total Revenue' = SUM(FactSales[Revenue])

\tmeasure 'Sales: YTD' =
\t\tCALCULATE(
\t\t\t[Sales: Total Revenue],
\t\t\tDATESYTD(DimDate[Date])
\t\t)

\tpartition FactSales = m
\t\tmode: directLake
\t\tsource = "x"
"""

MODEL_TMDL = """model Sales

relationship abc
\tfromColumn: FactSales.ProductId
\ttoColumn: DimProduct.ProductId
\tcrossFilteringBehavior: bothDirections
\tisActive: false
"""


def test_measures_have_correct_boundaries_and_lines():
    cat = parse_tmdl_model("Sales", {"tables/FactSales.tmdl": TABLE_TMDL})
    names = {m.name: m for m in cat.measures}
    assert set(names) == {"Sales: Total Revenue", "Sales: YTD"}
    # The inline measure does not swallow the next measure's DAX.
    assert names["Sales: Total Revenue"].dax == "SUM(FactSales[Revenue])"
    assert "CALCULATE" in names["Sales: YTD"].dax
    assert names["Sales: YTD"].line == 9  # 1-based declaration line


def test_columns_calculated_and_storage_mode():
    cat = parse_tmdl_model("Sales", {"f.tmdl": TABLE_TMDL})
    table = cat.tables[0]
    cols = {c.name: c for c in table.columns}
    assert cols["Revenue"].is_calculated is False
    assert cols["Margin"].is_calculated is True
    assert table.storage_mode == "directLake"
    assert cat.storage_mode == "directLake"


def test_relationship_crossfilter_and_active():
    cat = parse_tmdl_model("Sales", {"model.tmdl": MODEL_TMDL})
    assert len(cat.relationships) == 1
    rel = cat.relationships[0]
    assert (rel.from_table, rel.from_column) == ("FactSales", "ProductId")
    assert (rel.to_table, rel.to_column) == ("DimProduct", "ProductId")
    assert rel.cross_filter == "both"
    assert rel.is_active is False


def test_date_table_detected_via_data_category():
    tmdl = "table DimDate\n\tcolumn Date\n\t\tdataType: dateTime\n\t\tdataCategory: Time\n"
    cat = parse_tmdl_model("M", {"d.tmdl": tmdl})
    assert cat.date_table == "DimDate"


def test_bim_crossfilter_is_case_insensitive():
    # .bim must match the TMDL parser's case-insensitive compare:
    # any casing of "bothDirections" is "both".
    bim = json.dumps(
        {
            "name": "M",
            "model": {
                "tables": [{"name": "FactSales", "columns": [{"name": "ProductId"}]}],
                "relationships": [
                    {
                        "fromTable": "FactSales",
                        "fromColumn": "ProductId",
                        "toTable": "DimProduct",
                        "toColumn": "ProductId",
                        "crossFilteringBehavior": "BothDirections",
                    }
                ],
            },
        }
    )
    cat = parse_bim_model("model.bim", bim)
    assert len(cat.relationships) == 1
    assert cat.relationships[0].cross_filter == "both"


def test_model_root_resolves_semantic_model_name():
    root, name = model_root("repo/Sales.SemanticModel/definition/tables/x.tmdl")
    assert name == "Sales"
    assert root.endswith("Sales.SemanticModel")
