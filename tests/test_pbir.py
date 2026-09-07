import json
from pathlib import Path

from coop_dax_review import parsers
from coop_dax_review.diagnostics import PBIR_PARSE_FAILED
from coop_dax_review.model import Column, Measure, ModelCatalog, Table
from coop_dax_review.parsers.pbir import parse_report_references
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.dax_broken_field_ref import check as check_broken
from coop_dax_review.rules.dax_unused_measure import detect as detect_unused


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

    scan = parse_report_references(report_dir)
    assert scan.status == "complete"
    assert scan.files_attempted == 2
    assert scan.files_parsed == 2
    assert scan.diagnostics == []
    refs = scan.references
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
        report_files_attempted=scan.files_attempted,
        report_files_parsed=scan.files_parsed,
        report_scan_status=scan.status,
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


def test_partial_pbir_scan_reports_bad_visual_and_keeps_valid_references(tmp_path):
    report_dir = tmp_path / "MyModel.Report"
    _create_mock_report(report_dir)
    bad = report_dir / "definition" / "pages" / "page3" / "visuals" / "bad" / "visual.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not-json")

    scan = parse_report_references(report_dir)

    assert scan.status == "partial"
    assert scan.files_attempted == 3
    assert scan.files_parsed == 2
    assert {ref.field for ref in scan.references} == {
        "dimdate[missingdate]",
        "sales[amount]",
        "sales[usedmeasure]",
    }
    assert len(scan.diagnostics) == 1
    assert scan.diagnostics[0].category == PBIR_PARSE_FAILED
    assert scan.diagnostics[0].file == bad.as_posix()


def test_undecodable_pbir_visual_is_a_failed_scan(tmp_path):
    report_dir = tmp_path / "MyModel.Report"
    visual = report_dir / "definition" / "pages" / "page" / "visuals" / "bad" / "visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_bytes(b'{"visual":{"title":"\xff"}}')

    scan = parse_report_references(report_dir)

    assert scan.status == "failed"
    assert scan.files_attempted == 1
    assert scan.files_parsed == 0
    assert scan.diagnostics[0].file == visual.as_posix()
    assert "valid UTF-8" in scan.diagnostics[0].message


def test_unreadable_pbir_visual_is_a_failed_scan(tmp_path, monkeypatch):
    report_dir = tmp_path / "MyModel.Report"
    visual = report_dir / "definition" / "pages" / "page" / "visuals" / "bad" / "visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text("{}")
    real_read_text = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == visual:
            raise PermissionError("permission denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(parsers.pbir.Path, "read_text", unreadable)
    scan = parse_report_references(report_dir)

    assert scan.status == "failed"
    assert scan.files_attempted == 1
    assert scan.files_parsed == 0
    assert scan.diagnostics[0].file == visual.as_posix()
    assert "could not read" in scan.diagnostics[0].message


def test_partial_scan_blocks_unused_measure_but_keeps_broken_reference_actionable(tmp_path):
    report_dir = tmp_path / "MyModel.Report"
    _create_mock_report(report_dir)
    bad = report_dir / "definition" / "pages" / "page3" / "visuals" / "bad" / "visual.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not-json")
    scan = parse_report_references(report_dir)
    catalog = ModelCatalog(
        name="MyModel",
        tables=[Table(name="Sales", columns=[Column(name="Amount")])],
        measures=[Measure(name="UnusedMeasure", dax="1")],
        report_refs=scan.references,
        reports_scanned=1,
        report_files_attempted=scan.files_attempted,
        report_files_parsed=scan.files_parsed,
        report_scan_status=scan.status,
    )
    ctx_broken = RuleContext(
        Rule(id="R1", title="", severity="warning", category="", standard_ref="", tier=1), catalog
    )
    ctx_unused = RuleContext(
        Rule(id="R2", title="", severity="info", category="", standard_ref="", tier=1, kind="agent"),
        catalog,
    )

    findings = check_broken(ctx_broken)

    assert any("dimdate[missingdate]" in finding.message for finding in findings)
    assert detect_unused(ctx_unused) == []
