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

import difflib
import json
import logging
import os
import sys
from pathlib import Path

import click

from coop_review_core.cliutils import (
    apply_syntax_error_policy,
    config_write_path,
    display_path,
    force_utf8_console,
    run_upgrade,
    should_open_report,
    stdio_interactive,
    use_color,
    with_upgrade_options,
    write_extra_report,
)
from coop_review_core.delta import DeltaError, delta_text, diff_envelopes

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
from coop_dax_review.parsers.syntax_validation import validate_dax_syntax
from coop_dax_review.parsers.tmdl import decode_tmdl, group_tmdl_files, parse_tmdl_model
from coop_dax_review.progress import Progress, should_enable
from coop_dax_review.report import (
    console_lines,
    json_text,
    log_text,
    to_html,
    to_json,
    to_markdown,
    to_sarif,
)
from coop_dax_review.rules import all_rules, rule_docs
from coop_dax_review.suppressions import (
    TOOL,
    BaselineError,
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
    discover_config,
    load_config_friendly,
    parse_syntax_errors_knob,
    resolve_standards_path,
    section_text,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)

# Where an HTML report lands when the user doesn't pass -o: a discoverable,
# re-openable name in the working directory (overwritten on each run).
_DEFAULT_HTML_NAME = "coop-dax-review-report.html"

# Above this many findings with no --baseline in play, nudge a first-time run
# toward the ratcheting workflow (issue #15) — the intended adoption path for a
# legacy estate is baseline-then-fix-new, not read-a-6000-line-wall.
_BASELINE_HINT_THRESHOLD = 50

# This package's directory: config writes must never land inside the installed
# package (where the bundled-standards sibling rules.yml would live).
_PACKAGE_DIR = Path(__file__).resolve().parent


def discover_inputs(paths: tuple[str, ...]) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
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
    pbit: dict[Path, Path] = {}
    pbix: dict[Path, Path] = {}
    bucket_for = {".tmdl": tmdl, ".bim": bim, ".pbit": pbit, ".pbix": pbix}
    for root in roots:
        if root.is_file():
            bucket = bucket_for.get(root.suffix.lower())
            if bucket is not None:
                bucket.setdefault(root.resolve(), root)
            elif root.suffix.lower() == ".pbix":
                pbix.setdefault(root.resolve(), root)
        elif root.is_dir():
            for candidate in root.rglob("*"):
                bucket = bucket_for.get(candidate.suffix.lower())
                if bucket is None:
                    if candidate.suffix.lower() == ".pbix":
                        pbix.setdefault(candidate.resolve(), candidate)
                    continue
                rel = candidate.relative_to(root)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if candidate.is_file():
                    bucket.setdefault(candidate.resolve(), candidate)
    return (
        sorted(tmdl.values(), key=lambda p: display_path(p)),
        sorted(bim.values(), key=lambda p: display_path(p)),
        sorted(pbit.values(), key=lambda p: display_path(p)),
        sorted(pbix.values(), key=lambda p: display_path(p)),
    )


def build_catalogs(
    tmdl_files: list[Path],
    bim_files: list[Path],
    pbit_files: list[Path] = None,
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

    display = {p: display_path(p) for p in tmdl_files}
    groups, unreadable = group_tmdl_files(tmdl_files, display, on_file=on_file)
    if texts_out is not None:
        for files in groups.values():
            texts_out.update(files)
    for model_name, disp, exc in unreadable:  # one bad file degrades only its model
        if isinstance(exc, UnicodeDecodeError):
            # An undecodable file (bad UTF-8, or UTF-16 saved without a BOM -> NUL-riddled)
            # contributed NOTHING to the catalog, exactly like an unreadable one — so it is
            # an error-severity file_unreadable, not a warning. Otherwise a model whose only
            # file is mojibake would pass --strict / verdict as clean (issue #1, SQL-twin
            # parity: coverage of that file is lost).
            cat = ModelCatalog(name=model_name, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="error",
                    category=FILE_UNREADABLE,
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
        disp = display.get(path) or display_path(path)
        try:
            # BOM-aware decode with the same NUL guard as the TMDL path: reading
            # with errors="replace" would mask an undecodable .bim (e.g. UTF-16
            # without a BOM) as mojibake that then fails json.loads and degrades
            # to a warning PARSE_FAILED — so a model whose only file is an
            # unreadable .bim would report verdict clean and pass --strict, while
            # the identical TMDL case fails strict (issue #23). A decode failure
            # is coverage lost, exactly like an unreadable file -> error-severity
            # file_unreadable (issue #1). Genuine JSON syntax errors stay a
            # warning PARSE_FAILED below, matching the TMDL parse-failure policy.
            text = decode_tmdl(path.read_bytes())
        except OSError as exc:
            catalogs.append(_unreadable_model(disp, exc))
            if on_file is not None:
                on_file(disp)
            continue
        except UnicodeDecodeError as exc:
            cat = ModelCatalog(name=Path(disp).stem or disp, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="error",
                    category=FILE_UNREADABLE,
                    file=disp,
                    line=0,
                    message=(
                        f"could not decode {disp}: {exc} - the file must be UTF-8 (or UTF-16 with a BOM)"
                    ),
                )
            )
            catalogs.append(cat)
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

    pbit_files = pbit_files or []
    for path in pbit_files:
        disp = display.get(path) or display_path(path)
        try:
            from coop_dax_review.parsers.pbit import parse_pbit_model

            catalogs.append(parse_pbit_model(disp))
        except Exception as exc:
            cat = ModelCatalog(name=Path(disp).stem, file=disp)
            cat.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=PARSE_FAILED,
                    file=disp,
                    line=0,
                    message=f"could not parse .pbit model: {type(exc).__name__}: {exc}",
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


def _discover_config_path(config_path: str | None, save_ignores: bool, std_path: Path) -> Path:
    """Which config file this run reads, via core ``discover_config`` (issue #12):

    1. ``--config`` if given (a missing file is a friendly usage error — a typo
       must not silently drop the team's overrides/ignores. With ``--save-ignores``
       the flag also names the file to CREATE, so a missing file is legitimate
       there and skips discovery entirely).
    2. The ``COOP_DAX_REVIEW_CONFIG`` env var (points a whole CI pipeline at one
       config without threading ``--config`` through every call site).
    3. A git-style walk from the cwd up through its parents: in each directory
       ``coop-dax-review.yml`` (the tool-named config) first, then ``rules.yml``
       as the DEPRECATED shared fallback — so a monorepo can configure this tool
       and coop-sql-review side by side without the two fighting over one file.
       The walk stops at the repository root (a ``.git`` entry).
    4. The conventional spot beside the standards file.

    Discovery notes (the rules.yml deprecation nudge, a shadowed-file warning)
    surface on stderr — core never prints.
    """
    if config_path and save_ignores and not Path(config_path).is_file():
        return Path(config_path)  # the file --save-ignores will create
    try:
        discovered = discover_config(
            TOOL,
            explicit=config_path,
            env=os.environ,
            start=Path.cwd(),
            bundled_default=default_config_path(std_path),
        )
    except StandardsError as exc:
        raise click.UsageError(str(exc)) from exc
    for note in discovered.notes:
        click.echo(note, err=True)
    return discovered.path or default_config_path(std_path)


def _load_rule_config(path: Path) -> tuple[RuleConfig, str]:
    """Core ``load_config_friendly`` (plus the ``syntax_errors`` knob) under the
    CLI's friendly-error contract.

    Returns ``(config, syntax_errors_mode)`` where the mode is one of
    ``error``/``warning``/``off`` (default ``error``) — how to treat a genuine
    DAX syntax error (unbalanced parens/brackets, an unterminated
    string/comment, an empty body).

    rules.yml is a hand-edited file (and auto-discovered), so any problem in it
    — bad YAML, wrong shape, an unknown severity or ``syntax_errors`` value, a
    wrong encoding — must become a one-line usage error (exit 2) naming the
    file, never a traceback. A path that simply doesn't exist loads as the
    empty config; the explicit ``--config``-typo case is rejected earlier, in
    ``check``. (Mirrors the coop-sql-review twin.)
    """

    def _bad(problem: str) -> click.UsageError:
        return click.UsageError(f"could not load config {path}: {problem}")

    try:
        config, data = load_config_friendly(path)
    except StandardsError as exc:
        raise _bad(str(exc)) from exc
    syntax_mode = "error"
    if data.get("syntax_errors") is not None:
        try:
            syntax_mode = parse_syntax_errors_knob(data["syntax_errors"])
        except StandardsError as exc:
            raise _bad(str(exc)) from exc
    return config, syntax_mode


def _finding_ignore_label(f):
    where = f"{f.model}/{f.object}" if f.object else (f"{f.file}:{f.line}" if f.line else f.file)
    msg = f.message if len(f.message) <= 70 else f.message[:69] + "..."
    return f"[{f.severity}] {f.rule_id}  {where}  {msg}"


def _finding_ignore_entry(f):
    where = f"{f.model}/{f.object}" if f.object else (f"{f.file}:{f.line}" if f.line else f.file)
    return {"fingerprint": f.fingerprint(), "rule": f.rule_id, "where": where}


def _ignore_picker_choices(findings, questionary):
    """The ``--save-ignores`` checkbox, grouped by rule x model (issue #15): a
    separator heads each group, an "ignore all N" parent row precedes the
    individual findings of a multi-finding group, and every row starts
    UNchecked (opt-in). Choice VALUES are lists of findings so a parent pick
    means the whole group; the caller flattens + dedupes. A flat 500-row list
    was unusable at estate scale — the grouped form scales with rule count."""
    groups: dict[tuple[str, str], list] = {}
    for f in findings:
        groups.setdefault((f.rule_id, f.model), []).append(f)
    choices: list = []
    for (rule_id, model), members in sorted(groups.items()):
        n = len(members)
        choices.append(questionary.Separator(f"-- {rule_id} - {model} ({n} finding{'s' if n != 1 else ''})"))
        if n > 1:
            choices.append(
                questionary.Choice(
                    title=f"ignore all {n} {rule_id} findings in {model}", value=members, checked=False
                )
            )
        for f in members:
            choices.append(
                questionary.Choice(title="  " + _finding_ignore_label(f), value=[f], checked=False)
            )
    return choices


def _pick_findings_to_ignore(findings):
    """Checkbox of findings to ignore (grouped by rule x model, all start
    UNchecked -> opt-in). Returns the chosen findings (flattened, deduped by
    fingerprint), or [] if questionary is unavailable / nothing picked. Mirrors
    the error-handling of the existing _interactive_pick_paths helper."""
    try:
        import questionary
    except ImportError:
        return []
    choices = _ignore_picker_choices(findings, questionary)
    try:
        selected = questionary.checkbox(
            "Findings to add to the ignore list (SPACE to toggle, ENTER to confirm):", choices=choices
        ).ask()
    except (OSError, EOFError):
        return []
    picked: list = []
    seen: set[str] = set()
    for group in selected or []:
        for f in group:
            fingerprint = f.fingerprint()
            if fingerprint not in seen:
                seen.add(fingerprint)
                picked.append(f)
    return picked


def _save_ignores_interactive(findings, config_path, cfg_path: Path):
    """Let the user pick findings from this run to append to rules.yml's ignore
    list, so they are silenced on the next run. Interactive-terminal only.
    ``cfg_path`` is the config this run READ from, so the ignore is written back
    to it (not a shadowing ./rules.yml) — see core ``config_write_path``."""
    if not findings:
        click.echo("Nothing to ignore: this run reported no findings.", err=True)
        return
    if not stdio_interactive():
        click.echo("--save-ignores needs an interactive terminal; nothing written.", err=True)
        return
    selected = _pick_findings_to_ignore(findings)
    if not selected:
        click.echo("No findings selected; the ignore list is unchanged.", err=True)
        return
    target = config_write_path(config_path, cfg_path, package_dir=_PACKAGE_DIR)
    try:
        added = add_ignores(target, [_finding_ignore_entry(f) for f in selected])
    except (StandardsError, OSError, ValueError) as exc:
        # core 0.5.0's add_ignores raises StandardsError (a CoopReviewError, not an
        # OSError/ValueError) for an unreadable/unwritable/invalid target; keep OSError
        # + ValueError too as belt-and-braces so this exits 1 with one line, never a traceback.
        raise click.ClickException(f"could not update the ignore list in {target}: {exc}") from exc
    click.echo(
        f"Added {added} finding(s) to the ignore list in {target.resolve().as_posix()}; "
        "re-run to confirm they are silenced.",
        err=True,
    )


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
    "--config",
    "config_path",
    default=None,
    help="Path to a config file (default: $COOP_DAX_REVIEW_CONFIG, else a "
    "coop-dax-review.yml or rules.yml found from the current directory upward, "
    "else alongside standards).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "markdown", "html", "sarif"]),
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
    "--sarif",
    "sarif_path",
    type=click.Path(),
    default=None,
    help="Also write a SARIF 2.1.0 report to this path (for GitHub/ADO PR annotations; composes with any --format).",
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
@click.option(
    "--diff-against",
    "diff_against",
    type=click.Path(),
    default=None,
    help="Compare this run against a previous run's JSON envelope (a saved --format json "
    "report): print a new / fixed / persisting delta to stderr. Advisory - never changes the "
    "exit code.",
)
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
    sarif_path: str | None,
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    save_ignores: bool,
    log_file: str | None,
    strict: bool,
    diff_against: str | None,
) -> None:
    """Check Power BI models (TMDL folders or .bim files) against the standards.

    Advisory only: it reports, it never edits or blocks (exit 0 unless --strict).

    \b
    Report output:
      The text report prints to the screen. To redirect or save it:
        --format text|json|markdown|html|sarif   choose the format (default: text)
                                           (sarif = GitHub/ADO PR annotations)
        -o, --output FILE                  write that report to FILE
                                           (--format html always writes a file)
      To ALSO save shareable files in ONE run -- on top of whatever prints --
      add any of these (they compose with each other and with --format):
        --html FILE    a self-contained, branded HTML report
        --md FILE      a Markdown report
        --sarif FILE   a SARIF 2.1.0 report (GitHub/ADO PR annotations)
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
      The ignore list lives in the config file as an `ignore:` list of
      fingerprints (each with rule/where/note) -- editable by hand, and picked
      up automatically when a coop-dax-review.yml (preferred) or rules.yml
      (deprecated shared name) sits in the current directory or any parent up
      to the repo root (or pass --config FILE / set COOP_DAX_REVIEW_CONFIG).
      You can also disable a whole rule there, or drop an inline
      `// coop-dax-review:ignore RULE-ID` comment on the finding's line.
    """
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    # Config discovery (core `discover_config`): --config, else the
    # COOP_DAX_REVIEW_CONFIG env var, else coop-dax-review.yml / rules.yml on a
    # walk from the cwd up to the repo root, else beside the standards file. An
    # EXPLICIT --config that doesn't exist is almost always a typo — a friendly
    # usage error (unless --save-ignores names it as the file to create).
    cfg_path = _discover_config_path(config_path, save_ignores, std_path)
    config, syntax_mode = _load_rule_config(cfg_path)
    rules = apply_config(all_rules(), config)
    unknown_rules = config.unknown_rule_ids({r.id for r in all_rules()})

    # With no paths in an interactive terminal, offer a folder picker.
    if not paths and stdio_interactive():
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
    unsupported = [
        p
        for p in paths
        if Path(p).is_file() and Path(p).suffix.lower() not in (".tmdl", ".bim", ".pbit", ".pbix")
    ]
    for p in unsupported:
        click.echo(f"not a model file (.tmdl, .bim, .pbit, .pbix): {p}", err=True)

    tmdl_files, bim_files, pbit_files, pbix_files = discover_inputs(paths)
    if (
        not tmdl_files
        and not bim_files
        and not pbit_files
        and not pbix_files
        and not missing
        and not unsupported
    ):
        click.echo("No models (.tmdl, .bim, .pbit, .pbix) found.", err=True)
    # No early return: a zero-model scan still renders the full report in every
    # format/sink (models_checked=0 is the machine contract's own disambiguator),
    # with scan_empty diagnostics below making the empty scan machine-visible.

    # Stderr-only + TTY-gated, so it never pollutes the report (stdout) or a
    # redirected --output file — a big model folder no longer looks hung.
    progress = Progress(should_enable(quiet=False))
    progress.line(
        f"Checking {len(tmdl_files) + len(bim_files) + len(pbit_files) + len(pbit_files) + len(pbix_files)} model file(s)..."
    )
    raw_texts: dict[str, str] = {}
    with progress.bar("Parsing", total=len(tmdl_files) + len(bim_files) + len(pbit_files)) as tick:
        catalogs = build_catalogs(tmdl_files, bim_files, pbit_files, texts_out=raw_texts, on_file=tick)
    result = run_rules(catalogs, rules)
    for pbix in pbix_files:
        result.diagnostics.append(
            Diagnostic(
                severity="warning",
                category="pbix_opaque_model",
                file=str(pbix),
                line=0,
                message="cannot parse .pbix files (opaque model) - export to .pbit or PBIP format instead",
            )
        )

    # Cheap STRUCTURAL DAX validation (unbalanced parens/brackets, an unterminated
    # string/comment, an empty body) over every measure + calculated column —
    # error-severity SYNTAX_ERROR diagnostics, an orthogonal pass after the rules
    # (the rules still run on whatever parsed; this is drift DETECTION, not a
    # gate). The `syntax_errors` knob + inline `ignore syntax` are applied below,
    # after inline-directive filtering, mirroring the coop-sql-review twin.
    result.diagnostics.extend(validate_dax_syntax(catalogs))
    if not tmdl_files and not bim_files and not pbit_files and not pbix_files:
        # One scan_empty diagnostic per searched root, so an agent (or a CI log
        # reader) can tell a typo'd/empty path from a genuinely clean estate.
        for root in paths or (".",):
            if root in missing:
                problem = "path not found"
            elif root in unsupported:
                problem = "not a model file (.tmdl, .bim, .pbit, .pbix)"
            else:
                problem = "no models (.tmdl, .bim, .pbit, .pbix) found under this path"
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
    result.agent_review = [
        a for a in result.agent_review if not is_inline_suppressed(a.rule_id, a.line, inline.get(a.file, {}))
    ]

    # Syntax-error diagnostics (structurally invalid DAX) obey the rules.yml
    # `syntax_errors` knob and an inline `coop-dax-review:ignore syntax` directive
    # on the error's line or the line above. `off` (or an inline ignore) removes
    # the diagnostic; `warning` demotes but keeps it visible; `error` (default)
    # leaves it — where issue #1 then flips --strict / the verdict for free.
    result.diagnostics = apply_syntax_error_policy(result.diagnostics, syntax_mode, raw_texts, TOOL)
    # The full set of fingerprints this run produced (pre-baseline, pre-ignore) so a
    # stale ignore entry can be told from one another filter already consumed. An
    # entry matching only an agent-review item is NOT stale.
    present_fingerprints = {f.fingerprint() for f in result.findings} | {
        a.fingerprint() for a in result.agent_review
    }
    if write_baseline_path:
        try:
            count = write_baseline(Path(write_baseline_path), sorted(present_fingerprints))
        except OSError as exc:
            raise click.ClickException(f"could not write baseline to {write_baseline_path}: {exc}") from exc
        click.echo(
            f"Wrote baseline of {count} finding/agent-review entr{'y' if count == 1 else 'ies'} "
            f"to {write_baseline_path}",
            err=True,
        )
    elif baseline_path:
        # A corrupt/missing/wrong-tool baseline is a friendly usage error (exit 2),
        # not a silent empty set that floods every baselined finding back.
        try:
            baseline_fps = load_baseline(Path(baseline_path))
        except BaselineError as exc:
            raise click.UsageError(str(exc)) from exc
        result.findings = [f for f in result.findings if f.fingerprint() not in baseline_fps]
        result.agent_review = [a for a in result.agent_review if a.fingerprint() not in baseline_fps]
        stale = len(baseline_fps - present_fingerprints)
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
        result.agent_review = [
            a for a in result.agent_review if a.fingerprint() not in config.ignored_fingerprints
        ]
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
    colorize = fmt == "text" and use_color(color_flag, output_path)
    if fmt == "json":
        rendered = json_text(result, version=__version__, standards=standards)
    elif fmt == "markdown":
        rendered = to_markdown(result, version=__version__, standards=standards) + "\n"
    elif fmt == "html":
        rendered = to_html(result, version=__version__, standards=standards)
    elif fmt == "sarif":
        # Like json: renders to stdout unless -o is given (SARIF is file-oriented but a
        # stdout dump pipes fine and keeps parity with the other machine formats).
        rendered = to_sarif(result, version=__version__, standards=standards)
    else:
        body = console_lines(result, version=__version__, standards=standards, color=colorize)
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
        if should_open_report(fmt, open_report):
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
        click.echo(rendered, nl=False, color=colorize)

    if html_path:
        write_extra_report(html_path, to_html(result, version=__version__, standards=standards), "HTML")
    if md_path:
        write_extra_report(
            md_path, to_markdown(result, version=__version__, standards=standards) + "\n", "Markdown"
        )
    if sarif_path:
        write_extra_report(sarif_path, to_sarif(result, version=__version__, standards=standards), "SARIF")

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    # First-run-on-a-legacy-estate nudge (issue #15): with many findings and no
    # baseline in play, point at the ratcheting workflow. One stderr line, never
    # in the report itself.
    if len(result.findings) > _BASELINE_HINT_THRESHOLD and not baseline_path and not write_baseline_path:
        click.echo(
            f"Hint: {len(result.findings)} findings. For a legacy estate, ratchet instead of reading "
            "the wall: `--write-baseline baseline.json` once, then `--baseline baseline.json` on "
            "later runs surfaces only NEW findings.",
            err=True,
        )

    if save_ignores:
        _save_ignores_interactive(result.findings, config_path, cfg_path)

    # --diff-against: compare this run to a previous run's saved JSON envelope and print
    # a new / fixed / persisting delta to stderr (core's shared delta engine). Advisory —
    # the exit code is never changed. The current envelope is this run's report (after
    # suppressions + the --min-severity floor). A missing / non-JSON / wrong-tool file is a
    # friendly usage error (exit 2), mirroring --baseline.
    if diff_against:
        try:
            old_envelope = json.loads(Path(diff_against).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise click.UsageError(f"--diff-against: cannot read {diff_against}: {exc}") from exc
        except ValueError as exc:
            raise click.UsageError(f"--diff-against: {diff_against} is not valid JSON: {exc}") from exc
        if not isinstance(old_envelope, dict):
            raise click.UsageError(
                f"--diff-against: {diff_against} is not a review envelope (expected a JSON object)"
            )
        try:
            delta = diff_envelopes(old_envelope, to_json(result, version=__version__, standards=standards))
        except DeltaError as exc:
            raise click.UsageError(str(exc)) from exc
        click.echo(delta_text(delta, color=colorize), err=True, nl=False)

    # --strict also fails when NOTHING was checked (models_checked == 0): a
    # typo'd path in CI must not pass as silently clean. It ALSO fails on any
    # remaining error-severity diagnostic (an unreadable model, a rule crash, a
    # syntax error) — the tool's coverage is compromised, so a zero-findings run
    # over an unreadable file must never pass CI as clean.
    has_error_diagnostic = any(d.severity == "error" for d in result.diagnostics)
    if strict and (result.findings or result.models_checked == 0 or has_error_diagnostic):
        sys.exit(2)


@cli.command(name="diff")
@click.argument("old_json", type=click.Path(exists=True))
@click.argument("new_json", type=click.Path(exists=True))
@click.option(
    "--md",
    "--markdown",
    "md_path",
    type=click.Path(),
    default=None,
    help="Also write a Markdown report to this path.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(),
    default=None,
    help="Also write a self-contained HTML report to this path.",
)
@click.option(
    "--color/--no-color",
    "color_flag",
    default=None,
    help="Colorize the text report (default: auto - only at an interactive terminal).",
)
def diff_cmd(
    old_json: str, new_json: str, md_path: str | None, html_path: str | None, color_flag: bool | None
) -> None:
    """Compare two review JSON reports and show the delta (fixed / new / unchanged)."""
    import json
    from coop_review_core.cliutils import use_color, write_extra_report
    from coop_review_core.delta import DeltaError, delta_markdown, diff_envelopes
    from coop_dax_review.report import delta_html

    try:
        old_envelope = json.loads(Path(old_json).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise click.UsageError(f"cannot read {old_json}: {exc}") from exc
    except ValueError as exc:
        raise click.UsageError(f"{old_json} is not valid JSON: {exc}") from exc

    try:
        new_envelope = json.loads(Path(new_json).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise click.UsageError(f"cannot read {new_json}: {exc}") from exc
    except ValueError as exc:
        raise click.UsageError(f"{new_json} is not valid JSON: {exc}") from exc

    if not isinstance(old_envelope, dict):
        raise click.UsageError(f"{old_json} is not a review envelope (expected a JSON object)")
    if not isinstance(new_envelope, dict):
        raise click.UsageError(f"{new_json} is not a review envelope (expected a JSON object)")

    try:
        delta = diff_envelopes(old_envelope, new_envelope)
    except DeltaError as exc:
        raise click.UsageError(str(exc)) from exc

    colorize = use_color(color_flag, None)
    click.echo(delta_text(delta, color=colorize), nl=False)

    if html_path:
        # Re-parse version from envelope or fallback
        version = str(new_envelope.get("version") or __version__)
        html_str = delta_html(delta, version=version)
        write_extra_report(html_path, html_str, "HTML")
    if md_path:
        md_str = delta_markdown(delta)
        write_extra_report(md_path, md_str, "Markdown")


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


@cli.command()
@click.argument("rule_id")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option(
    "--color/--no-color",
    "color_flag",
    default=None,
    help="Colorize the explanation (default: auto — only at an interactive terminal).",
)
@click.option(
    "--standards",
    "standards_path",
    type=click.Path(),
    default=None,
    help="Standards file to quote the section from (default: the bundled copy).",
)
def explain(rule_id: str, fmt: str, color_flag: bool | None, standards_path: str | None) -> None:
    """Explain a rule: its rationale, standards excerpt, severity, and tier.

    RULE_ID is case-insensitive (e.g. DAX-USE-DIVIDE). This prints what a finding
    only cites — so a report reader never needs docs/standards.md open, and the
    agent can pull rule rationale for triage (`--format json`). An unknown id is a
    usage error with a did-you-mean. Mirrors coop-sql-review's `explain`.
    """
    from coop_review_core.report import sty

    by_id = {r.id: r for r in all_rules()}
    match = by_id.get(rule_id) or by_id.get(rule_id.upper())
    if match is None:
        suggestions = difflib.get_close_matches(rule_id.upper(), list(by_id), n=3, cutoff=0.5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise click.UsageError(
            f"unknown rule id '{rule_id}'. Run `coop-dax-review rules` to list them.{hint}"
        )

    doc = rule_docs().get(match.id, "").strip()
    section = section_text(resolve_standards_path(standards_path), match.standard_ref)

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "id": match.id,
                    "title": match.title,
                    "severity": match.severity,
                    "category": match.category,
                    "standard_ref": match.standard_ref,
                    "tier": match.tier,
                    "kind": match.kind,
                    "default_enabled": match.default_enabled,
                    "params": match.params,
                    "rationale": doc,
                    "standards_excerpt": section,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
        return

    use_col = use_color(color_flag, None)
    tag = "agent-judgment" if match.kind == "agent" else f"{match.severity} (default)"
    meta = f"severity: {tag}   tier: {match.tier}   standard: {match.standard_ref}"
    if not match.default_enabled:
        meta += "   [off by default — enable in rules.yml]"

    out = [sty(f"{match.id} - {match.title}", "bold", color=use_col), meta]
    if match.params:
        out.append("params: " + ", ".join(f"{k}={v!r}" for k, v in sorted(match.params.items())))
    if doc:
        out += ["", sty("Why", "bold", color=use_col), doc]
    if section:
        out += ["", sty(f"Standard {match.standard_ref}", "bold", color=use_col), section]
    click.echo("\n".join(out))


def _run_upgrade(check_only: bool) -> None:
    """Report version + dependency freshness, then print the exact command to run.

    The ONLY networked command (PyPI / `git fetch`). Core ``run_upgrade`` never
    self-updates: a package manager can't reliably replace a program that is
    currently running (on Windows the console-script .exe is locked), so it
    shows the command for the user to run in a fresh terminal after exiting.
    ``--check`` stops after the freshness report (status only — mirrors the
    coop-sql-review twin).
    """
    from coop_dax_review.upgrade import build_plan

    run_upgrade(check_only, tool_name=TOOL, plan=build_plan())


@cli.command()
@with_upgrade_options
def upgrade(check_only: bool) -> None:
    """Show how to update coop-dax-review (and check dependency freshness).

    The ONLY command that uses the network. Prints the exact command to run —
    the tool never replaces itself while running.
    """
    _run_upgrade(check_only)


@cli.command()
@with_upgrade_options
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


def main() -> None:
    """Console-script entrypoint: friendly one-line errors, 130 on Ctrl-C."""
    force_utf8_console()
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
