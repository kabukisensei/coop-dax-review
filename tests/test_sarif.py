"""SARIF 2.1.0 output (core emitter, issue #18): shape, mapping, determinism,
and the CLI wiring (`--format sarif` + the `--sarif FILE` extra sink) — mirrors
the coop-sql-review twin's contract (one family shape)."""

import json
from pathlib import Path

from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.engine import Result
from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.report import to_sarif

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STANDARDS = {"path": "docs/standards.md", "sha256": "abc123"}


def _result() -> Result:
    # findings already in engine-sorted order (model, file, line, ...)
    return Result(
        findings=[
            Finding(
                "DAX-USE-DIVIDE",
                "warning",
                "Sales",
                "tables/FactSales.tmdl",
                12,
                "[Sales: Margin %]",
                "use DIVIDE() for safe division",
                "§14",
            ),
        ],
        agent_review=[
            AgentReviewItem(
                "DAX-CONTEXT-TRANSITION",
                "Sales",
                "tables/FactSales.tmdl",
                "[Sales: Total]",
                40,
                "CALCULATE inside an iterator",
                "§9",
            ),
        ],
        models_checked=1,
    )


def test_sarif_is_valid_2_1_0_and_maps_findings():
    sarif = json.loads(to_sarif(_result(), version="0.1.0", standards=STANDARDS))
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "coop-dax-review" and driver["version"] == "0.1.0"
    assert "coop-dax-review" in driver["informationUri"]
    rule_ids = {r["id"] for r in driver["rules"]}
    # Every result maps to a rule that exists in tool.driver.rules.
    for res in run["results"]:
        assert res["ruleId"] in rule_ids
    # The finding maps to a warning-level result at its line with its fingerprint.
    finding_res = next(r for r in run["results"] if r["ruleId"] == "DAX-USE-DIVIDE")
    assert finding_res["level"] == "warning"
    loc = finding_res["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "tables/FactSales.tmdl"  # TMDL path renders as-is
    assert loc["region"]["startLine"] == 12
    assert finding_res["partialFingerprints"]["coopFingerprint/v2"] == _result().findings[0].fingerprint()
    # The agent-review item is a non-blocking note (advisory judgment calls
    # are visible but never gate — same call as the twin).
    agent_res = next(r for r in run["results"] if r["ruleId"] == "DAX-CONTEXT-TRANSITION")
    assert agent_res["level"] == "note"


def test_sarif_rule_metadata_carries_standard_refs():
    driver = json.loads(to_sarif(Result(), version="0", standards=STANDARDS))["runs"][0]["tool"]["driver"]
    by_id = {r["id"]: r for r in driver["rules"]}
    rule = by_id["DAX-USE-DIVIDE"]
    assert rule["shortDescription"]["text"]  # the rule title
    assert rule["properties"]["standard_ref"].startswith("§")
    assert rule["defaultConfiguration"]["level"] == "warning"
    # The synthetic diagnostics rule is appended so broken input still annotates.
    assert "syntax-error" in by_id
    assert by_id["syntax-error"]["defaultConfiguration"]["level"] == "error"


def test_sarif_severity_mapping():
    result = Result(
        findings=[
            Finding("DAX-A", "error", "M", "a.tmdl", 1, "[o]", "m", "§1"),
            Finding("DAX-B", "warning", "M", "a.tmdl", 2, "[o]", "m", "§1"),
            Finding("DAX-C", "info", "M", "a.tmdl", 3, "[o]", "m", "§1"),
        ],
        models_checked=1,
    )
    levels = {
        r["ruleId"]: r["level"]
        for r in json.loads(to_sarif(result, version="0", standards=STANDARDS))["runs"][0]["results"]
    }
    assert levels == {"DAX-A": "error", "DAX-B": "warning", "DAX-C": "note"}  # info -> note


def test_sarif_omits_region_for_line_zero():
    # A model-level finding (line 0) renders a bare artifact location — no region.
    result = Result(
        findings=[Finding("DAX-X", "warning", "M", "model.tmdl", 0, "M", "model-level", "§1")],
        models_checked=1,
    )
    loc = json.loads(to_sarif(result, version="0", standards=STANDARDS))["runs"][0]["results"][0][
        "locations"
    ][0]
    assert "region" not in loc["physicalLocation"]  # no line -> no region
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == "model.tmdl"


def test_sarif_is_deterministic():
    a = to_sarif(_result(), version="0.1.0", standards=STANDARDS)
    b = to_sarif(_result(), version="0.1.0", standards=STANDARDS)
    assert a == b and a.endswith("\n")


def test_sarif_is_pure_ascii():
    # ensure_ascii so the § marks in rule metadata are safe on any console.
    to_sarif(_result(), version="0.1.0", standards=STANDARDS).encode("ascii")


# ---------------------------------------------------------------------------
# CLI wiring: --format sarif and the --sarif extra sink
# ---------------------------------------------------------------------------


def test_format_sarif_prints_parseable_sarif():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "sarif"])
    assert result.exit_code == 0  # advisory, like every other format
    sarif = json.loads(result.stdout)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "coop-dax-review"
    assert sarif["runs"][0]["results"]  # the fixtures fire findings


def test_format_sarif_results_match_json_findings_plus_agent_items():
    json_out = json.loads(CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"]).stdout)
    sarif = json.loads(CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "sarif"]).stdout)
    error_diags = [d for d in json_out["diagnostics"] if d["severity"] == "error"]
    expected = len(json_out["findings"]) + len(json_out["agent_review"]) + len(error_diags)
    assert len(sarif["runs"][0]["results"]) == expected


def test_sarif_output_is_byte_identical_across_runs():
    runner = CliRunner()
    first = runner.invoke(cli, ["check", str(FIXTURES), "--format", "sarif"])
    second = runner.invoke(cli, ["check", str(FIXTURES), "--format", "sarif"])
    assert first.stdout == second.stdout


def test_sarif_extra_sink_composes_with_any_format(tmp_path):
    # --sarif FILE writes an extra report alongside the main --format output.
    sarif_file = tmp_path / "r.sarif"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--sarif", str(sarif_file)])
    assert result.exit_code == 0
    assert "DAX-" in result.stdout  # the main text report still prints
    assert "SARIF report written to" in result.stderr  # announced on stderr
    body = json.loads(sarif_file.read_text(encoding="utf-8"))
    assert body["version"] == "2.1.0"


def test_sarif_to_output_file(tmp_path):
    # --format sarif -o FILE: the CI-snippet form (upload the file to code scanning).
    out = tmp_path / "review.sarif"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "sarif", "-o", str(out)])
    assert result.exit_code == 0
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["runs"][0]["results"]
    assert "runs" not in result.stdout  # the report went to the file, not the screen


def test_syntax_error_becomes_sarif_error_result(tmp_path):
    # Genuinely malformed DAX surfaces as an error-level result on the synthetic
    # diagnostics rule, so broken measures still annotate the PR line.
    root = tmp_path / "Model.SemanticModel" / "definition" / "tables"
    root.mkdir(parents=True)
    (root / "FactSales.tmdl").write_text(
        "table FactSales\n\tcolumn Revenue\n\t\tdataType: double\n\n"
        "\tmeasure 'Bad' = SUM(FactSales[Revenue]\n",
        encoding="utf-8",
    )
    out = (
        CliRunner().invoke(cli, ["check", str(tmp_path / "Model.SemanticModel"), "--format", "sarif"]).stdout
    )
    sarif = json.loads(out)
    driver_rule_ids = {r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert "syntax-error" in driver_rule_ids
    errs = [r for r in sarif["runs"][0]["results"] if r["level"] == "error"]
    assert any(r["ruleId"] == "syntax-error" for r in errs)


def test_sarif_basic_schema_sanity():
    # A minimal structural pass over the emitted log: the required SARIF 2.1.0
    # members exist with the right shapes (a stand-in for full schema validation,
    # which would need a network fetch — this tool is offline).
    sarif = json.loads(CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "sarif"]).stdout)
    assert isinstance(sarif["runs"], list) and len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    for key in ("name", "version", "informationUri", "rules"):
        assert key in driver
    for rule in driver["rules"]:
        assert isinstance(rule["id"], str) and rule["id"]
        assert rule["shortDescription"]["text"]
    for res in run["results"]:
        assert res["level"] in ("error", "warning", "note")
        assert isinstance(res["message"]["text"], str)
        assert res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
