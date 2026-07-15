"""`coop-dax-review explain <RULE-ID>` (mirror of coop-sql-review #38)."""

import json

import pytest
from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.rules import all_rules
from coop_dax_review.standards import resolve_standards_path, section_text

RULE_IDS = [r.id for r in all_rules()]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_explain_every_rule_runs(rule_id):
    r = CliRunner().invoke(cli, ["explain", rule_id, "--no-color"])
    assert r.exit_code == 0, r.output
    assert rule_id in r.output
    assert "severity:" in r.output


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_explain_json_every_rule(rule_id):
    r = CliRunner().invoke(cli, ["explain", rule_id, "--format", "json"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["id"] == rule_id
    assert {"rationale", "standards_excerpt", "severity", "tier"} <= set(d)


def test_explain_is_case_insensitive():
    r = CliRunner().invoke(cli, ["explain", "dax-use-divide", "--no-color"])
    assert r.exit_code == 0
    assert "DAX-USE-DIVIDE" in r.output


def test_explain_numeric_ref_shows_the_standards_excerpt():
    r = CliRunner().invoke(cli, ["explain", "DAX-USE-DIVIDE", "--no-color"])
    assert "Standard §14" in r.output  # DAX-USE-DIVIDE cites §14


def test_explain_unknown_id_is_a_usage_error_with_suggestion():
    r = CliRunner().invoke(cli, ["explain", "DAX-DIVIDE"])
    assert r.exit_code == 2
    assert "unknown rule id" in r.output
    assert "DAX-USE-DIVIDE" in r.output


def test_section_text_slices_exactly_and_is_safe():
    std = resolve_standards_path(None)
    s1 = section_text(std, "§1")
    assert s1.startswith("## 1.")
    assert "\n## 2." not in s1
    assert section_text(std, "§999") == ""
    assert section_text(std, "") == ""
