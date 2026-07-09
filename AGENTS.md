# AGENTS.md

Canonical guide for **any** coding agent (Claude Code, the Pi agent, Hermes/Kimi, or a human)
working in this repository. `CLAUDE.md` imports this file; do not duplicate content there.

## Status: M0–M5 done + published to PyPI — 25 rules (M6 agent-wiring remaining)

Scaffold, model catalog, TMDL/.bim parsers, rule engine, text/JSON renderers, standards-driven
config, the full rule set documented in `RULES.md` (all 25 rules: the original Tier-1/2/3 + agent
set plus the M5 best-practice rules §14–§20 adopted from `docs/standards-proposed-additions.md`:
DIVIDE, format strings, key column types, hidden FKs, key summarizeBy, display folders, explicit
measures — plus §21 DAX-AUTO-DATETIME) are implemented and tested (`coop-dax-review rules` lists all
25). The foundation was adversarially reviewed (20
confirmed issues fixed) and every rule has a fires + a compliant case; precision issues found by
per-rule verifiers are fixed and pinned in `tests/test_regressions.py` / `tests/test_m5*.py`.
The UX surface was then brought to parity with `coop-sql-review`: `check` gained `--format
markdown|html` + `-o/--output` and a self-contained, branded **HTML report** (inline CSS + base64
logo in `data/cooptimize-logo.png`, `report.to_html`/`to_markdown`) that always writes to a file and
opens in the browser (`--open/--no-open`, auto-gated to interactive terminals via
`_should_open_report`); an interactive **folder picker** (`questionary`, `_interactive_pick_paths`)
appears when `check` is run with no paths in a TTY; and `upgrade`/`update` now **print** the install-
appropriate command (`upgrade_command` -> `pipx upgrade …`, etc.) instead of self-applying, since a
package manager can't replace the running tool (the `--yes` flag and `apply_plan` call path were
dropped; `--check` — status only, stop before the command — was restored for SQL-twin parity). The terminal report (`--format text`) was then restyled into a **sectioned
report** — banner, one section per model with `ERROR`/`WARN`/`INFO` severity badges, a `SUMMARY`
panel — with ANSI color auto-enabled at an interactive terminal and plain ASCII when piped /
redirected / `--no-color` / `NO_COLOR` (`report.console_lines(..., color=)`, cli `_use_color`,
`--color/--no-color`). New dep: `questionary>=2.0`. Tests in `tests/test_report.py` and the
expanded `tests/test_cli.py`; upgrade-command coverage lives there and in
`tests/test_core_wiring.py` / `tests/test_review_fixes.py`.
Remaining: **M6** — wire into the company analytics agent. (Publishing is done: coop-dax-review
is live on PyPI via the `v*`-tag trusted-publishing workflow.) Any further
`standards-proposed-additions.md` items need the user to merge the section into `docs/standards.md`
(the authored canon) first; keep the bundled copy `src/coop_dax_review/data/standards.md`
byte-identical (see "Standards-file invariant" below). Background reading: `SPEC.md`, `RULES.md`,
`docs/standards.md`.

## Environment

- Works fully headless on Linux (and macOS/Windows) — no GUI needed; browser-opening and the
  folder picker auto-disable off-TTY, and only `upgrade` touches the network.
- Python: create the venv with **Python 3.13** (3.10–3.13 supported; **avoid 3.14** — its venvs
  don't process editable-install `.pth` files, so imports/console scripts fail). `make setup`
  uses whatever `python3` resolves to; if `python3 --version` prints 3.14+, rebuild explicitly:
  `rm -rf .venv && python3.13 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"`,
  then verify with `make test` (expect all tests passing).
- Before starting any work: `git fetch && git pull --ff-only`. If the pull fails, or
  `git status --porcelain` prints changes you didn't make yourself, **stop and report** — never
  stash, reset, or commit around them (another agent or human may share this tree).
- Secrets: **none in this repo and none needed** — PyPI publishing is tokenless trusted
  publishing (GitHub OIDC), and the tool itself is offline.

**Dev-env gotchas:**

- On a Python 3.14 venv (as the repo's old Homebrew setup had) the hatchling editable install's
  `.pth` is processed unreliably, so the `coop-dax-review` console script intermittently
  `ModuleNotFoundError`s. For
  reliable local CLI runs use `PYTHONPATH=src .venv/bin/python -m coop_dax_review ...` (a clean
  `pip uninstall -y coop-dax-review && pip install -e .` also restores the script). Tests are
  unaffected (`conftest.py` puts `src` on the path); shipped installs (pipx/pip from PyPI) are too.
- **Never invoke `.venv/bin/pytest`, `.venv/bin/pip`, or `.venv/bin/coop-dax-review` directly.**
  Venv console scripts hard-code the venv's absolute path at install time in their shebang; this
  repo has moved on disk before (iCloud → `~/Developer`) and those scripts fail with
  `bad interpreter`. `.venv/bin/python -m <module>` always works — every command below uses that
  form. (If a console script errors this way, either use the module form or recreate the venv with
  `make setup`.)

## Commands

`make` targets are the canonical entry points (see `Makefile`); the raw commands they run follow.

```sh
make setup           # one-time: create .venv, install -e ".[dev]"
make test            # .venv/bin/python -m pytest -q          (317 tests as of v0.9.0, <1s)
make lint            # ruff check + ruff format --check on src tests — the exact CI gate
make build           # rm -rf dist, then python -m build → dist/ holds only the current version
make release-check   # scripts/release-check.sh: version gate + standards sync (see below)
```

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"   # what `make setup` does
.venv/bin/python -m pytest -q                                          # run all tests
.venv/bin/python -m pytest tests/test_rules.py -q                      # one test file
.venv/bin/python -m pytest tests/test_rules.py::test_nested_calculate_fires   # one test
.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests
PYTHONPATH=src .venv/bin/python -m coop_dax_review check tests/fixtures               # run the linter
PYTHONPATH=src .venv/bin/python -m coop_dax_review check tests/fixtures --format json # the agent contract
PYTHONPATH=src .venv/bin/python -m coop_dax_review rules                # list every rule
```

Verify after any code change: `make test` (expect `... passed` and exit 0) and `make lint`
(expect no output from `ruff check`, `N files already formatted` from `ruff format --check`).

Release — only when Aaron explicitly asked for one **naming the version** in the current
conversation (the tag push publishes to PyPI immediately). Steps, in order:

1. Bump `__version__` in `src/coop_dax_review/__init__.py` (the single source; `pyproject.toml`
   derives it via hatchling dynamic versioning) and add the `## [X.Y.Z]` entry to `CHANGELOG.md`.
2. `make release-check` — must print `release-check: OK`.
3. Commit and push the bump, then `git tag vX.Y.Z && git push origin vX.Y.Z` — publish.yml does
   the rest via PyPI trusted publishing (it refuses the release if the tag and `__version__`
   disagree).
4. Verify: the `Publish to PyPI` workflow run is green (repo → Actions tab) and
   `python -m pip index versions coop-dax-review` (networked) lists X.Y.Z.

Guardrails: never infer a release from a clean working tree, a version bump you notice, or green
CI — real incident (2026-07-02): an agent cut a spurious empty release off a "clean tree" signal
while another agent shared the same tree. Never move, delete, or reuse an existing `v*` tag (PyPI
refuses re-uploads; a botched release means the next patch number). Suite ordering: release
`coop-review-core` **first** (this repo pins `coop-review-core>=...`), and a suite release is
**not done** until the `coop-website` repo is synced + pushed — `versions.json` first, then both
of its check scripts `PASS` (procedure: coop-website's `AGENTS.md`, "Release-time procedure").

## Git hooks

One-time activation per clone (not automatic — git ignores `.githooks/` until told):

```sh
git config core.hooksPath .githooks
git config core.hooksPath          # verify: prints `.githooks`
```

The `pre-commit` hook runs `scripts/release-check.sh` (<1s, no network, no venv): the
version-single-source gate and the standards byte-identity check. If it fails, fix what it
reports — **never bypass with `git commit --no-verify`**; a commit that drifts the standards
files or breaks the version gate will fail CI and block the next release anyway.

## Testing against local coop-review-core

This tool's `.venv` holds a **non-editable installed copy** of the shared `coop-review-core`
package (pyproject pins `coop-review-core>=0.4,<0.5`), NOT an editable link to the local
`coop-review-core` checkout. Edits to the local core checkout are therefore **invisible** to
this tool until core is re-published and reinstalled. Do not `pip install -e` the local core into
this venv — editable installs are unreliable here (see dev-env gotchas). The coop-* repos are
assumed cloned **side by side under one parent directory** (on Aaron's Mac: `~/Developer`, which
is what `$HOME/Developer` below means) — substitute your actual path to the sibling
`coop-review-core` checkout if it lives elsewhere.

To run this tool's tests or CLI against **local core edits**, shadow the installed copy on
`PYTHONPATH` (local core first, then this repo's own `src`):

```sh
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python -m pytest -q
# same prefix for the CLI:
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python -m coop_dax_review check tests/fixtures
```

Expect the full suite to pass exactly as with the installed core (verified: 317 passed). If tests
pass shadowed but fail bare (or vice versa), the local core has diverged from the released one —
that difference is the thing to investigate, not to paper over.

After a core release, resync the venv so bare runs use the new core:
`.venv/bin/python -m pip install -U coop-review-core` (verify with
`.venv/bin/python -m pip show coop-review-core`). Release order is always **core first**, then
the tools whose pyproject pins the new floor.

## Standards-file invariant

`docs/standards.md` is the **authored canon**; `src/coop_dax_review/data/standards.md` is the
**bundled copy** shipped as package data (the default `--standards`; its sha256 travels in the
JSON contract as provenance). They MUST stay **byte-identical** — never edit the bundled copy
directly. After any edit to the canon:

```sh
cp docs/standards.md src/coop_dax_review/data/standards.md
cmp docs/standards.md src/coop_dax_review/data/standards.md && echo IN-SYNC   # must print IN-SYNC
```

The invariant is enforced three ways: `tests/test_standards_sync.py` (pytest),
`scripts/release-check.sh` (via `make release-check` and the pre-commit hook), and a dedicated
`cmp` step in `.github/workflows/ci.yml`.

## Adding a rule

Drop a `src/coop_dax_review/rules/dax_<name>.py` exporting a module-level `RULE = Rule(...)`. The
registry auto-discovers any `dax_*.py` (so no shared file to edit → conflict-free parallel
authoring). A deterministic rule sets `check(ctx) -> [Finding]`; an agent-judgment rule sets
`kind="agent"` + `detect(ctx) -> [AgentReviewItem]` (routed to `agent_review`, never auto-decided).
`ctx.catalog` is the `ModelCatalog`; `ctx.finding(...)` / `ctx.review(...)` stamp the rule's
id/severity/ref. **Always `mask_dax()` before any text scan** (helpers re-export `masked`,
`line_at`) so a keyword inside a comment/string never fires. Favor precision over recall — a false
positive on compliant code erodes trust fastest (the standards' own "good" examples must stay
clean). Add a fires + a compliant case to `tests/test_rules.py`.

## What this tool is

`coop-dax-review` — an **offline, advisory** DAX/model standards linter for Power BI semantic
models. It parses TMDL (and `.bim`) models, builds a model catalog, checks measures **and model
structure** against `docs/standards.md`, and reports findings. It is **advisory and never blocking**
— it reports, it never edits or stops anything. Outputs: a human report (a sectioned, colorized
terminal report, Markdown, or a self-contained branded HTML file) and **machine JSON for the
company analytics agent**.

Sibling tool to `coop-sql-review` (same architecture/contracts). Reference implementation to clone
from: the `coop-data-doc` package (PyPI: `coop-data-doc`).

**Shared core:** the tool-agnostic infrastructure lives in the published
[`coop-review-core`](https://github.com/kabukisensei/coop-review-core) package (runtime dep;
pinned `>=0.4,<0.5`). The
local modules `progress.py`, `diagnostics.py`, `suppressions.py`, `upgrade.py`, and `standards.py`
are now **thin shims** that re-export / forward to core (baking in this tool's name); `finding.py`
sources `SEVERITIES`/`severity_rank`/`at_or_above`/`fingerprint` from `coop_review_core.severity` but
keeps the `model`-carrying `Finding`/`AgentReviewItem`. Since core 0.4.0, `report.py` builds on
`coop_review_core.report` (console chrome, the branded HTML style + the family's ONE bundled logo,
the JSON envelope + verdict, the diagnostics log, the SARIF emitter) and keeps only the
model-grouped renderers + this tool's finding dicts; `cli.py` imports its edge helpers
(`display_path`, `stdio_interactive`, `use_color`, `config_write_path`,
`apply_syntax_error_policy`, `write_extra_report`, `should_open_report`, `force_utf8_console`,
`run_upgrade`/`with_upgrade_options`) from `coop_review_core.cliutils` and config
loading/discovery (`load_config_friendly`, `parse_syntax_errors_knob`, `discover_config`) from
`coop_review_core.config` via the `standards.py` shim. Fix shared infra in `coop-review-core`; keep
the tool's own parsers, rules, Rule/RuleContext/Result, and `standards.md` here.

## Build approach — reuse, do not start from scratch

- **Skeleton**: hatchling `pyproject`, CI matrix, trusted-publishing, `upgrade.py`, `progress.py`,
  ruff, src layout — from the company CLI playbook + the coop-data-doc bones.
- **Parsers — lift from coop-data-doc**:
  - `src/coop_data_doc/parsers/tmdl.py`, `bim.py` — parse model into tables, columns (+dataType),
    measures (+DAX expression), relationships.
  - `src/coop_data_doc/parsers/dax.py` — DAX dependency extraction; **strips comments/strings
    before matching**. Reuse this stripping before *every* text rule so rules never false-positive
    inside string literals or comments.
- **Output**: reuse coop-data-doc `diagnostics.py` (severity + console/JSON/markdown).

## Architecture

```
TMDL/.bim model → parse → catalog {tables, columns, measures(+DAX), relationships, storage_mode, date_table}
                                   ↓
              rule engine (measure-text rules + model-level rules) → Findings → render (text · JSON · markdown · HTML)
```

- **Build the model catalog first** (milestone M1). It's the foundation: most Tier-1 rules need it,
  especially the measure-vs-column distinction — you can't tell a measure ref `[X]` from a column
  ref `[X]` without knowing which names are measures vs columns.
- **Rule** = `{id, title, severity, category, standard_ref, check(catalog|measure) -> [Finding]}`.
  Rule check functions must be **pure and deterministic** (LF, sorted output).
- **standards.md drives config** (which rules on + params) via `rules.yml` — editable
  without a rebuild.
- **Judgment rules are never silently dropped** — they go into the `agent_review` list of the JSON
  output so the agent can apply semantic judgment.

Rule taxonomy and the full Tier-1 vs Tier-2/3 build order are in `RULES.md`. The `Method` column
there (`text` / `catalog` / `model` / `agent`) tells you what context each rule needs.

## CLI

```
coop-dax-review check [MODEL_PATHS...] --standards <path> [--config <path>]
                      [--format text|json|markdown|html|sarif] [-o FILE]
                      [--html FILE] [--md FILE] [--sarif FILE]
                      [--open/--no-open] [--color/--no-color] [--baseline <path>]
                      [--write-baseline <path>] [--save-ignores] [--min-severity ...]
                      [--log-file <path>] [--strict]
coop-dax-review rules
coop-dax-review upgrade [--check] # prints the command to update; never self-applies (alias: update)
coop-dax-review --version
```

- **Suppressions** (`suppressions.py`): inline `coop-dax-review:ignore <RULE>` comments (on the
  finding's line or the line above; bare/`*` = all) and a fingerprint **baseline** (`--write-baseline`
  / `--baseline`) for ratcheting on legacy models. All three suppression mechanisms (inline,
  baseline, `rules.yml` ignore list) filter findings **and `agent_review` items** before the
  `--min-severity` floor (`--write-baseline` records agent fingerprints too; an entry matching only
  an agent item is never stale) — same contract as coop-sql-review. Findings carry a stable, line-
  and path-independent `Finding.fingerprint()` (`rule_id, model, object, message/note` — no file, no
  line — **still schema_version 2**: the family-wide identity-scheme bump is tracked separately as
  issue #14, so baselines/ignores survive a cwd or machine change); the JSON adds
  `schema_version`, a `verdict`, `models_checked`, and a `fingerprint` per finding/agent-review item.
  The same fingerprints travel in the SARIF output as `partialFingerprints` under the family's
  frozen key `coopFingerprint/v2` (core `SARIF_FINGERPRINT_KEY` — GitHub code scanning matches
  alerts across runs by that key/value pair; no alerts have shipped from this tool yet, so the
  default key is the right one).
- **`rules.yml` ignore list** (core `RuleConfig.ignored_fingerprints` + `add_ignores`): an optional
  top-level `ignore:` list in `rules.yml` — human-readable, fingerprint-matched suppressions living
  in the one writable config file. Filtered before the `--min-severity` floor (like the baseline). A
  stale entry (no longer matching a current finding) is reported as an `ignore_stale` diagnostic.
  `check --save-ignores` shows an interactive checkbox (opt-in, all unchecked) of this run's findings
  and appends the picks via core `add_ignores` (interactive terminal only). Config discovery (core
  `discover_config`): `--config` if given, else the `COOP_DAX_REVIEW_CONFIG` env var, else a
  `coop-dax-review.yml` (preferred) or `rules.yml` (the deprecated shared name) per directory on a
  git-style walk from the cwd up to the repo root, else beside the standards file — discovery
  notes (the rules.yml deprecation nudge, a shadowed-file warning) surface on stderr. Writes go to
  `--config` if given, else back to the config the run actually read (core `config_write_path` —
  never inside the installed package), else `./rules.yml`.
- **Extra report sinks**: `--html FILE` / `--md FILE` / `--sarif FILE` write a self-contained HTML /
  Markdown / SARIF 2.1.0 report in *addition* to the main `--format` output (they compose with any
  format and never open a browser). Distinct from `--format html`, which always writes/opens a
  single default-named file.
- **SARIF** (`--format sarif` or the `--sarif FILE` sink; flag semantics mirror coop-sql-review):
  a deterministic SARIF 2.1.0 log via core's shared `to_sarif` emitter — never fork a local copy.
  Findings map to their rule/severity (info -> `note`), agent-review items are non-blocking `note`
  results, error-severity diagnostics ride the synthetic `syntax-error` rule, and warning-severity
  diagnostics are intentionally not emitted. Rule metadata (title, §ref, tier, category) comes from
  `report._sarif_driver_rules()`. `--format sarif` prints to stdout unless `-o` is given (the CI
  form: `--format sarif -o coop-dax-review.sarif`, then upload-sarif — snippet in README).

- Paths point at a PBIP/TMDL model folder (`*.SemanticModel/definition/...`) or a `.bim`. Run
  `check` with no paths in a TTY and a `questionary` checkbox picks which subfolders to scan.
  TMDL models are grouped by their **root directory** (`.SemanticModel`/`definition` root, else
  the parent folder for loose files), so same-named dev/prod models stay distinct and a flat
  folder of `.tmdl` files is one model. An explicitly passed non-`.tmdl`/`.bim` file is called
  out on stderr, never parsed as a phantom `.bim`.
- Exit codes follow the **family-wide contract** stated once in
  [coop-review-core's AGENTS.md](https://github.com/kabukisensei/coop-review-core/blob/main/AGENTS.md)
  ("Exit-code contract": 0 advisory / 1 friendly tool failure / 2 usage error + the `--strict`
  trip / 130 interrupt) — don't restate the table here. Tool-specifics only: `--strict` trips
  (exit 2) when findings remain, **when zero models were checked** (a typo'd path must not pass CI
  as clean; a zero-model run still renders every format/sink, with `models_checked: 0` and one
  `scan_empty` diagnostic per searched root), or when an error-severity diagnostic remains. A
  malformed/mis-encoded config (or a missing explicit `--config` / env-var path) is a friendly
  one-line usage error, exit 2 (`cli._load_rule_config` — mirrors coop-sql-review).
- `--standards` defaults to the bundled `data/standards.md` (kept byte-identical to the authored
  `docs/standards.md`); `--log-file` writes a diagnostics log.
- The default `--format text` is a **sectioned report** (banner, one section per model with
  `ERROR`/`WARN`/`INFO` badges, a `SUMMARY` panel). Color is automatic at an interactive terminal
  and plain ASCII when piped / redirected / `--no-color` / `NO_COLOR`; `--color`/`--no-color`
  overrides the auto-detection.
- `--format html` always writes a self-contained report file (default
  `coop-dax-review-report.html`, or `-o`), prints its path, and opens it in the browser
  (`--no-open` to skip; auto-suppressed off-TTY). `--format markdown`/text honor `-o` or print.

## Agent JSON contract (identical shape to coop-sql-review)

```json
{
  "tool": "coop-dax-review", "version": "x.y.z",
  "standards": {"path": "...", "sha256": "..."},
  "findings": [{"rule_id":"...","severity":"warning","model":"...","object":"[Sales: Revenue YTD]","message":"...","standard_ref":"§3"}],
  "summary": {"error":0,"warning":2,"info":4},
  "agent_review": [{"rule_id":"...","object":"[...]","note":"..."}]
}
```

`object` is the measure name (or table/relationship for model-level findings).

## Hard requirements

- **Non-blocking, offline, deterministic** — as coop-data-doc.
- Strip DAX comments/strings before any text matching (reuse `dax.py`).
- `DAX-MARKED-DATE-TABLE` fires only when the model actually uses time-intelligence functions
  (`DATESYTD`, `SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, …) — in measures or in
  calculated-column expressions.
- Thresholds for "non-trivial" measures (`DAX-VAR-RETURN`, `DAX-COMPLEX-NO-HEADER`) must be
  configurable.

## Build milestones (see SPEC.md §"Build milestones")

M0 scaffold → M1 parsing + catalog → M2 rule engine + Tier-1 rules → M3 diagnostics output →
M4 standards-driven config → M5 Microsoft/Tabular best-practice rules → M6 package + publish + wire
into the agent.
