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


def test_text_report_is_styled_and_plain_when_piped():
    # CliRunner stdout is not a TTY -> auto mode stays plain (no ANSI).
    out = CliRunner().invoke(cli, ["check", str(FIXTURES)]).output
    assert "\033[" not in out
    assert "coop-dax-review" in out and "SUMMARY" in out  # the report banner + panel
    assert "Advisory only" in out


def test_text_report_color_flag_forces_ansi():
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--color"]).output
    assert "\033[" in out  # explicit --color wins over the non-interactive default


def test_use_color_decision(monkeypatch):
    from coop_dax_review.cli import _use_color

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _use_color(True, None) is True  # explicit --color
    assert _use_color(False, None) is False  # explicit --no-color
    assert _use_color(None, "out.txt") is False  # writing to a file -> never color
    monkeypatch.setenv("NO_COLOR", "1")
    assert _use_color(None, None) is False  # NO_COLOR wins in auto mode


def test_markdown_format():
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "markdown"]).output
    assert out.startswith("# coop-dax-review report")
    assert "## Findings" in out
    assert "DAX-" in out


def test_output_writes_text_report_to_file(tmp_path):
    report = tmp_path / "report.txt"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "-o", str(report)])
    assert result.exit_code == 0
    body = report.read_text(encoding="utf-8")
    assert "Advisory only" in body and "DAX-" in body  # the report went to the file
    # the report body stays off the streams; only the "written to" notice (stderr) shows
    assert "Advisory only" not in result.output
    assert "DAX-" not in result.output
    assert str(report) in result.stderr  # the path is announced on stderr


def test_html_format_writes_file_opens_nothing_under_test(tmp_path):
    report = tmp_path / "out.html"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "html", "-o", str(report)])
    assert result.exit_code == 0
    assert report.exists()
    body = report.read_text(encoding="utf-8")
    assert body.startswith("<!DOCTYPE html>")
    assert "</html>" in body
    assert "DAX-" in body  # at least one rule fired in the fixtures
    assert "HTML report written to" in result.output
    # the path is shown for the user, as a POSIX path (OS-stable; backslashes on Windows otherwise)
    assert report.resolve().as_posix() in result.output


def test_html_defaults_to_a_file_in_cwd():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["check", str(FIXTURES), "--format", "html"])
        assert result.exit_code == 0
        assert Path("coop-dax-review-report.html").exists()


def test_interactive_picker_falls_back_without_subdirs(tmp_path):
    from coop_dax_review.cli import _interactive_pick_paths

    (tmp_path / "model.tmdl").write_text("x\n", encoding="utf-8")
    # No subfolders -> picker returns None so the caller uses the default path.
    assert _interactive_pick_paths(tmp_path) is None


def test_interactive_picker_all_selected_returns_root(tmp_path, monkeypatch):
    from coop_dax_review import cli as climod

    (tmp_path / "Sales.SemanticModel").mkdir()
    (tmp_path / "Finance.SemanticModel").mkdir()

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            pass

        def ask(self):  # simulate the user keeping everything checked
            return [tmp_path / "Finance.SemanticModel", tmp_path / "Sales.SemanticModel"]

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox())
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))
    assert climod._interactive_pick_paths(tmp_path) == [tmp_path]  # all -> scan root


def test_update_prints_command_and_never_applies(monkeypatch):
    from coop_dax_review import upgrade as upmod

    plan = upmod.UpgradePlan("pipx", None, "0.1.0", "already on the latest release (0.1.0)", pip_spec=None)
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)
    result = CliRunner().invoke(cli, ["update"])
    assert result.exit_code == 0
    assert "does not update itself" in result.output
    assert "pipx upgrade coop-dax-review" in result.output
    # never self-applies: no trace of the old apply path's output
    assert "ran:" not in result.output
    assert "Done." not in result.output


def test_upgrade_alias_also_prints_command(monkeypatch):
    from coop_dax_review import upgrade as upmod

    plan = upmod.UpgradePlan("pipx", None, "0.1.0", "latest release is 0.2.0", pip_spec=None)
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)
    result = CliRunner().invoke(cli, ["upgrade"])
    assert result.exit_code == 0
    assert "pipx upgrade coop-dax-review" in result.output


def test_removed_upgrade_flags_are_rejected():
    # --check / --yes were dropped when self-apply was removed; pin that they error.
    assert CliRunner().invoke(cli, ["upgrade", "--check"]).exit_code != 0
    assert CliRunner().invoke(cli, ["update", "--yes"]).exit_code != 0


def test_should_open_report_tri_state(monkeypatch):
    from coop_dax_review import cli as climod

    monkeypatch.setattr(climod, "_stdio_interactive", lambda: False)
    assert climod._should_open_report(True) is True  # explicit --open wins
    assert climod._should_open_report(False) is False  # explicit --no-open wins
    assert climod._should_open_report(None) is False  # auto -> follows the (non-)tty
    monkeypatch.setattr(climod, "_stdio_interactive", lambda: True)
    assert climod._should_open_report(None) is True


def test_html_does_not_open_browser_in_auto_mode_under_test(tmp_path, monkeypatch):
    import webbrowser

    calls: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: calls.append(a))
    report = tmp_path / "o.html"
    # No --open: auto mode + non-interactive runner -> must NOT open a browser.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "html", "-o", str(report)])
    assert result.exit_code == 0
    assert calls == []


def test_html_no_open_flag_suppresses_open(tmp_path, monkeypatch):
    import webbrowser

    calls: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: calls.append(a))
    report = tmp_path / "o.html"
    result = CliRunner().invoke(
        cli, ["check", str(FIXTURES), "--format", "html", "-o", str(report), "--no-open"]
    )
    assert result.exit_code == 0
    assert calls == []


def test_html_explicit_open_overrides_non_interactive(tmp_path, monkeypatch):
    import webbrowser

    calls: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: calls.append(a))
    report = tmp_path / "o.html"
    # Explicit --open overrides the interactive-terminal gate and opens the file URI.
    result = CliRunner().invoke(
        cli, ["check", str(FIXTURES), "--format", "html", "-o", str(report), "--open"]
    )
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0].startswith("file://")


def test_interactive_picker_partial_selection_returns_subset(tmp_path, monkeypatch):
    from coop_dax_review import cli as climod

    (tmp_path / "Sales.SemanticModel").mkdir()
    (tmp_path / "Finance.SemanticModel").mkdir()

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            pass

        def ask(self):  # the user kept only one of the two folders
            return [tmp_path / "Sales.SemanticModel"]

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox())
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))
    # A subset -> exactly those folders (NOT the root).
    assert climod._interactive_pick_paths(tmp_path) == [tmp_path / "Sales.SemanticModel"]


def test_interactive_picker_cancelled_returns_none(tmp_path, monkeypatch):
    from coop_dax_review import cli as climod

    (tmp_path / "Sales.SemanticModel").mkdir()
    (tmp_path / "Finance.SemanticModel").mkdir()

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            pass

        def ask(self):  # user pressed ESC / selected nothing
            return None

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox())
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))
    assert climod._interactive_pick_paths(tmp_path) is None
