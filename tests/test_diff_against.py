"""`check --diff-against FILE`: the run-to-run delta, built on core's delta engine.

Requires coop-review-core >= 0.6.0 (the `delta` module); run bare only after the
venv is refreshed to it, else shadow the local core on PYTHONPATH (see AGENTS.md).
"""

from pathlib import Path

from click.testing import CliRunner

from coop_dax_review.cli import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _json_report(out_path):
    r = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json", "-o", str(out_path)])
    assert r.exit_code == 0, r.output
    return out_path


def test_diff_against_identical_run_is_all_persisting(tmp_path):
    old = _json_report(tmp_path / "old.json")
    r = CliRunner().invoke(cli, ["check", str(FIXTURES), "--diff-against", str(old)])
    assert r.exit_code == 0
    assert "0 new, 0 fixed," in r.output
    assert "unchanged" in r.output
    assert "summary delta:" in r.output


def test_diff_against_min_severity_shift_shows_fixed(tmp_path):
    # old.json captures every finding; a stricter run reports fewer (the fixtures emit
    # only warnings/info, so --min-severity error leaves none), so the dropped findings
    # read as "fixed" — exercising the fixed path on real models.
    old = _json_report(tmp_path / "old.json")
    r = CliRunner().invoke(
        cli, ["check", str(FIXTURES), "--min-severity", "error", "--diff-against", str(old)]
    )
    assert r.exit_code == 0
    assert "0 new," in r.output
    assert "0 unchanged" in r.output  # nothing reported now -> nothing persists
    assert "FIXED (" in r.output


def test_diff_against_wrong_tool_is_usage_error(tmp_path):
    sql = tmp_path / "sql.json"
    sql.write_text('{"tool": "coop-sql-review", "findings": [], "summary": {}}')
    r = CliRunner().invoke(cli, ["check", str(FIXTURES), "--diff-against", str(sql)])
    assert r.exit_code == 2
    assert "different tools" in r.output


def test_diff_against_missing_file_is_usage_error(tmp_path):
    r = CliRunner().invoke(cli, ["check", str(FIXTURES), "--diff-against", str(tmp_path / "nope.json")])
    assert r.exit_code == 2
    assert "--diff-against" in r.output


def test_diff_against_invalid_json_is_usage_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{")
    r = CliRunner().invoke(cli, ["check", str(FIXTURES), "--diff-against", str(bad)])
    assert r.exit_code == 2
    assert "not valid JSON" in r.output
