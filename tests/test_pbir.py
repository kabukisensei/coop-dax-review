import json
from pathlib import Path

from coop_dax_review.model import ModelCatalog, Table, Column, Measure
from coop_dax_review.parsers.pbir import parse_report_references
from coop_dax_review.rules.dax_broken_field_ref import check as check_broken
from coop_dax_review.rules.dax_unused_measure import detect as detect_unused
from coop_dax_review.rules.base import RuleContext, Rule


def _create_mock_report(path: Path):
    path.mkdir(parents=True)
    pages = path / "definition" / "pages"
    pages.mkdir(parents=True)

    # Mock visual 1 (broken ref + valid ref)
    visuals1 = pages / "page1" / "visuals" / "v1"
    visuals1.mkdir(parents=True)
    visuals1.joinpath("visual.json").write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "barChart",
                    "projections": {
                        "values": [{"queryRef": "Sales.Amount", "Property": "Amount", "Entity": "Sales"}]
                    },
                },
                "filterConfig": {"filters": [{"Entity": "DimDate", "Property": "MissingDate"}]},
            }
        )
    )

    # Mock visual 2 (unused measure is actually used here)
    visuals2 = pages / "page2" / "visuals" / "v2"
    visuals2.mkdir(parents=True)
    visuals2.joinpath("visual.json").write_text(
        json.dumps(
            {
                "visual": {
                    "visualType": "table",
                    "projections": {
                        "values": [
                            {"queryRef": "Sales.UsedMeasure", "Property": "UsedMeasure", "Entity": "Sales"}
                        ]
                    },
                }
            }
        )
    )


def test_parse_pbir_and_rules(tmp_path):
    report_dir = tmp_path / "MyModel.Report"
    _create_mock_report(report_dir)

    refs = parse_report_references(report_dir)
    assert len(refs) == 3

    fields = {r.field for r in refs}
    assert "sales[amount]" in fields
    assert "dimdate[missingdate]" in fields
    assert "sales[usedmeasure]" in fields

    catalog = ModelCatalog(
        name="MyModel",
        tables=[
            Table(name="Sales", columns=[Column(name="Amount")]),
            Table(name="DimDate", columns=[Column(name="DateKey")]),
        ],
        measures=[
            Measure(name="UsedMeasure", dax="1"),
            Measure(name="UnusedMeasure", dax="2"),
            Measure(name="DaxUsedMeasure", dax="3"),
        ],
        report_refs=refs,
        reports_scanned=1,
    )

    # Simulate internal DAX ref
    catalog.measures[0].dax = "CALCULATE([DaxUsedMeasure])"

    ctx_broken = RuleContext(
        Rule(id="R1", title="", severity="warning", category="", standard_ref="", tier=1), catalog
    )
    findings = check_broken(ctx_broken)

    assert len(findings) == 1
    assert "dimdate[missingdate]" in findings[0].message

    ctx_unused = RuleContext(
        Rule(id="R2", title="", severity="info", category="", standard_ref="", tier=1, kind="agent"), catalog
    )
    items = detect_unused(ctx_unused)

    assert len(items) == 1
    assert "[UnusedMeasure]" in items[0].note
