"""Command-line interface.

Thin wrapper over the pipeline (discover -> parse -> run rules -> render).
Advisory by default: exit code 0 no matter what is found. ``--strict`` is the
opt-in CI gate — exit 2 when any reported finding remains after the
``--min-severity`` filter.

Inputs are Power BI semantic models: a PBIP/TMDL model folder
(``*.SemanticModel/definition/...``, or any folder of ``.tmdl`` files) or a
legacy ``.bim`` file. Directories are searched recursively.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
from pathlib import Path

import click

from coop_dax_review import __version__
from coop_dax_review.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    FILE_UNREADABLE,
    PARSE_FAILED,
    Diagnostic,
)
from coop_dax_review.engine import run_rules
from coop_dax_review.finding import SEVERITIES
from coop_dax_review.model import ModelCatalog
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import group_tmdl_files, parse_tmdl_model
from coop_dax_review.progress import Progress, should_enable
from coop_dax_review.report import console_lines, json_text, log_text, to_html, to_markdown
from coop_dax_review.rules import all_rules
from coop_dax_review.suppressions import (
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)
from coop_dax_review.standards import (
    RuleConfig,
    StandardsError,
    apply_config,
    default_config_path,
    resolve_standards_path,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)

# Where an HTML report lands when the user doesn't pass -o: a discoverable,
# re-openable name in the working directory (overwritten on each run).
_DEFAULT_HTML_NAME = "coop-dax-review-report.html"


def _display_path(path: Path) -> str:
    """POSIX-style path, relative to cwd when possible (deterministic, OS-stable)."""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def discover_inputs(paths: tuple[str, ...]) -> tuple[list[Path], list[Path]]:
    """Expand paths into (sorted .tmdl files, sorted .bim files).

    Files are taken as-is; directories are searched recursively, skipping
    hidden directories. Defaults to the current directory when none given.
    """
    roots = [Path(p) for p in paths] or [Path(".")]
    tmdl: set[Path] = set()
    bim: set[Path] = set()
    bucket_for = {".tmdl": tmdl, ".bim": bim}
    for root in roots:
        if root.is_file():
            (tmdl if root.suffix.lower() == ".tmdl" else bim).add(root)
        elif root.is_dir():
            # Walk once and match on the lower-cased suffix so an uppercase
            # extension (Model.TMDL) is found identically on every OS — rglob's
            # own case handling differs between Windows and POSIX.
            for candidate in root.rglob("*"):
                bucket = bucket_for.get(candidate.suffix.lower())
                if bucket is None:
                    continue
                rel = candidate.relative_to(root)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if candidate.is_file():
                    bucket.add(candidate)
    return (
        sorted(tmdl, key=lambda p: _display_path(p)),
        sorted(bim, key=lambda p: _display_path(p)),
    )


def build_catalogs(
    tmdl_files: list[Path],
    bim_files: list[Path],
    texts_out: dict[str, str] | None = None,
) -> list[ModelCatalog]:
    """Parse discovered inputs into model catalogs.

    TMDL files are grouped per semantic model; each ``.bim`` is its own model.
    Unreadable files and parse failures become diagnostics on the affected
    model, never crashes. If ``texts_out`` is given it is filled with
    ``{display_path: raw_text}`` (so the caller can scan inline directives without
    re-reading the files).
    """
    catalogs: list[ModelCatalog] = []

    display = {p: _display_path(p) for p in tmdl_files}
    groups, unreadable = group_tmdl_files(tmdl_files, display)
    if texts_out is not None:
        for files in groups.values():
            texts_out.update(files)
    for _model_name, disp, exc in unreadable:
        catalogs.append(_unreadable_model(disp, exc))  # one bad file degrades only its model
    for model_name in sorted(groups):
        files = groups[model_name]
        try:
            catalogs.append(parse_tmdl_model(model_name, files))
        except Exception as exc:  # malformed TMDL / unexpected shape — degrade, never crash
            disp = next(iter(files), model_name)
            cat = ModelCatalog(name=model_name, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=PARSE_FAILED,
                    file=disp,
                    line=0,
                    message=f"could not parse TMDL model: {type(exc).__name__}: {exc}",
                )
            )
            catalogs.append(cat)

    for path in bim_files:
        disp = display.get(path) or _display_path(path)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            catalogs.append(_unreadable_model(disp, exc))
            continue
        if texts_out is not None:
            texts_out[disp] = text
        try:
            catalogs.append(parse_bim_model(disp, text))
        except Exception as exc:  # malformed JSON / unexpected shape
            cat = ModelCatalog(name=Path(disp).stem, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=PARSE_FAILED,
                    file=disp,
                    line=0,
                    message=f"could not parse .bim model: {type(exc).__name__}: {exc}",
                )
            )
            catalogs.append(cat)
    return catalogs


def _unreadable_model(disp: str, exc: Exception) -> ModelCatalog:
    cat = ModelCatalog(name=Path(disp).stem or disp, file=disp)
    cat.diagnostics.append(
        Diagnostic(
            severity="error",
            category=FILE_UNREADABLE,
            file=disp,
            line=0,
            message=f"could not read model file(s): {exc}",
        )
    )
    return cat


def _stdio_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _use_color(color_flag: bool | None, output_path: str | None) -> bool:
    """Whether to colorize the terminal report. An explicit ``--color`` /
    ``--no-color`` wins; otherwise auto: color only when writing to an
    interactive stdout (never to a file) and ``NO_COLOR`` is unset."""
    if color_flag is not None:
        return color_flag
    if output_path or os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _should_open_report(open_report: bool | None) -> bool:
    """Whether to open the HTML report in a browser. An explicit ``--open`` /
    ``--no-open`` always wins; otherwise it's automatic — open only when running
    in an interactive terminal (so CI / piped / agent runs never pop a browser).
    """
    if open_report is not None:
        return open_report
    return _stdio_interactive()


def _interactive_pick_paths(root: Path) -> list[Path] | None:
    """Let the user pick which subfolders to check via a checkbox.

    All folders start selected, so pressing ENTER checks everything (== scan
    the whole folder). Returns the chosen paths, or None to fall back to the
    default behavior — no subfolders, questionary unavailable, or cancelled.
    """
    try:
        subdirs = sorted(
            (d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")),
            key=lambda d: d.name,
        )
    except OSError:
        return None
    if not subdirs:
        return None
    try:
        import questionary
    except ImportError:
        return None
    choices = [questionary.Choice(title=f"{d.name}/", value=d, checked=True) for d in subdirs]
    try:
        selected = questionary.checkbox(
            "Folders to check (all selected; SPACE to toggle, ENTER to confirm):", choices=choices
        ).ask()
    except (OSError, EOFError):
        return None
    if not selected:
        return None
    # Everything selected -> scan the root (also catches loose top-level models).
    if len(selected) == len(subdirs):
        return [root]
    return list(selected)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="coop-dax-review")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Offline, advisory DAX/model standards linter for Power BI semantic models.

    Reports deviations from the DAX standards; never edits or blocks.
    Processing problems (unreadable files, rule errors) are reported as
    diagnostics in every run; use ``check --log-file`` to capture them.
    """
    ctx.ensure_object(dict)
    logging.getLogger("coop_dax_review").setLevel(logging.ERROR)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--standards", "standards_path", default=None, help="Path to the standards file (default: bundled)."
)
@click.option(
    "--config", "config_path", default=None, help="Path to a rules.yml (default: alongside standards)."
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "markdown", "html"]),
    default="text",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Write the report to this file instead of the screen (HTML always writes to a file).",
)
@click.option(
    "--open/--no-open",
    "open_report",
    default=None,
    help="Open the HTML report in your browser (default: auto - only in an interactive terminal).",
)
@click.option(
    "--color/--no-color",
    "color_flag",
    default=None,
    help="Colorize the text report (default: auto - only at an interactive terminal).",
)
@click.option(
    "--min-severity",
    type=_SEVERITY_CHOICE,
    default="info",
    show_default=True,
    help="Hide findings below this severity.",
)
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(),
    default=None,
    help="Suppress findings already recorded in this baseline file (only new ones surface).",
)
@click.option(
    "--write-baseline",
    "write_baseline_path",
    type=click.Path(),
    default=None,
    help="Write the current findings to this baseline file (ratchet setup), then report as usual.",
)
@click.option(
    "--log-file",
    "log_file",
    type=click.Path(),
    default=None,
    help="Write a diagnostics log (parse problems, rule errors) to this file.",
)
@click.option("--strict", is_flag=True, help="Exit 2 if any reported finding remains (opt-in CI gate).")
@click.pass_context
def check(
    ctx: click.Context,
    paths: tuple[str, ...],
    standards_path: str | None,
    config_path: str | None,
    fmt: str,
    output_path: str | None,
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check Power BI models (TMDL folders or .bim files) against the standards."""
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    cfg_path = Path(config_path) if config_path else default_config_path(std_path)
    config = RuleConfig.load(cfg_path)
    rules = apply_config(all_rules(), config)
    unknown_rules = config.unknown_rule_ids({r.id for r in all_rules()})

    # With no paths in an interactive terminal, offer a folder picker.
    if not paths and _stdio_interactive():
        picked = _interactive_pick_paths(Path("."))
        if picked is not None:
            paths = tuple(str(p) for p in picked)

    # A path the user typed that doesn't exist is almost always a typo — call it
    # out so it isn't silently indistinguishable from a clean scan.
    missing = [p for p in paths if not Path(p).exists()]
    for p in missing:
        click.echo(f"path not found: {p}", err=True)

    tmdl_files, bim_files = discover_inputs(paths)
    if not tmdl_files and not bim_files:
        if not missing:
            click.echo("No TMDL (.tmdl) or .bim models found.", err=True)
        return

    # Stderr-only + TTY-gated, so it never pollutes the report (stdout) or a
    # redirected --output file — a big model folder no longer looks hung.
    progress = Progress(should_enable(quiet=False))
    progress.line(f"Checking {len(tmdl_files) + len(bim_files)} model file(s)...")
    raw_texts: dict[str, str] = {}
    catalogs = build_catalogs(tmdl_files, bim_files, texts_out=raw_texts)
    result = run_rules(catalogs, rules)
    for rule_id in unknown_rules:
        result.diagnostics.append(
            Diagnostic(
                severity="warning",
                category=CONFIG_UNKNOWN_RULE,
                file=cfg_path.as_posix(),
                line=0,
                message=f"rules.yml: unknown rule id '{rule_id}' - ignored",
            )
        )

    # Suppressions: inline `coop-dax-review:ignore` directives (always), then a
    # fingerprint baseline (opt-in). Both run before the --min-severity floor so a
    # suppressed finding is gone regardless of severity.
    inline = {file: scan_directives(text) for file, text in raw_texts.items()}
    result.findings = [
        f for f in result.findings if not is_inline_suppressed(f.rule_id, f.line, inline.get(f.file, {}))
    ]
    if write_baseline_path:
        count = write_baseline(Path(write_baseline_path), [f.fingerprint() for f in result.findings])
        click.echo(f"Wrote baseline of {count} finding(s) to {write_baseline_path}", err=True)
    elif baseline_path:
        baseline_fps = load_baseline(Path(baseline_path))
        seen = {f.fingerprint() for f in result.findings}
        result.findings = [f for f in result.findings if f.fingerprint() not in baseline_fps]
        stale = len(baseline_fps - seen)
        if stale:
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=BASELINE_STALE,
                    file=Path(baseline_path).as_posix(),
                    line=0,
                    message=f"baseline: {stale} entr{'y' if stale == 1 else 'ies'} no longer match a "
                    "current finding; re-run --write-baseline to prune",
                )
            )
    if unknown_rules or (baseline_path and not write_baseline_path):
        result.diagnostics.sort(key=lambda d: d.sort_key())
    result = result.filtered(min_severity)

    standards = standards_info(std_path)
    use_color = fmt == "text" and _use_color(color_flag, output_path)
    if fmt == "json":
        rendered = json_text(result, version=__version__, standards=standards)
    elif fmt == "markdown":
        rendered = to_markdown(result, version=__version__, standards=standards) + "\n"
    elif fmt == "html":
        rendered = to_html(result, version=__version__, standards=standards)
    else:
        body = console_lines(result, version=__version__, standards=standards, color=use_color)
        rendered = "\n".join(body) + "\n"

    if fmt == "html":
        # HTML is meant to be viewed in a browser: always write it to a file (a
        # default name when -o is omitted), print the path, and open it.
        target = Path(output_path) if output_path else Path(_DEFAULT_HTML_NAME)
        try:
            target.write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {target}: {exc}") from exc
        resolved = target.resolve()
        click.echo(f"HTML report written to {resolved.as_posix()}")
        if _should_open_report(open_report):
            import webbrowser

            try:
                webbrowser.open(resolved.as_uri())
            except Exception:
                pass  # opening is a convenience; never fail the run over it
    elif output_path:
        try:
            Path(output_path).write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {output_path}: {exc}") from exc
        click.echo(f"Report written to {output_path}", err=True)
    else:
        click.echo(rendered, nl=False, color=use_color)

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    if strict and result.findings:
        sys.exit(2)


@cli.command(name="rules")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
def rules_cmd(fmt: str) -> None:
    """List every rule: id, severity, tier, and whether it needs the agent."""
    rules = all_rules()
    if fmt == "json":
        import json

        payload = [
            {
                "id": r.id,
                "title": r.title,
                "severity": r.severity,
                "category": r.category,
                "standard_ref": r.standard_ref,
                "tier": r.tier,
                "kind": r.kind,
                "default_enabled": r.default_enabled,
            }
            for r in rules
        ]
        click.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    click.echo(f"{len(rules)} rule(s) ('off' = disabled by default; enable in rules.yml):\n")
    for r in rules:
        tag = "agent" if r.kind == "agent" else r.severity
        off = "" if r.default_enabled else "  [off by default]"
        click.echo(f"  {r.id:28} [{tag:7}] T{r.tier} {r.standard_ref:5} {r.title}{off}")


def _run_upgrade() -> None:
    """Report version + dependency freshness, then print the exact command to run.

    The ONLY networked command (PyPI / `git fetch`). It never self-updates: a
    package manager can't reliably replace a program that is currently running
    (on Windows the console-script .exe is locked), so we show the command for
    the user to run in a fresh terminal after exiting.
    """
    from coop_dax_review.upgrade import build_plan, upgrade_command

    plan = build_plan()
    click.echo(f"coop-dax-review {plan.tool_installed} ({plan.install_method}) — {plan.tool_note}")
    if plan.dependencies:
        click.echo("\nDependencies:")
        for dep in plan.dependencies:
            latest = dep.latest or "?"
            label = {
                "current": "up to date",
                "safe": f"update available -> {latest}",
                "major": f"MAJOR update available -> {latest} (review before applying)",
                "unknown": "could not check (offline?)",
            }[dep.kind]
            click.echo(f"  {dep.name:20} {dep.installed:12} {label}")
    commands = upgrade_command(plan)
    click.echo("\nThis tool does not update itself. To update, exit coop-dax-review and run:\n")
    for command in commands:
        click.echo(f"    {shlex.join(command)}")


@cli.command()
def upgrade() -> None:
    """Show how to update coop-dax-review (and check dependency freshness).

    The ONLY command that uses the network. Prints the exact command to run —
    the tool never replaces itself while running.
    """
    _run_upgrade()


@cli.command()
def update() -> None:
    """Alias for `upgrade` — show how to update coop-dax-review."""
    _run_upgrade()


@cli.command(name="help")
@click.argument("command_name", required=False)
@click.pass_context
def help_cmd(ctx: click.Context, command_name: str | None) -> None:
    """Show help. `help` for everything, or `help <command>` (e.g. `help check`)."""
    parent = ctx.parent
    if command_name is None:
        click.echo(parent.get_help())
        return
    command = cli.get_command(ctx, command_name)
    if command is None:
        raise click.UsageError(f"unknown command '{command_name}' — try `coop-dax-review help`", ctx=parent)
    sub_ctx = click.Context(command, info_name=command_name, parent=parent)
    click.echo(command.get_help(sub_ctx))


def _force_utf8_console() -> None:
    """Emit UTF-8 on every platform so non-ASCII in messages (the § section
    marks, em-dashes) never raise UnicodeEncodeError on a legacy Windows
    console (cp1252/cp437). errors='replace' guarantees we never crash on
    output; worst case an old console shows a replacement glyph."""
    for stream in (sys.stdout, sys.stderr):
        try:
            # newline="" disables write-time \n -> \r\n translation, so the JSON
            # contract (and the text report) stay byte-identical (LF) across
            # OSes even when redirected to a file on Windows.
            stream.reconfigure(encoding="utf-8", errors="replace", newline="")
        except (AttributeError, ValueError, OSError):
            pass  # not a reconfigurable text stream (e.g. under test capture)


def main() -> None:
    """Console-script entrypoint: friendly one-line errors, 130 on Ctrl-C."""
    _force_utf8_console()
    try:
        cli(obj={}, standalone_mode=False)
    except click.exceptions.Abort:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)
    except click.exceptions.Exit as exc:  # --help / --version
        sys.exit(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
