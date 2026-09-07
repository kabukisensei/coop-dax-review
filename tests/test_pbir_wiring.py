"""End-to-end PBIP sibling discovery and PBIR coverage behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from coop_dax_review.cli import apply_pbir_report_awareness, build_catalogs, cli, discover_inputs
from coop_dax_review.diagnostics import PBIR_PARSE_FAILED


def _write_model(project: Path, name: str = "Sales") -> tuple[Path, Path]:
    model_root = project / f"{name}.SemanticModel"
    model_file = model_root / "definition" / "model.tmdl"
    table_file = model_root / "definition" / "tables" / "Sales.tmdl"
    model_file.parent.mkdir(parents=True)
    table_file.parent.mkdir(parents=True)
    model_file.write_text(f"model {name}\n")
    table_file.write_text(
        """table Sales
\tcolumn Amount
\t\tdataType: double

\tmeasure UsedMeasure = 1
\tmeasure UnusedMeasure = 2
"""
    )
    return model_file, table_file


def _write_visual(report_root: Path, name: str, *properties: str) -> Path:
    visual = report_root / "definition" / "pages" / "page" / "visuals" / name / "visual.json"
    visual.parent.mkdir(parents=True)
    visual.write_text(
        json.dumps(
            {
                "visual": {
                    "projections": {
                        "values": [
                            {"Entity": "Sales", "Property": prop, "queryRef": f"Sales.{prop}"}
                            for prop in properties
                        ]
                    }
                }
            }
        )
    )
    return visual


def _catalogs_for(*paths: Path):
    tmdl, bim, pbit, _pbix = discover_inputs(tuple(str(path) for path in paths))
    return build_catalogs(tmdl, bim, pbit)


@pytest.mark.parametrize("entrypoint", ["root", "model", "table"])
def test_standard_pbip_entrypoints_bind_exact_sibling_report(tmp_path, entrypoint):
    model_file, table_file = _write_model(tmp_path)
    report_root = tmp_path / "Sales.Report"
    visual = _write_visual(report_root, "main", "UsedMeasure", "MissingField")
    selected = {
        "root": tmp_path / "Sales.SemanticModel",
        "model": model_file,
        "table": table_file,
    }[entrypoint]
    catalogs = _catalogs_for(selected)

    apply_pbir_report_awareness(catalogs)

    assert len(catalogs) == 1
    catalog = catalogs[0]
    assert catalog.reports_scanned == 1
    assert catalog.report_scan_status == "complete"
    assert catalog.report_files_attempted == 1
    assert catalog.report_files_parsed == 1
    assert {ref.visual_file for ref in catalog.report_refs} == {visual.as_posix()}


def test_report_references_reach_both_rules_through_real_cli(tmp_path):
    _write_model(tmp_path)
    _write_visual(tmp_path / "Sales.Report", "main", "UsedMeasure", "MissingField")

    result = CliRunner().invoke(cli, ["check", str(tmp_path / "Sales.SemanticModel"), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert any(
        finding["rule_id"] == "DAX-BROKEN-FIELD-REF" and "missingfield" in finding["message"]
        for finding in payload["findings"]
    )
    unused = [item for item in payload["agent_review"] if item["rule_id"] == "DAX-UNUSED-MEASURE"]
    assert any(item["object"] == "[UnusedMeasure]" for item in unused)
    assert not any(item["object"] == "[UsedMeasure]" for item in unused)
    assert payload["coverage"]["pbir"] == {
        "status": "complete",
        "reports_scanned": 1,
        "files_attempted": 1,
        "files_parsed": 1,
    }


def test_same_named_models_bind_only_reports_in_their_own_parent(tmp_path):
    for environment, property_name in (("dev", "DevOnly"), ("prod", "ProdOnly")):
        project = tmp_path / environment
        _write_model(project)
        _write_visual(project / "Sales.Report", "main", property_name)
    catalogs = _catalogs_for(tmp_path / "dev", tmp_path / "prod")

    apply_pbir_report_awareness(catalogs)

    assert len(catalogs) == 2
    for catalog in catalogs:
        environment = Path(catalog.source_root).parent.name
        assert catalog.reports_scanned == 1
        assert len(catalog.report_refs) == 1
        assert f"/{environment}/Sales.Report/" in catalog.report_refs[0].visual_file


def test_loose_tmdl_and_bim_do_not_bind_same_named_reports(tmp_path):
    loose = tmp_path / "Loose"
    loose.mkdir()
    tmdl = loose / "model.tmdl"
    tmdl.write_text("model Loose\n")
    bim = tmp_path / "Other.bim"
    bim.write_text('{"name":"Other","model":{"tables":[]}}')
    _write_visual(tmp_path / "Loose.Report", "main", "ShouldNotBind")
    _write_visual(tmp_path / "Other.Report", "main", "ShouldNotBind")
    catalogs = _catalogs_for(tmdl, bim)

    apply_pbir_report_awareness(catalogs)

    assert len(catalogs) == 2
    assert all(catalog.reports_scanned == 0 for catalog in catalogs)
    assert all(catalog.report_scan_status == "not-applicable" for catalog in catalogs)
    assert all(catalog.report_refs == [] for catalog in catalogs)


def _partial_report_model(tmp_path: Path) -> tuple[Path, Path]:
    _write_model(tmp_path)
    report_root = tmp_path / "Sales.Report"
    _write_visual(report_root, "good", "MissingField")
    bad = report_root / "definition" / "pages" / "page" / "visuals" / "bad" / "visual.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not-json")
    return tmp_path / "Sales.SemanticModel", bad


def test_partial_scan_is_error_diagnostic_blocks_unused_and_keeps_broken_finding(tmp_path):
    model_root, bad = _partial_report_model(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["check", str(model_root), "--format", "json", "--strict", "--min-severity", "error"],
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    diagnostics = [d for d in payload["diagnostics"] if d["category"] == PBIR_PARSE_FAILED]
    assert len(diagnostics) == 1
    assert diagnostics[0]["severity"] == "error"
    assert diagnostics[0]["file"] == bad.as_posix()
    assert payload["coverage"]["pbir"] == {
        "status": "partial",
        "reports_scanned": 1,
        "files_attempted": 2,
        "files_parsed": 1,
    }
    assert not [item for item in payload["agent_review"] if item["rule_id"] == "DAX-UNUSED-MEASURE"]

    advisory = CliRunner().invoke(cli, ["check", str(model_root), "--format", "json"])
    assert advisory.exit_code == 0, advisory.output
    advisory_payload = json.loads(advisory.stdout)
    assert any(finding["rule_id"] == "DAX-BROKEN-FIELD-REF" for finding in advisory_payload["findings"])


@pytest.mark.parametrize("fmt", ["text", "markdown", "sarif"])
def test_pbir_diagnostic_is_consistent_in_stream_formats(tmp_path, fmt):
    model_root, bad = _partial_report_model(tmp_path)

    result = CliRunner().invoke(cli, ["check", str(model_root), "--format", fmt])

    assert result.exit_code == 0, result.output
    assert bad.as_posix() in result.stdout


def test_pbir_diagnostic_is_consistent_in_html_and_log(tmp_path):
    model_root, bad = _partial_report_model(tmp_path)
    html = tmp_path / "report.html"
    log = tmp_path / "diagnostics.log"

    result = CliRunner().invoke(
        cli,
        [
            "check",
            str(model_root),
            "--format",
            "html",
            "--output",
            str(html),
            "--log-file",
            str(log),
            "--no-open",
        ],
    )

    assert result.exit_code == 0, result.output
    assert bad.as_posix() in html.read_text()
    assert bad.as_posix() in log.read_text()
