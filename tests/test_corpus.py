"""Corpus crash-guard (issue #4): no rule may crash on a realistic model.

``engine.run_rules`` isolates a crashing rule into a ``rule_error`` diagnostic
and the exit code stays 0 — so without this guard a rule-crash regression (a
parser refactor changing a shape, say) would ship green and only surface as
per-run diagnostics on user machines. The synthetic corpus exercises every
parser feature at once (multi-line measures with §12 headers, calculated
columns + tables, a calculation group, quoted identifiers with spaces / parens /
apostrophes, hidden + documented measures, partitions, active/inactive +
bidirectional relationships, a marked Date table) so a future regression that
silently drops objects also fails the count assertions below. All content is
generic/synthetic (this repo is public).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.diagnostics import RULE_ERROR
from coop_dax_review.engine import run_rules
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import parse_tmdl_model
from coop_dax_review.rules import all_rules

_TABLES = {
    "definition/tables/DimDate.tmdl": (
        "table DimDate\n"
        "\tcolumn Date\n"
        "\t\tdataType: dateTime\n"
        "\t\tdataCategory: Time\n"
        "\tcolumn Year\n"
        "\t\tdataType: int64\n"
    ),
    "definition/tables/DimCustomer.tmdl": (
        "table DimCustomer\n"
        "\tcolumn CustomerKey\n"
        "\t\tdataType: int64\n"
        "\t\tsummarizeBy: none\n"
        "\tcolumn 'Customer Name'\n"
        "\t\tdataType: string\n"
        "\n"
        "\t/// Internal helper, not shown on visuals.\n"
        "\tmeasure 'Cust: _ActiveCount' = COUNTROWS(DimCustomer)\n"
        "\t\tisHidden: true\n"
        "\n"
        "\tmeasure 'Cust: Count' = COUNTROWS(DimCustomer)\n"
        "\t\tdisplayFolder: Counts\n"
        "\t\tformatString: #,0\n"
    ),
    "definition/tables/FactSales.tmdl": (
        "table FactSales\n"
        "\tcolumn Amount\n"
        "\t\tdataType: double\n"
        "\tcolumn Cost\n"
        "\t\tdataType: double\n"
        "\tcolumn CustomerKey\n"
        "\t\tdataType: int64\n"
        "\t\tsummarizeBy: none\n"
        "\tcolumn DateKey\n"
        "\t\tdataType: dateTime\n"
        "\t\tsummarizeBy: none\n"
        "\tcolumn 'Net (USD)' = FactSales[Amount] * 0.9\n"
        "\t\tdataType: double\n"
        "\tcolumn Margin =\n"
        "\t\tDIVIDE(\n"
        "\t\t\tFactSales[Amount],\n"
        "\t\t\tFactSales[Cost]\n"
        "\t\t)\n"
        "\t\tdataType: double\n"
        "\n"
        "\t/* Measure: Revenue\n"
        "\t   Purpose: total sales revenue */\n"
        "\tmeasure 'Sales: Revenue' = SUM(FactSales[Amount])\n"
        "\t\tformatString: \\$#,0\n"
        "\n"
        "\tmeasure 'Sales: Revenue YTD' =\n"
        "\t\tCALCULATE(\n"
        "\t\t\t[Sales: Revenue],\n"
        "\t\t\tDATESYTD(DimDate[Date])\n"
        "\t\t)\n"
        "\t\tformatString: \\$#,0\n"
        "\n"
        "\tpartition FactSales = m\n"
        "\t\tmode: import\n"
        '\t\tsource = "let Source = ... in Source"\n'
    ),
    "definition/tables/TopCustomers.tmdl": (
        "table 'Top Customers' =\n"
        "\t\tTOPN(\n"
        "\t\t\t10,\n"
        "\t\t\tDimCustomer,\n"
        "\t\t\t[Cust: Count]\n"
        "\t\t)\n"
        "\tcolumn CustomerKey\n"
        "\t\tdataType: int64\n"
    ),
    "definition/tables/TimeIntel.tmdl": (
        "table 'Time Intelligence'\n"
        "\tcalculationGroup\n"
        "\n"
        "\tcalculationItem Current = SELECTEDMEASURE()\n"
        "\n"
        "\tcalculationItem YoY =\n"
        "\t\tCALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR(DimDate[Date]))\n"
        "\n"
        "\tcolumn 'Time Calculation'\n"
        "\t\tdataType: string\n"
    ),
    "definition/relationships.tmdl": (
        "relationship rCustomer\n"
        "\tfromColumn: FactSales.CustomerKey\n"
        "\ttoColumn: DimCustomer.CustomerKey\n"
        "\n"
        "relationship rDate\n"
        "\tfromColumn: FactSales.DateKey\n"
        "\ttoColumn: DimDate.Date\n"
        "\tisActive: false\n"
        "\tcrossFilteringBehavior: bothDirections\n"
    ),
    "definition/model.tmdl": "model Corpus\n",
}

_LEGACY_BIM = {
    "name": "Legacy",
    "model": {
        "tables": [
            {
                "name": "FactSales",
                "columns": [
                    {"name": "Amount", "dataType": "double"},
                    {"name": "Ratio", "type": "calculated", "expression": "DIVIDE([Amount], 2)"},
                ],
                "measures": [
                    {"name": "Sales: Revenue", "expression": "SUM(FactSales[Amount])", "formatString": "#,0"},
                    {"name": "Sales: _Helper", "expression": "1", "isHidden": True, "description": "helper"},
                ],
            },
            {
                "name": "Time Intelligence",
                "calculationGroup": {
                    "calculationItems": [
                        {"name": "Current", "expression": "SELECTEDMEASURE()"},
                    ]
                },
            },
        ]
    },
}


def _corpus_catalog():
    return parse_tmdl_model("Corpus", _TABLES)


def test_corpus_parses_to_expected_object_counts():
    cat = _corpus_catalog()
    # A future parser regression that silently drops objects fails here.
    assert len(cat.tables) == 5
    assert {m.name for m in cat.measures} == {
        "Cust: _ActiveCount",
        "Cust: Count",
        "Sales: Revenue",
        "Sales: Revenue YTD",
    }
    assert len(cat.relationships) == 2
    assert {c.name for c in cat.calculation_items} == {"Current", "YoY"}
    # feature spot-checks: hidden measure, calc table, calc column all captured.
    assert next(m for m in cat.measures if m.name == "Cust: _ActiveCount").is_hidden
    assert next(t for t in cat.tables if t.name == "Top Customers").expression.startswith("TOPN(")
    assert next(c for t in cat.tables for c in t.columns if c.name == "Margin").is_calculated


def test_every_rule_survives_the_corpus():
    # ALL rules, including off-by-default ones the CLI wouldn't run.
    result = run_rules(
        [_corpus_catalog(), parse_bim_model("legacy.bim", json.dumps(_LEGACY_BIM))], all_rules()
    )
    errors = [d for d in result.diagnostics if d.category == RULE_ERROR]
    assert errors == [], "\n".join(f"{d.rule_id}: {d.message}" for d in errors)
    # The corpus must actually exercise rules (guard against it degrading into
    # something no rule can see inside).
    assert result.findings


def test_corpus_findings_are_deterministic():
    a = run_rules([_corpus_catalog()], all_rules())
    b = run_rules([_corpus_catalog()], all_rules())
    key = [(f.model, f.file, f.line, f.rule_id, f.object) for f in a.findings]
    assert key == [(f.model, f.file, f.line, f.rule_id, f.object) for f in b.findings]


def test_check_over_the_corpus_reports_no_rule_errors(tmp_path):
    root = tmp_path / "Corpus.SemanticModel"
    for rel, text in _TABLES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "legacy.bim").write_text(json.dumps(_LEGACY_BIM), encoding="utf-8")

    result = CliRunner().invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["models_checked"] >= 2  # the TMDL model + the .bim
    assert [d for d in payload["diagnostics"] if d["category"] == RULE_ERROR] == []
