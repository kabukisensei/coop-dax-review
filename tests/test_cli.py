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
    assert payload["schema_version"] == 3  # 3: the family identity rule (issue #14)
    assert set(payload["verdict"]) == {"clean", "highest_severity"}
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
            "fingerprint",
        }


def test_strict_exits_two_when_findings_remain():
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--strict"])
    assert result.exit_code == 2


def test_strict_exit_zero_when_filtered_below_threshold():
    # The fixtures emit only warnings/info; filtering to errors leaves none.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--strict", "--min-severity", "error"])
    assert result.exit_code == 0


def test_nonexistent_path_is_called_out_not_silently_clean():
    # A typo'd path must not look identical to a clean scan.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES / "nonexistent")])
    assert result.exit_code == 0
    assert "path not found" in result.output
    assert "No TMDL" not in result.output  # the path error explains it; don't double-message


def test_empty_dir_reports_no_models_found(tmp_path):
    result = CliRunner().invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code == 0
    assert "No models" in result.output


def test_malformed_tmdl_does_not_crash_the_run(monkeypatch):
    # A TMDL parse error must degrade to a diagnostic, never abort the run.
    from coop_dax_review import cli as climod

    def _boom(name, files):
        raise RuntimeError("boom")

    monkeypatch.setattr(climod, "parse_tmdl_model", _boom)
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert result.exit_code == 0  # advisory: never crash
    assert "could not parse TMDL" in result.output


def test_unknown_rule_id_in_config_warns(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-NOPE-NOT-A-RULE:\n    enabled: false\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)])
    assert result.exit_code == 0
    assert "unknown rule id 'DAX-NOPE-NOT-A-RULE'" in result.output


def test_agent_review_items_listed_in_terminal():
    out = CliRunner().invoke(cli, ["check", str(FIXTURES)]).output
    assert "Agent review (judgment required)" in out  # the section, not just the count
    assert "JUDGE" in out


def test_json_includes_models_checked():
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"]).output
    payload = json.loads(out)
    assert payload["models_checked"] >= 1


def test_build_catalogs_collects_raw_texts():
    from coop_dax_review.cli import build_catalogs, discover_inputs

    tmdl, bim, pbit, pbix = discover_inputs((str(FIXTURES),))
    texts: dict = {}
    build_catalogs(tmdl, bim, texts_out=texts)
    assert texts  # raw text captured so inline directives can be scanned
    assert any(k.endswith(".tmdl") or k.endswith(".bim") for k in texts)


def test_baseline_write_then_suppresses(tmp_path):
    bl = tmp_path / "bl.json"
    written = CliRunner().invoke(cli, ["check", str(FIXTURES), "--write-baseline", str(bl)])
    assert written.exit_code == 0 and bl.exists()
    # re-check against the baseline -> every known finding is suppressed
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--baseline", str(bl)]).output
    assert "no issues found" in out  # all findings suppressed (agent-review items still pass through)


def test_write_baseline_to_missing_dir_is_friendly_error(tmp_path):
    # A typo'd/unwritable --write-baseline path must fail with the family's
    # friendly one-line error, never a raw traceback (parity with the sql twin).
    target = tmp_path / "no-such-dir" / "base.json"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--write-baseline", str(target)])
    assert result.exit_code == 1
    assert "could not write baseline" in result.output
    assert "Traceback" not in result.output


def test_stale_baseline_entry_warns(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text('{"tool":"coop-dax-review","fingerprints":["deadbeef0000"]}\n', encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--baseline", str(bl)]).output
    assert "baseline:" in out and "no longer match" in out


def test_rule_threshold_configurable_via_params(tmp_path):
    # DAX-VAR-RETURN fires on the fixtures; raising its threshold via rules.yml silences it.
    base = json.loads(CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"]).output)
    assert any(f["rule_id"] == "DAX-VAR-RETURN" for f in base["findings"])
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-VAR-RETURN:\n    params:\n      min_functions: 99\n", encoding="utf-8")
    tuned = json.loads(
        CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg), "--format", "json"]).output
    )
    assert not any(f["rule_id"] == "DAX-VAR-RETURN" for f in tuned["findings"])


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
    # The decision now lives in core cliutils; the cli imports it unchanged.
    from coop_dax_review.cli import use_color

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert use_color(True, None) is True  # explicit --color
    assert use_color(False, None) is False  # explicit --no-color
    assert use_color(None, "out.txt") is False  # writing to a file -> never color
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(None, None) is False  # NO_COLOR wins in auto mode


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
    # The path is announced on STDERR (stdout stays the clean report artifact), as a
    # POSIX path (OS-stable; backslashes on Windows otherwise).
    assert "HTML report written to" in result.stderr
    assert report.resolve().as_posix() in result.stderr
    assert "HTML report written to" not in result.stdout  # stdout stays clean for a piped read


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

    plan = upmod.UpgradePlan(
        package_name="coop-dax-review",
        install_method="pipx",
        checkout=None,
        tool_installed="0.1.0",
        tool_note="already on the latest release (0.1.0)",
    )
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

    plan = upmod.UpgradePlan(
        package_name="coop-dax-review",
        install_method="pipx",
        checkout=None,
        tool_installed="0.1.0",
        tool_note="latest release is 0.2.0",
    )
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)
    result = CliRunner().invoke(cli, ["upgrade"])
    assert result.exit_code == 0
    assert "pipx upgrade coop-dax-review" in result.output


def test_removed_upgrade_yes_flag_is_rejected():
    # --yes (self-apply) was dropped for good; --check (status only) is kept
    # for parity with coop-sql-review — see tests/test_review_fixes.py.
    assert CliRunner().invoke(cli, ["upgrade", "--yes"]).exit_code != 0
    assert CliRunner().invoke(cli, ["update", "--yes"]).exit_code != 0


def test_should_open_report_tri_state(monkeypatch):
    # Core's two-arg variant: the fmt gate means only --format html can open a
    # browser; the tri-state --open/--no-open/auto behavior is unchanged.
    from coop_review_core import cliutils

    from coop_dax_review import cli as climod

    monkeypatch.setattr(cliutils, "stdio_interactive", lambda: False)
    assert climod.should_open_report("html", True) is True  # explicit --open wins
    assert climod.should_open_report("html", False) is False  # explicit --no-open wins
    assert climod.should_open_report("html", None) is False  # auto -> follows the (non-)tty
    assert climod.should_open_report("text", True) is False  # only HTML is browser-viewable
    monkeypatch.setattr(cliutils, "stdio_interactive", lambda: True)
    assert climod.should_open_report("html", None) is True


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


def _all_findings():
    """Every finding on the fixtures, as JSON dicts (deterministic order)."""
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"]).output
    return json.loads(out)["findings"]


def _unique_finding_with_plain_object():
    """The first finding whose rule-id fires exactly once AND whose object carries
    no ``: `` (a YAML mapping indicator). Suppressing it makes that rule-id vanish
    from the report, and its ``where`` round-trips cleanly through rules.yml. Both
    hold deterministically on the fixtures."""
    from collections import Counter

    findings = _all_findings()
    counts = Counter(f["rule_id"] for f in findings)
    for f in findings:
        if counts[f["rule_id"]] == 1 and ": " not in f["object"]:
            return f
    raise AssertionError("no single-firing rule with a plain object on the fixtures")


def test_html_and_md_extra_sinks_compose_with_text(tmp_path):
    # --html + --md are EXTRA sinks: the main text report still prints to the console.
    html = tmp_path / "r.html"
    md = tmp_path / "r.md"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--html", str(html), "--md", str(md)])
    assert result.exit_code == 0
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert md.read_text(encoding="utf-8").startswith("# coop-dax-review report")
    # the main text report is unaffected — a finding rule-id still shows on the console
    assert "DAX-" in result.output


def test_config_ignore_suppresses_all_findings(tmp_path):
    # Ignoring every fingerprint from a run leaves the report clean (agent-review
    # items still pass through, exactly like the baseline path).
    findings = _all_findings()
    entries = "".join(f"  - fingerprint: {f['fingerprint']}\n" for f in findings)
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n" + entries, encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)]).output
    for rule_id in {f["rule_id"] for f in findings}:
        assert rule_id not in out  # every ignored finding is gone
    assert "no issues found" in out  # the tool's clean phrasing


def test_config_ignore_suppresses_a_single_finding(tmp_path):
    finding = _unique_finding_with_plain_object()
    cfg = tmp_path / "rules.yml"
    cfg.write_text(f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)]).output
    assert finding["rule_id"] not in out  # the one ignored finding is gone


def test_stale_ignore_entry_warns(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - fingerprint: deadbeefdead\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)]).output
    assert "ignore:" in out and "no longer" in out


def test_save_ignores_full_loop_then_silenced(tmp_path, monkeypatch):
    from coop_dax_review.standards import RuleConfig
    from coop_dax_review import cli as climod

    findings = _all_findings()
    # Prove the round-trip specifically for a measure whose name uses the DAX
    # "[Category: Name]" house style — its ": " must survive rules.yml write+reload
    # (a bare emit would corrupt the file; core quotes it).
    colon = [f for f in findings if ": " in f["object"]]
    target = colon[0] if colon else findings[0]

    # An interactive-terminal only flow -> pretend we're at a TTY.
    monkeypatch.setattr(climod, "stdio_interactive", lambda: True)

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            self._values = k.get("choices", [])

        def ask(self):
            # The user checks every offered row. Real questionary returns only
            # Choice VALUES (lists of findings since the issue #15 grouping) —
            # never the Separator group headers, so filter those out here.
            return [v for v in self._values if isinstance(v, list)]

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox(**k))
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))

    cfg = tmp_path / "rules.yml"
    saved = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg), "--save-ignores"])
    assert saved.exit_code == 0
    assert cfg.exists()
    ignored = RuleConfig.load(cfg).ignored_fingerprints  # must re-parse without error
    assert target["fingerprint"] in ignored
    assert target["fingerprint"] in cfg.read_text(encoding="utf-8")
    # re-run against the now-populated ignore list -> every ignored finding is silenced
    out = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)]).output
    for rule_id in {f["rule_id"] for f in findings}:
        assert rule_id not in out
    assert "no issues found" in out


def test_save_ignores_no_terminal_writes_nothing(tmp_path, monkeypatch):
    from coop_dax_review import cli as climod

    monkeypatch.setattr(climod, "stdio_interactive", lambda: False)
    cfg = tmp_path / "rules.yml"
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg), "--save-ignores"])
    assert result.exit_code == 0
    assert "needs an interactive terminal" in result.output
    assert not cfg.exists()  # nothing written off-TTY


def test_cwd_rules_yml_is_auto_discovered(tmp_path, monkeypatch):
    # A rules.yml in the working directory is picked up with no --config flag
    # (the deprecated shared name still works everywhere it used to).
    monkeypatch.chdir(tmp_path)
    finding = _unique_finding_with_plain_object()
    (tmp_path / "rules.yml").write_text(
        f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8"
    )
    out = CliRunner().invoke(cli, ["check", str(FIXTURES)]).output
    assert finding["rule_id"] not in out  # auto-discovered ignore silenced it


# ---- unified config discovery (core discover_config; coop-review-core#12) ----


def test_env_var_names_the_config(tmp_path, monkeypatch):
    # COOP_DAX_REVIEW_CONFIG points a run (or a whole CI pipeline) at one config.
    finding = _unique_finding_with_plain_object()
    cfg = tmp_path / "team-config.yml"
    cfg.write_text(f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8")
    monkeypatch.setenv("COOP_DAX_REVIEW_CONFIG", str(cfg))
    out = CliRunner().invoke(cli, ["check", str(FIXTURES)]).output
    assert finding["rule_id"] not in out  # the env-var config applied


def test_env_var_missing_file_is_usage_error(monkeypatch):
    # A set-but-missing env var path is a misconfiguration, never a silent fallback.
    monkeypatch.setenv("COOP_DAX_REVIEW_CONFIG", "/nope/does-not-exist.yml")
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert result.exit_code == 2
    assert "COOP_DAX_REVIEW_CONFIG" in result.output


def test_tool_named_config_wins_over_rules_yml(tmp_path, monkeypatch):
    # coop-dax-review.yml is the preferred filename; a rules.yml in the same
    # directory is shadowed (with a note on stderr) — so a monorepo can configure
    # this tool and coop-sql-review side by side without fighting over one file.
    monkeypatch.chdir(tmp_path)
    finding = _unique_finding_with_plain_object()
    (tmp_path / "coop-dax-review.yml").write_text(
        f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8"
    )
    (tmp_path / "rules.yml").write_text("ignore:\n  - fingerprint: deadbeefdead\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert finding["rule_id"] not in result.stdout  # the tool-named config applied
    assert "shadowed" in result.stderr  # the losing rules.yml is called out
    assert "ignore_stale" not in result.stdout  # the rules.yml entry was never loaded


def test_config_discovered_by_parent_walk_up(tmp_path, monkeypatch):
    # A config in a parent directory applies when running from a subdirectory
    # (git-style walk-up), so one repo-root config covers every model folder.
    finding = _unique_finding_with_plain_object()
    (tmp_path / "coop-dax-review.yml").write_text(
        f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8"
    )
    nested = tmp_path / "models" / "sales"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    out = CliRunner().invoke(cli, ["check", str(FIXTURES)]).output
    assert finding["rule_id"] not in out  # the repo-root config applied


def test_rules_yml_discovery_prints_deprecation_note(tmp_path, monkeypatch):
    # Finding a config via the legacy shared name nudges toward the tool-named
    # file on stderr (rules.yml keeps working; the note is advisory).
    monkeypatch.chdir(tmp_path)
    finding = _unique_finding_with_plain_object()
    (tmp_path / "rules.yml").write_text(
        f"ignore:\n  - fingerprint: {finding['fingerprint']}\n", encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert "deprecated" in result.stderr and "coop-dax-review.yml" in result.stderr
    assert "deprecated" not in result.stdout  # the note never pollutes the report


def test_save_ignores_writes_back_to_the_discovered_config(tmp_path, monkeypatch):
    # The core config_write_path fix: --save-ignores appends to the config this
    # run actually READ (here: a standards-side rules.yml) instead of
    # unconditionally creating ./rules.yml — which would silently SHADOW the
    # real config on the next run.
    import shutil

    from coop_dax_review import cli as climod
    from coop_dax_review.standards import BUNDLED_STANDARDS

    std_dir = tmp_path / "standards"
    std_dir.mkdir()
    std = std_dir / "standards.md"
    shutil.copyfile(BUNDLED_STANDARDS, std)
    cfg = std_dir / "rules.yml"  # the conventional spot beside the standards file
    cfg.write_text("# team config\n", encoding="utf-8")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    monkeypatch.setattr(climod, "stdio_interactive", lambda: True)

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            self._values = k.get("choices", [])

        def ask(self):
            # Only Choice VALUES come back from real questionary (lists of
            # findings since the issue #15 grouping), never the Separators.
            return [v for v in self._values if isinstance(v, list)]

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox(**k))
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))

    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--standards", str(std), "--save-ignores"])
    assert result.exit_code == 0
    assert "ignore:" in cfg.read_text(encoding="utf-8")  # written back to what was read
    assert not (workdir / "rules.yml").exists()  # no shadowing ./rules.yml appeared


# ---- issue #15: baseline hint + grouped --save-ignores picker


def test_baseline_hint_when_many_findings(tmp_path, monkeypatch):
    # Above the threshold with no baseline flags -> one stderr nudge toward
    # the ratcheting workflow (--write-baseline / --baseline).
    from coop_dax_review import cli as climod

    monkeypatch.setattr(climod, "_BASELINE_HINT_THRESHOLD", 0)
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert "--write-baseline" in result.stderr
    assert "--write-baseline" not in result.stdout  # a hint, never report content


def test_no_baseline_hint_when_baseline_in_play(tmp_path, monkeypatch):
    from coop_dax_review import cli as climod

    monkeypatch.setattr(climod, "_BASELINE_HINT_THRESHOLD", 0)
    base = tmp_path / "baseline.json"
    written = CliRunner().invoke(cli, ["check", str(FIXTURES), "--write-baseline", str(base)])
    assert "Hint:" not in written.stderr  # writing the baseline IS the workflow
    reran = CliRunner().invoke(cli, ["check", str(FIXTURES), "--baseline", str(base)])
    assert "Hint:" not in reran.stderr


def test_no_baseline_hint_under_threshold():
    # The real threshold (50) is far above the fixture estate's finding count.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert "Hint:" not in result.stderr


def test_save_ignores_picker_groups_by_rule_and_model():
    # issue #15: the picker is grouped -- a Separator heads each rule x model
    # group, multi-finding groups get an "ignore all N" parent whose value is
    # the whole group, and every value is a LIST of findings.
    import questionary

    from coop_dax_review.cli import _ignore_picker_choices
    from coop_dax_review.finding import Finding

    def f(rule, model, obj):
        return Finding(rule, "warning", model, "t.tmdl", 1, obj, f"m {obj}", "§1")

    findings = [
        f("DAX-A", "M1", "[x]"),
        f("DAX-A", "M1", "[y]"),
        f("DAX-B", "M1", "[z]"),
    ]
    choices = _ignore_picker_choices(findings, questionary)
    separators = [c for c in choices if isinstance(c, questionary.Separator)]
    picks = [c for c in choices if not isinstance(c, questionary.Separator)]
    assert len(separators) == 2  # one per rule x model group
    assert "DAX-A" in separators[0].title and "(2 findings)" in separators[0].title
    parent = picks[0]
    assert "ignore all 2 DAX-A" in parent.title
    assert parent.value == findings[:2]  # the whole group
    assert all(isinstance(c.value, list) for c in picks)
    assert not any(c.checked for c in picks)  # opt-in: everything starts unchecked
    # the single-finding DAX-B group has NO "ignore all" parent
    assert not any("ignore all 1" in c.title for c in picks)


def test_pick_findings_dedupes_parent_and_child_overlap(monkeypatch):
    # Selecting a group's parent AND one of its members must not double-add.
    import questionary

    from coop_dax_review import cli as climod
    from coop_dax_review.finding import Finding

    def f(obj):
        return Finding("DAX-A", "warning", "M1", "t.tmdl", 1, obj, f"m {obj}", "§1")

    findings = [f("[x]"), f("[y]")]

    class _FakeCheckbox:
        def ask(self):
            return [findings, [findings[0]]]  # the parent group + one member again

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox())
    picked = climod._pick_findings_to_ignore(findings)
    assert picked == findings  # deduped by fingerprint, order preserved
