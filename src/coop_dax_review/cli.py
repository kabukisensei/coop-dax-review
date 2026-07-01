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
import yaml

from coop_dax_review import __version__
from coop_dax_review.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    FILE_UNREADABLE,
    IGNORE_STALE,
    PARSE_FAILED,
    SCAN_EMPTY,
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
    add_ignores,
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

    Explicit files must be ``.tmdl`` / ``.bim`` — anything else is skipped
    (``check`` calls the typo out on stderr) rather than "checked" as a
    phantom .bim model. Directories are searched recursively, skipping hidden
    directories. Each bucket is keyed by resolved path so a file reached via
    two overlapping roots (``.`` plus an absolute path, a symlink) is only
    checked once (mirrors coop-sql-review). Defaults to the current directory
    when none given.
    """
    roots = [Path(p) for p in paths] or [Path(".")]
    tmdl: dict[Path, Path] = {}
    bim: dict[Path, Path] = {}
    bucket_for = {".tmdl": tmdl, ".bim": bim}
    for root in roots:
        if root.is_file():
            bucket = bucket_for.get(root.suffix.lower())
            if bucket is not None:
                bucket.setdefault(root.resolve(), root)
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
                    bucket.setdefault(candidate.resolve(), candidate)
    return (
        sorted(tmdl.values(), key=lambda p: _display_path(p)),
        sorted(bim.values(), key=lambda p: _display_path(p)),
    )


def build_catalogs(
    tmdl_files: list[Path],
    bim_files: list[Path],
    texts_out: dict[str, str] | None = None,
    on_file=None,
) -> list[ModelCatalog]:
    """Parse discovered inputs into model catalogs.

    TMDL files are grouped per semantic model (keyed by the model's root
    directory, so same-named models stay distinct); each ``.bim`` is its own
    model. Unreadable/undecodable files and parse failures become diagnostics
    on the affected model, never crashes. If ``texts_out`` is given it is
    filled with ``{display_path: raw_text}`` (so the caller can scan inline
    directives without re-reading the files). ``on_file`` (optional) is ticked
    once per model file, for progress reporting.
    """
    catalogs: list[ModelCatalog] = []

    display = {p: _display_path(p) for p in tmdl_files}
    groups, unreadable = group_tmdl_files(tmdl_files, display, on_file=on_file)
    if texts_out is not None:
        for files in groups.values():
            texts_out.update(files)
    for model_name, disp, exc in unreadable:  # one bad file degrades only its model
        if isinstance(exc, UnicodeDecodeError):
            cat = ModelCatalog(name=model_name, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=PARSE_FAILED,
                    file=disp,
                    line=0,
                    message=(
                        f"could not decode {disp}: {exc} - the file must be UTF-8 (or UTF-16 with a BOM)"
                    ),
                )
            )
            catalogs.append(cat)
        else:
            catalogs.append(_unreadable_model(disp, exc))
    for key in sorted(groups):
        _root, model_name = key
        files = groups[key]
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
            if on_file is not None:
                on_file(disp)
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
        if on_file is not None:
            on_file(disp)
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


def _config_read_path(config_path, std_path):
    """Where to READ rules.yml from: --config if given, else a rules.yml in the
    current directory (so 'save an ignore, re-run, it is silenced' works with no
    flags), else the conventional spot beside the standards file."""
    if config_path:
        return Path(config_path)
    cwd_cfg = Path.cwd() / "rules.yml"
    if cwd_cfg.is_file():
        return cwd_cfg
    return default_config_path(std_path)


def _config_write_path(config_path):
    """Where to WRITE ignores: --config if given, else ./rules.yml (never the
    bundled standards directory inside the installed package)."""
    return Path(config_path) if config_path else Path.cwd() / "rules.yml"


def _load_rule_config(path: Path) -> RuleConfig:
    """``RuleConfig.load`` under the CLI's friendly-error contract.

    rules.yml is a hand-edited file (and auto-discovered from the cwd), so any
    problem in it — bad YAML, wrong shape, an unknown severity, a wrong encoding
    — must become a one-line usage error (exit 2) naming the file, never a
    traceback. A path that simply doesn't exist loads as the empty config; the
    explicit ``--config``-typo case is rejected earlier, in ``check``.
    (Mirrors the coop-sql-review twin.)
    """
    if not path.is_file():
        return RuleConfig()

    def _bad(problem: str) -> click.UsageError:
        return click.UsageError(f"could not load config {path}: {problem}")

    try:
        text = path.read_text(encoding="utf-8-sig")
        if "\x00" in text:  # UTF-16 without a BOM decodes as NUL-riddled "UTF-8"
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "null byte")
        data = yaml.safe_load(text)
    except UnicodeDecodeError:
        raise _bad("the file is not UTF-8 - re-save it as UTF-8 (PowerShell '>' writes UTF-16)") from None
    except yaml.YAMLError as exc:
        raise _bad(f"invalid YAML - {' '.join(str(exc).split())}") from exc
    except OSError as exc:
        raise _bad(str(exc)) from exc
    if data is not None and not isinstance(data, dict):
        raise _bad("the top level must be a mapping (e.g. a `rules:` section)")
    if isinstance(data, dict) and data.get("rules") is not None and not isinstance(data["rules"], dict):
        raise _bad("`rules:` must be a mapping of rule ids to settings, not a list")
    try:
        return RuleConfig.load(path)
    except StandardsError as exc:
        raise _bad(str(exc)) from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # Anything the shape checks above didn't anticipate (e.g. a malformed
        # `ignore:` entry) still surfaces as the same friendly one-liner.
        raise _bad(f"unexpected structure ({exc})") from exc


def _write_extra_report(path, content, label):
    """Write an extra report file (in addition to the main output) and announce
    its path on stderr. Never opens a browser — these are scriptable sinks."""
    target = Path(path)
    try:
        target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise click.ClickException(f"could not write report to {path}: {exc}") from exc
    click.echo(f"{label} report written to {target.resolve().as_posix()}", err=True)


def _finding_ignore_label(f):
    where = f"{f.model}/{f.object}" if f.object else (f"{f.file}:{f.line}" if f.line else f.file)
    msg = f.message if len(f.message) <= 70 else f.message[:69] + "..."
    return f"[{f.severity}] {f.rule_id}  {where}  {msg}"


def _finding_ignore_entry(f):
    where = f"{f.model}/{f.object}" if f.object else (f"{f.file}:{f.line}" if f.line else f.file)
    return {"fingerprint": f.fingerprint(), "rule": f.rule_id, "where": where}


def _pick_findings_to_ignore(findings):
    """Checkbox of findings to ignore (all start UNchecked -> opt-in). Returns the
    chosen findings, or [] if questionary is unavailable / nothing picked. Mirrors
    the error-handling of the existing _interactive_pick_paths helper."""
    try:
        import questionary
    except ImportError:
        return []
    choices = [questionary.Choice(title=_finding_ignore_label(f), value=f, checked=False) for f in findings]
    try:
        selected = questionary.checkbox(
            "Findings to add to the ignore list (SPACE to toggle, ENTER to confirm):", choices=choices
        ).ask()
    except (OSError, EOFError):
        return []
    return list(selected or [])


def _save_ignores_interactive(findings, config_path):
    """Let the user pick findings from this run to append to rules.yml's ignore
    list, so they are silenced on the next run. Interactive-terminal only."""
    if not findings:
        click.echo("Nothing to ignore: this run reported no findings.", err=True)
        return
    if not _stdio_interactive():
        click.echo("--save-ignores needs an interactive terminal; nothing written.", err=True)
        return
    selected = _pick_findings_to_ignore(findings)
    if not selected:
        click.echo("No findings selected; the ignore list is unchanged.", err=True)
        return
    target = _config_write_path(config_path)
    try:
        added = add_ignores(target, [_finding_ignore_entry(f) for f in selected])
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"could not update the ignore list in {target}: {exc}") from exc
    click.echo(
        f"Added {added} finding(s) to the ignore list in {target.resolve().as_posix()}; "
        "re-run to confirm they are silenced.",
        err=True,
    )


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
    "--html",
    "html_path",
    type=click.Path(),
    default=None,
    help="Also write a self-contained HTML report to this path (composes with any --format).",
)
@click.option(
    "--md",
    "--markdown",
    "md_path",
    type=click.Path(),
    default=None,
    help="Also write a Markdown report to this path (composes with any --format).",
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
    "--save-ignores",
    "save_ignores",
    is_flag=True,
    help="After the report, interactively pick findings to add to rules.yml's ignore list (silenced next run).",
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
    html_path: str | None,
    md_path: str | None,
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    save_ignores: bool,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check Power BI models (TMDL folders or .bim files) against the standards.

    Advisory only: it reports, it never edits or blocks (exit 0 unless --strict).

    \b
    Report output:
      The text report prints to the screen. To redirect or save it:
        --format text|json|markdown|html   choose the format (default: text)
        -o, --output FILE                  write that report to FILE
                                           (--format html always writes a file)
      To ALSO save shareable files in ONE run -- on top of whatever prints --
      add either or both (they compose with each other and with --format):
        --html FILE   a self-contained, branded HTML report
        --md FILE     a Markdown report
    \b
        coop-dax-review check ./MyModel.SemanticModel --html report.html --md report.md

    \b
    Ignoring findings you've accepted (advisory -- nothing is ever deleted):
      --save-ignores   After the report, pick findings from an interactive
                       checklist (SPACE toggles, ENTER confirms). The picks are
                       written to rules.yml and stay silenced on later runs:
    \b
        coop-dax-review check ./MyModel.SemanticModel --save-ignores   # tick to silence
        coop-dax-review check ./MyModel.SemanticModel                   # they no longer show
    \b
      The ignore list lives in rules.yml as an `ignore:` list of fingerprints
      (each with rule/where/note) -- editable by hand, and picked up
      automatically when rules.yml sits in the current directory (or pass
      --config FILE). You can also disable a whole rule in rules.yml, or drop an
      inline `// coop-dax-review:ignore RULE-ID` comment on the finding's line.
    """
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    # An EXPLICIT --config that doesn't exist is almost always a typo — silently
    # running with the default rules would drop the team's overrides/ignores.
    # (With --save-ignores the flag also names the file to CREATE, so a missing
    # file is legitimate there. Auto-discovery absence stays silent.)
    if config_path and not Path(config_path).is_file() and not save_ignores:
        raise click.UsageError(f"config file not found: {config_path}")
    cfg_path = _config_read_path(config_path, std_path)
    config = _load_rule_config(cfg_path)
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
    # So is an explicit file that isn't a model: without the callout it would be
    # "checked" as a phantom .bim and confuse models_checked.
    unsupported = [p for p in paths if Path(p).is_file() and Path(p).suffix.lower() not in (".tmdl", ".bim")]
    for p in unsupported:
        click.echo(f"not a TMDL (.tmdl) or .bim model file: {p}", err=True)

    tmdl_files, bim_files = discover_inputs(paths)
    if not tmdl_files and not bim_files and not missing and not unsupported:
        click.echo("No TMDL (.tmdl) or .bim models found.", err=True)
    # No early return: a zero-model scan still renders the full report in every
    # format/sink (models_checked=0 is the machine contract's own disambiguator),
    # with scan_empty diagnostics below making the empty scan machine-visible.

    # Stderr-only + TTY-gated, so it never pollutes the report (stdout) or a
    # redirected --output file — a big model folder no longer looks hung.
    progress = Progress(should_enable(quiet=False))
    progress.line(f"Checking {len(tmdl_files) + len(bim_files)} model file(s)...")
    raw_texts: dict[str, str] = {}
    with progress.bar("Parsing", total=len(tmdl_files) + len(bim_files)) as tick:
        catalogs = build_catalogs(tmdl_files, bim_files, texts_out=raw_texts, on_file=tick)
    result = run_rules(catalogs, rules)
    if not tmdl_files and not bim_files:
        # One scan_empty diagnostic per searched root, so an agent (or a CI log
        # reader) can tell a typo'd/empty path from a genuinely clean estate.
        for root in paths or (".",):
            if root in missing:
                problem = "path not found"
            elif root in unsupported:
                problem = "not a TMDL (.tmdl) or .bim model file"
            else:
                problem = "no TMDL (.tmdl) or .bim models found under this path"
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=SCAN_EMPTY,
                    file=Path(root).as_posix(),
                    line=0,
                    message=f"{problem} - nothing was checked (is the path right?)",
                )
            )
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
    # The full set of fingerprints this run produced (pre-baseline, pre-ignore) so a
    # stale ignore entry can be told from one another filter already consumed.
    present_fingerprints = {f.fingerprint() for f in result.findings}
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
    # rules.yml "ignore:" list — human-readable, fingerprint-matched suppressions
    # (like the baseline, but living in the one writable config file). Filtered before
    # the --min-severity floor, so an ignored finding is gone regardless of severity.
    if config.ignored_fingerprints:
        result.findings = [f for f in result.findings if f.fingerprint() not in config.ignored_fingerprints]
        stale = len(config.ignored_fingerprints - present_fingerprints)
        if stale:
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=IGNORE_STALE,
                    file=cfg_path.as_posix(),
                    line=0,
                    message=f"rules.yml ignore: {stale} entr{'y' if stale == 1 else 'ies'} no longer "
                    "match a current finding",
                )
            )
    # Always sort so the diagnostics order is deterministic regardless of which
    # suppression paths appended to it (matches coop-sql-review).
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
        # Announce on stderr so stdout stays clean for a piped/agent read (matches
        # every other report/log announcement and coop-sql-review).
        click.echo(f"HTML report written to {resolved.as_posix()}", err=True)
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

    if html_path:
        _write_extra_report(html_path, to_html(result, version=__version__, standards=standards), "HTML")
    if md_path:
        _write_extra_report(
            md_path, to_markdown(result, version=__version__, standards=standards) + "\n", "Markdown"
        )

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    if save_ignores:
        _save_ignores_interactive(result.findings, config_path)

    # --strict also fails when NOTHING was checked (models_checked == 0): a
    # typo'd path in CI must not pass as silently clean.
    if strict and (result.findings or result.models_checked == 0):
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


def _run_upgrade(check_only: bool) -> None:
    """Report version + dependency freshness, then print the exact command to run.

    The ONLY networked command (PyPI / `git fetch`). It never self-updates: a
    package manager can't reliably replace a program that is currently running
    (on Windows the console-script .exe is locked), so we show the command for
    the user to run in a fresh terminal after exiting. ``--check`` stops after
    the freshness report (status only — mirrors the coop-sql-review twin).
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
    if check_only:
        return
    commands = upgrade_command(plan)
    click.echo("\nThis tool does not update itself. To update, exit coop-dax-review and run:\n")
    for command in commands:
        click.echo(f"    {shlex.join(command)}")


_UPGRADE_OPTIONS = [
    click.option(
        "--check",
        "check_only",
        is_flag=True,
        help="Only report whether an update is available; don't print the upgrade command.",
    ),
]


def _with_upgrade_options(func):
    for option in reversed(_UPGRADE_OPTIONS):
        func = option(func)
    return func


@cli.command()
@_with_upgrade_options
def upgrade(check_only: bool) -> None:
    """Show how to update coop-dax-review (and check dependency freshness).

    The ONLY command that uses the network. Prints the exact command to run —
    the tool never replaces itself while running.
    """
    _run_upgrade(check_only)


@cli.command()
@_with_upgrade_options
def update(check_only: bool) -> None:
    """Alias for `upgrade` — show how to update coop-dax-review."""
    _run_upgrade(check_only)


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
