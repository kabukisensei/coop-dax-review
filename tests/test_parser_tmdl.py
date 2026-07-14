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


def test_measure_is_hidden_and_description_captured_tmdl():
    # issue #7: capture isHidden (property) + the `///` doc-comment description.
    tmdl = (
        "table T\n"
        "\t/// Intermediate helper.\n"
        "\t/// Not shown on visuals.\n"
        "\tmeasure 'Sales: _Helper' = 1\n"
        "\t\tisHidden: true\n"
        "\tmeasure 'Sales: Revenue' = 2\n"
    )
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    by = {m.name: m for m in cat.measures}
    assert by["Sales: _Helper"].is_hidden is True
    assert by["Sales: _Helper"].description == "Intermediate helper. Not shown on visuals."
    assert by["Sales: Revenue"].is_hidden is False
    assert by["Sales: Revenue"].description == ""  # no `///` above it


def test_measure_is_hidden_and_description_captured_bim():
    model = {
        "name": "M",
        "model": {
            "tables": [
                {
                    "name": "T",
                    "columns": [{"name": "A", "dataType": "int64"}],
                    "measures": [
                        {
                            "name": "Sales: _Helper",
                            "expression": "1",
                            "isHidden": True,
                            "description": ["Line one.", "Line two."],
                        },
                        {"name": "Sales: Revenue", "expression": "2"},
                    ],
                }
            ]
        },
    }
    cat = parse_bim_model("m.bim", json.dumps(model))
    by = {m.name: m for m in cat.measures}
    assert by["Sales: _Helper"].is_hidden is True
    assert "Line one." in by["Sales: _Helper"].description and "Line two." in by["Sales: _Helper"].description
    assert by["Sales: Revenue"].is_hidden is False


def test_column_bare_ishidden_and_real_export_property_order():
    # Real PBIP exports write the BARE `isHidden` keyword (never `isHidden: true`)
    # and serialize `summarizeBy:` AFTER unrecognized properties like
    # `lineageTag:` — neither may unbind the column being scanned.
    tmdl = (
        "table Fact\n"
        "\tcolumn CustomerKey\n"
        "\t\tdataType: int64\n"
        "\t\tisHidden\n"
        "\t\tformatString: 0\n"
        "\t\tisAvailableInMdx: false\n"
        "\t\tlineageTag: 10000000-0000-0000-0000-000000000001\n"
        "\t\tsummarizeBy: none\n"
        "\t\tsourceColumn: CustomerKey\n"
        "\n"
        "\t\tchangedProperty = IsHidden\n"
        "\n"
        "\tcolumn Amount\n"
        "\t\tdataType: double\n"
        "\t\tlineageTag: 10000000-0000-0000-0000-000000000002\n"
        "\t\tsummarizeBy: sum\n"
        "\t\tsourceColumn: Amount\n"
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    cols = {c.name: c for c in cat.tables[0].columns}
    assert cols["CustomerKey"].is_hidden is True
    assert cols["CustomerKey"].summarize_by == "none"
    assert cols["Amount"].is_hidden is False  # changedProperty didn't leak over
    assert cols["Amount"].summarize_by == "sum"


def test_column_colon_ishidden_still_parses():
    # The hand-written colon dialect must keep working alongside the bare form.
    tmdl = (
        "table Fact\n"
        "\tcolumn A\n"
        "\t\tdataType: int64\n"
        "\t\tisHidden: true\n"
        "\tcolumn B\n"
        "\t\tdataType: int64\n"
        "\t\tisHidden: false\n"
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    cols = {c.name: c for c in cat.tables[0].columns}
    assert cols["A"].is_hidden is True
    assert cols["B"].is_hidden is False


def test_measure_bare_ishidden_not_glued_into_dax():
    # A bare `isHidden` after a multi-line measure body is a property, not DAX.
    tmdl = (
        "table T\n"
        "\tmeasure 'Sales: _Helper' =\n"
        "\t\tSUM(T[Amount])\n"
        "\t\tisHidden\n"
        "\t\tlineageTag: 10000000-0000-0000-0000-000000000003\n"
        "\n"
        "\tmeasure 'Sales: Revenue' = SUM(T[Amount])\n"
    )
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    by = {m.name: m for m in cat.measures}
    assert by["Sales: _Helper"].is_hidden is True
    assert by["Sales: _Helper"].dax == "SUM(T[Amount])"  # no glued property text
    assert by["Sales: Revenue"].is_hidden is False


def test_table_level_ishidden_bare_and_colon():
    tmdl_bare = (
        "table Staging\n"
        "\tisHidden\n"
        "\tlineageTag: 10000000-0000-0000-0000-000000000004\n"
        "\n"
        "\tcolumn A\n"
        "\t\tdataType: int64\n"
    )
    tmdl_colon = "table Staging\n\tisHidden: true\n\tcolumn A\n\t\tdataType: int64\n"
    for text in (tmdl_bare, tmdl_colon):
        cat = parse_tmdl_model("M", {"s.tmdl": text})
        assert cat.tables[0].is_hidden is True
        assert cat.hidden_tables == {"staging"}


def test_measure_ishidden_does_not_leak_to_table():
    # An isHidden inside a measure's property block (current column unbound,
    # children already seen) is the MEASURE's — never the table's.
    tmdl = "table T\n\tmeasure 'Sales: _Helper' = 1\n\t\tisHidden\n\tcolumn A\n\t\tdataType: int64\n"
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    assert cat.tables[0].is_hidden is False
    assert {c.name: c.is_hidden for c in cat.tables[0].columns} == {"A": False}
    assert cat.measures[0].is_hidden is True


def test_table_level_ishidden_bim():
    model = {
        "name": "M",
        "model": {
            "tables": [
                {"name": "Staging", "isHidden": True, "columns": [{"name": "A", "dataType": "int64"}]},
                {"name": "Fact", "columns": [{"name": "B", "dataType": "int64"}]},
            ]
        },
    }
    cat = parse_bim_model("m.bim", json.dumps(model))
    hidden = {t.name: t.is_hidden for t in cat.tables}
    assert hidden == {"Staging": True, "Fact": False}
    assert cat.hidden_tables == {"staging"}


def test_calculated_table_expression_inline_tmdl():
    # issue #5: an inline `table X = <DAX>` retains its expression for linting.
    cat = parse_tmdl_model(
        "m", {"t.tmdl": "table Calc = FILTER(Sales, Sales[Amt] > 0)\n\tcolumn A\n\t\tdataType: int64\n"}
    )
    t = cat.tables[0]
    assert t.is_calculated is True
    assert t.expression == "FILTER(Sales, Sales[Amt] > 0)"
    assert t.dax_line == 1
    assert [c.name for c in t.columns] == ["A"]  # columns still parse


def test_calculated_table_expression_multiline_tmdl():
    # issue #5: the multi-line `table X =` form keeps the body AND still parses
    # the (derived) column list below it.
    tmdl = (
        "table Summary =\n"
        "\t\tADDCOLUMNS(\n"
        "\t\t\tVALUES(Sales[Region]),\n"
        '\t\t\t"Ratio", [Rev] / [Cost]\n'
        "\t\t)\n"
        "\tcolumn Region\n"
        "\t\tdataType: string\n"
    )
    cat = parse_tmdl_model("m", {"t.tmdl": tmdl})
    t = cat.tables[0]
    assert t.is_calculated is True
    assert t.expression.startswith("ADDCOLUMNS(") and "[Rev] / [Cost]" in t.expression
    assert t.dax_line == 2
    assert [c.name for c in t.columns] == ["Region"]


def test_calculated_table_expression_bim():
    model = {
        "name": "M",
        "model": {
            "tables": [
                {
                    "name": "Calc",
                    "columns": [{"name": "A", "dataType": "int64"}],
                    "partitions": [
                        {"source": {"type": "calculated", "expression": "FILTER(Sales, Sales[Amt] > 0)"}}
                    ],
                }
            ]
        },
    }
    cat = parse_bim_model("m.bim", json.dumps(model))
    t = cat.tables[0]
    assert t.is_calculated is True
    assert t.expression == "FILTER(Sales, Sales[Amt] > 0)"


def test_columns_calculated_and_storage_mode():
    cat = parse_tmdl_model("Sales", {"f.tmdl": TABLE_TMDL})
    table = cat.tables[0]
    cols = {c.name: c for c in table.columns}
    assert cols["Revenue"].is_calculated is False
    assert cols["Margin"].is_calculated is True
    assert table.storage_mode == "directLake"
    assert cat.storage_mode == "directLake"


# -- issue #13: Column.dax_line — multi-line calc-column bodies map to source lines


_MULTILINE_CALC_COL_TMDL = (
    "table Fact\n"  # line 1
    "\tcolumn Plain\n"  # line 2
    "\t\tdataType: double\n"  # line 3
    "\tcolumn Ratio =\n"  # line 4: declaration
    "\t\tVAR d = Fact[Denominator]\n"  # line 5: DAX body starts here
    "\t\tRETURN\n"  # line 6
    "\t\t\tFact[Numerator] / d\n"  # line 7: the `/` operator
    "\t\tdataType: double\n"  # line 8
    "\tcolumn Inline = Fact[A] * 2\n"  # line 9: inline form
)


def test_calc_column_dax_line_recorded():
    cat = parse_tmdl_model("M", {"f.tmdl": _MULTILINE_CALC_COL_TMDL})
    cols = {c.name: c for c in cat.tables[0].columns}
    assert cols["Ratio"].line == 4 and cols["Ratio"].dax_line == 5  # body below the decl
    assert cols["Inline"].line == 9 and cols["Inline"].dax_line == 9  # inline == decl line
    assert cols["Plain"].dax_line == 0  # a data column has no DAX body
    assert cols["Ratio"].data_type == "double"  # trailing property still binds


def test_multiline_calc_column_finding_points_at_operator_line():
    # issue #13: a rule finding inside a multi-line calc-column body lands on
    # the operator's source line, not the `column X =` declaration line.
    from coop_dax_review.engine import run_rules
    from coop_dax_review.rules import all_rules

    cat = parse_tmdl_model("M", {"f.tmdl": _MULTILINE_CALC_COL_TMDL})
    result = run_rules([cat], [r for r in all_rules() if r.id == "DAX-USE-DIVIDE"])
    by_object = {f.object: f for f in result.findings}
    assert by_object["Fact[Ratio]"].line == 7  # the `/` operator's line


def test_multiline_calc_column_syntax_error_points_at_body_line():
    # issue #13: a structural syntax error inside a multi-line body reports the
    # offending body line (dax_line-based), not the declaration line.
    from coop_dax_review.parsers.syntax_validation import validate_dax_syntax

    tmdl = (
        "table Fact\n"  # line 1
        "\tcolumn Bad =\n"  # line 2: declaration
        "\t\tVAR x = 1\n"  # line 3: body starts
        "\t\tRETURN\n"  # line 4
        "\t\t\tSUM(Fact[A]\n"  # line 5: unbalanced paren
        "\t\tdataType: double\n"
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    diags = validate_dax_syntax([cat])
    assert len(diags) == 1
    assert "Fact[Bad]" in diags[0].message
    assert diags[0].line == 5


# -- issue #25: TMDL triple-backtick verbatim expressions ------------------------------

_FENCE = "```"  # the TMDL verbatim fence (three backticks)


def test_verbatim_measure_body_has_no_fences_and_binds_trailing_property():
    # The serializer emits `measure X = ```` for an expression with trailing
    # whitespace; the fences must NOT end up in the stored DAX, and a property
    # after the closing fence must still bind.
    tmdl = (
        "table Fact\n"  # 1
        f"\tmeasure 'Sales: Rev' = {_FENCE}\n"  # 2: opening fence
        "\t\tCALCULATE(\n"  # 3: body starts
        "\t\t\tSUM(Fact[Amount]),\n"  # 4
        "\t\t\tALL(Fact))\n"  # 5
        f"\t\t{_FENCE}\n"  # 6: closing fence
        "\t\tformatString: #,0\n"  # 7: property after the block
        "\tmeasure 'Sales: Count' = COUNTROWS(Fact)\n"  # 8: next measure
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    by = {m.name: m for m in cat.measures}
    assert set(by) == {"Sales: Rev", "Sales: Count"}  # neither measure lost
    rev = by["Sales: Rev"]
    assert _FENCE not in rev.dax  # fences stripped
    assert rev.dax.startswith("CALCULATE(") and "ALL(Fact)" in rev.dax  # full body kept
    assert rev.format_string == "#,0"  # trailing property still bound
    assert rev.dax_line == 3  # first body line, not the declaration line
    assert by["Sales: Count"].dax == "COUNTROWS(Fact)"  # next measure intact


def test_verbatim_measure_dedented_body_does_not_truncate_the_table():
    # A verbatim body is "read including indentation": a line dedented to column
    # 0 must NOT be mistaken for the next top-level object (which would truncate
    # the whole table and misparse the rest).
    tmdl = (
        "table Fact\n"  # 1
        f"\tmeasure 'Sales: Rev' = {_FENCE}\n"  # 2: opening fence
        "\t\tCALCULATE(\n"  # 3
        "SUM(Fact[Amount]),\n"  # 4: DEDENTED to column 0
        "\t\t\tALL(Fact))\n"  # 5
        f"\t\t{_FENCE}\n"  # 6: closing fence
        "\tmeasure 'Sales: Count' = COUNTROWS(Fact)\n"  # 7: still in the table
        "\tcolumn Amount\n"  # 8: still in the table
        "\t\tdataType: double\n"  # 9
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    table = cat.tables[0]
    by = {m.name: m for m in cat.measures}
    assert set(by) == {"Sales: Rev", "Sales: Count"}  # the table was NOT truncated
    assert "SUM(Fact[Amount])" in by["Sales: Rev"].dax  # the dedented line is part of the body
    assert _FENCE not in by["Sales: Rev"].dax
    assert [c.name for c in table.columns] == ["Amount"]  # the trailing column parsed too
    assert table.columns[0].data_type == "double"


def test_verbatim_calculated_column_body_not_lost():
    # A verbatim calc-column body was silently LOST (group(3) captured '```' as a
    # truthy inline expression, skipping the body loop). It must now be captured,
    # with a trailing dataType still binding.
    tmdl = (
        "table Fact\n"  # 1
        f"\tcolumn Ratio = {_FENCE}\n"  # 2: opening fence
        "\t\tDIVIDE(\n"  # 3: body starts
        "Fact[Num],\n"  # 4: dedented body line
        "\t\t\tFact[Den])\n"  # 5
        f"\t\t{_FENCE}\n"  # 6: closing fence
        "\t\tdataType: double\n"  # 7: property after the block
        "\tcolumn Plain\n"  # 8: next column
        "\t\tdataType: int64\n"  # 9
    )
    cat = parse_tmdl_model("M", {"f.tmdl": tmdl})
    cols = {c.name: c for c in cat.tables[0].columns}
    assert set(cols) == {"Ratio", "Plain"}
    ratio = cols["Ratio"]
    assert ratio.is_calculated is True
    assert ratio.expression.startswith("DIVIDE(") and "Fact[Den]" in ratio.expression
    assert _FENCE not in ratio.expression  # body captured, not just the fence
    assert ratio.data_type == "double"  # trailing property still binds
    assert ratio.dax_line == 3  # first body line
    assert cols["Plain"].is_calculated is False and cols["Plain"].data_type == "int64"


def test_verbatim_calculation_item_body_not_lost():
    tmdl = (
        "table Time\n"  # 1
        "\tcalculationGroup\n"  # 2
        f"\t\tcalculationItem YTD = {_FENCE}\n"  # 3: opening fence
        "\t\t\tCALCULATE(\n"  # 4: body starts
        "SELECTEDMEASURE(),\n"  # 5: dedented body line
        "\t\t\t\tDATESYTD('Date'[Date]))\n"  # 6
        f"\t\t\t{_FENCE}\n"  # 7: closing fence
        "\t\tcalculationItem MTD = SELECTEDMEASURE()\n"  # 8: next item
    )
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    items = {c.name: c for c in cat.calculation_items}
    assert set(items) == {"YTD", "MTD"}  # neither item lost
    ytd = items["YTD"]
    assert ytd.dax.startswith("CALCULATE(") and "DATESYTD" in ytd.dax
    assert _FENCE not in ytd.dax
    assert ytd.dax_line == 4  # first body line


def test_relationship_crossfilter_and_active():
    cat = parse_tmdl_model("Sales", {"model.tmdl": MODEL_TMDL})
    assert len(cat.relationships) == 1
    rel = cat.relationships[0]
    assert (rel.from_table, rel.from_column) == ("FactSales", "ProductId")
    assert (rel.to_table, rel.to_column) == ("DimProduct", "ProductId")
    assert rel.cross_filter == "both"
    assert rel.is_active is False


# -- issue #24: TMDL property keywords are matched case-insensitively ------------------


def test_case_varied_keywords_parse_like_canonical_casing():
    # Hand-written / docs-derived TMDL may lowercase keywords (the MS overview
    # writes `datatype:`). A fully lowercased table + relationship block must
    # parse identically to canonical camelCase — no silently dropped dataType,
    # relationship endpoints, isActive, or crossFilteringBehavior.
    lower_tbl = (
        "table factsales\n\tcolumn productid\n\t\tdatatype: int64\n\tpartition p = m\n\t\tmode: directLake\n"
    )
    lower_model = (
        "model M\n"
        "\n"
        "relationship rel1\n"
        "\tfromcolumn: factsales.productid\n"
        "\ttocolumn: dimproduct.productid\n"
        "\tcrossfilteringbehavior: bothDirections\n"
        "\tisactive: false\n"
    )
    cat = parse_tmdl_model("M", {"t.tmdl": lower_tbl, "model.tmdl": lower_model})
    col = cat.tables[0].columns[0]
    assert col.data_type == "int64"  # dataType captured despite lowercase keyword
    assert cat.tables[0].storage_mode == "directLake"  # mode captured
    assert len(cat.relationships) == 1  # endpoints captured -> relationship kept
    rel = cat.relationships[0]
    assert (rel.from_table, rel.from_column) == ("factsales", "productid")
    assert (rel.to_table, rel.to_column) == ("dimproduct", "productid")
    assert rel.cross_filter == "both"
    assert rel.is_active is False  # isActive captured -> inactive relationship recognized


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
