"""CLI end-to-end: discovery, the agent JSON contract, advisory exit codes."""

import json
from pathlib import Path

from click.testing import CliRunner

from coop_dax_review.cli import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_check_text_is_advisory_exit_zero():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert result.exit_code == 0
    assert "Advisory only" in result.output


def test_check_json_contract_shape():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["tool"] == "coop-dax-review"
    assert set(payload) >= {"findings", "summary", "agent_review", "standards", "diagnostics"}
    assert payload["standards"]["sha256"]
    for finding in payload["findings"]:
        assert set(finding) == {
            "rule_id",
            "severity",
            "model",
            "file",
            "line",
            "object",
            "message",
            "standard_ref",
        }


def test_strict_exits_two_when_findings_remain():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--strict"])
    assert result.exit_code == 2


def test_strict_exit_zero_when_filtered_below_threshold():
    # The fixtures emit only warnings/info; filtering to errors leaves none.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--strict", "--min-severity", "error"])
    assert result.exit_code == 0


def test_no_models_found_is_graceful():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES / "nonexistent")])
    assert result.exit_code == 0
    assert "No TMDL" in result.output


def test_rules_command_lists_every_rule():
    result = CliRunner().invoke(cli, ["rules", "--format", "json"])
    assert result.exit_code == 0
    ids = {r["id"] for r in json.loads(result.output)}
    assert "DAX-NO-NESTED-CALCULATE" in ids
    assert "DAX-MARKED-DATE-TABLE" in ids
