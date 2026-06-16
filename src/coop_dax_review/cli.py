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
import sys
from pathlib import Path

import click

from coop_dax_review import __version__
from coop_dax_review.diagnostics import FILE_UNREADABLE, PARSE_FAILED, Diagnostic
from coop_dax_review.engine import run_rules
from coop_dax_review.finding import SEVERITIES
from coop_dax_review.model import ModelCatalog
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import group_tmdl_files, parse_tmdl_model
from coop_dax_review.report import console_lines, json_text, log_text
from coop_dax_review.rules import all_rules
from coop_dax_review.standards import (
    RuleConfig,
    StandardsError,
    apply_config,
    default_config_path,
    resolve_standards_path,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)


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


def build_catalogs(tmdl_files: list[Path], bim_files: list[Path]) -> list[ModelCatalog]:
    """Parse discovered inputs into model catalogs.

    TMDL files are grouped per semantic model; each ``.bim`` is its own model.
    Unreadable files and parse failures become diagnostics on the affected
    model, never crashes.
    """
    catalogs: list[ModelCatalog] = []

    display = {p: _display_path(p) for p in tmdl_files}
    groups, unreadable = group_tmdl_files(tmdl_files, display)
    for _model_name, disp, exc in unreadable:
        catalogs.append(_unreadable_model(disp, exc))  # one bad file degrades only its model
    for model_name in sorted(groups):
        catalogs.append(parse_tmdl_model(model_name, groups[model_name]))

    for path in bim_files:
        disp = display.get(path) or _display_path(path)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            catalogs.append(_unreadable_model(disp, exc))
            continue
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
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option(
    "--min-severity",
    type=_SEVERITY_CHOICE,
    default="info",
    show_default=True,
    help="Hide findings below this severity.",
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
    min_severity: str,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check Power BI models (TMDL folders or .bim files) against the standards."""
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    config = RuleConfig.load(Path(config_path) if config_path else default_config_path(std_path))
    rules = apply_config(all_rules(), config)

    tmdl_files, bim_files = discover_inputs(paths)
    if not tmdl_files and not bim_files:
        click.echo("No TMDL (.tmdl) or .bim models found.", err=True)
        return

    catalogs = build_catalogs(tmdl_files, bim_files)
    result = run_rules(catalogs, rules)
    result = result.filtered(min_severity)

    if fmt == "json":
        click.echo(json_text(result, version=__version__, standards=standards_info(std_path)), nl=False)
    else:
        for line in console_lines(result):
            click.echo(line)

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
            }
            for r in rules
        ]
        click.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    click.echo(f"{len(rules)} rule(s):\n")
    for r in rules:
        tag = "agent" if r.kind == "agent" else r.severity
        click.echo(f"  {r.id:28} [{tag:7}] T{r.tier} {r.standard_ref:5} {r.title}")


def _run_upgrade(check_only: bool, yes: bool) -> None:
    """Shared self-update behind both `upgrade` and `update` (the only networked path)."""
    from coop_dax_review.upgrade import UpgradeError, apply_plan, build_plan

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
    if check_only:
        return
    if not yes:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            click.echo("\nRe-run with --yes to apply in non-interactive environments.", err=True)
            return
        if not click.confirm("\nApply the update and any non-breaking dependency updates?", default=True):
            click.echo("Nothing changed.")
            return
    try:
        executed = apply_plan(plan)
    except UpgradeError as exc:
        raise click.ClickException(str(exc)) from exc
    for command in executed:
        click.echo(f"ran: {' '.join(command)}", err=True)
    click.echo("Done. Run `coop-dax-review --version` to confirm.")


_UPGRADE_OPTIONS = [
    click.option("--check", "check_only", is_flag=True, help="Report available updates; change nothing."),
    click.option("--yes", is_flag=True, help="Apply without asking for confirmation."),
]


def _with_upgrade_options(func):
    for option in reversed(_UPGRADE_OPTIONS):
        func = option(func)
    return func


@cli.command()
@_with_upgrade_options
def upgrade(check_only: bool, yes: bool) -> None:
    """Update coop-dax-review to the latest version (and safe dependency bumps).

    The ONLY command that uses the network. Major dependency jumps are
    reported but never auto-applied.
    """
    _run_upgrade(check_only, yes)


@cli.command()
@_with_upgrade_options
def update(check_only: bool, yes: bool) -> None:
    """Alias for `upgrade` — update coop-dax-review to the latest version."""
    _run_upgrade(check_only, yes)


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
