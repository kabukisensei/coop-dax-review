# coop-dax-review

Offline, **advisory** DAX/model standards linter for our Power BI semantic models. It parses
TMDL (and legacy `.bim`) models, builds a model catalog, checks measures **and model structure**
against `docs/standards.md` (our DAX standards + Microsoft/Tabular best practices), and surfaces
anything that doesn't match. **It never edits or blocks — it only reports.** Human reports (a
sectioned, colorized terminal report, Markdown, or a self-contained branded HTML file) and
**machine JSON for the company analytics agent**.

Sibling tool to [`coop-sql-review`](https://github.com/kabukisensei/coop-sql-review) — same
architecture and contracts.

Part of the Cooptimize **coop suite** — if your team uses
[coop-agent](https://github.com/kabukisensei/coop-agent), `coop install` installs this plus the
sibling tools ([coop-sql-review](https://github.com/kabukisensei/coop-sql-review),
[coop-data-doc](https://github.com/kabukisensei/coop-data-doc)); `coop update` keeps them
current.

## Install

```sh
pipx install coop-dax-review        # from PyPI
```

Use `pipx`, not system `pip`, so the tool stays isolated from other CLIs (`ms-fabric-cli`,
`azure-cli`) it might otherwise fight over shared pins. For local development (Python 3.10–3.13;
avoid 3.14 — its venvs mis-handle editable installs):

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
```

## Usage

```sh
coop-dax-review check [MODEL_PATHS...] [--format text|json|markdown|html|sarif] [-o FILE]
                      [--html FILE] [--md FILE] [--sarif FILE] [--open/--no-open]
                      [--color/--no-color] [--log-file FILE] [--baseline FILE]
                      [--write-baseline FILE] [--save-ignores]
                      [--min-severity error|warning|info] [--strict]
coop-dax-review rules                 # list every rule (id, severity, tier, agent?)
coop-dax-review upgrade [--check]     # show the command to update (never self-applies; alias: update)
coop-dax-review --version
```

- `MODEL_PATHS` point at a PBIP/TMDL model folder (`*.SemanticModel/definition/...`), any folder of
  `.tmdl` files, or a legacy `.bim` file. Directories are searched recursively; defaults to `.`.
- **Run it with no paths in a terminal** and it offers a checkbox picker of the subfolders to check
  (all selected by default — press ENTER to scan everything).
- **Advisory**: exit code is always `0`. `--strict` is the opt-in CI gate — exit `2` when any
  finding remains at/above `--min-severity`, **or when no models were found/checked at all** (so a
  typo'd path can't pass silently). A zero-model run still renders the full report (with
  `models_checked: 0` and a `scan_empty` diagnostic per searched path).
- `--standards <path>` overrides the bundled standards (e.g. point it at a canonical company
  standards file). Its sha256 travels in the JSON so the agent knows which standards a report used.
- A config file can disable rules, override severities, and **tune thresholds** — all with no
  rebuild. It is found, first hit wins, via: `--config`; the `COOP_DAX_REVIEW_CONFIG` environment
  variable (point a whole CI pipeline at one config); a **`coop-dax-review.yml`** (preferred) or
  `rules.yml` (the deprecated shared name — every coop-*-review tool reads it, so two tools in one
  monorepo would fight over it) in the current directory **or any parent up to the repo root**;
  else beside the standards file. A broken config (bad YAML, wrong shape, a non-UTF-8 save) is a
  friendly one-line error naming the file, and a `--config` or env-var path that doesn't exist is
  an error too (a typo can't silently drop your overrides). For example, raise what counts as a
  "non-trivial" measure:
  ```yaml
  rules:
    DAX-VAR-RETURN:
      params: { min_functions: 5 }   # also: DAX-COMPLEX-NO-HEADER.min_vars,
                                      # DAX-DISPLAY-FOLDERS.min_measures, DAX-SIMPLE-FUNCTIONS.min_calculates
  ```

```sh
coop-dax-review check ./MyModel.SemanticModel
coop-dax-review check . --format json --strict --min-severity warning
coop-dax-review check . --format html              # writes a report file and opens it in your browser
coop-dax-review check . --format markdown -o report.md
```

The default `--format text` is a **sectioned terminal report**: a banner, one section per model with
`ERROR`/`WARN`/`INFO` severity badges, and a `SUMMARY` panel. It's colorized automatically when
you're at a terminal and falls back to plain text when piped or redirected (override with
`--color`/`--no-color`; `NO_COLOR` is respected).

`--format html` produces a self-contained, branded HTML report (inline CSS + embedded logo, no
network). It is always written to a file — `coop-dax-review-report.html` by default, or wherever
`-o` points — and the path is printed and opened in your browser (pass `--no-open` to skip the open,
e.g. in CI). `upgrade`/`update` print the exact command to run yourself (`pipx upgrade
coop-dax-review`, etc.) rather than self-applying, since a package manager can't replace the tool
while it is running; `upgrade --check` reports whether an update is available and stops there.

Want a report file *and* the usual console/JSON output in one run? `--html FILE`, `--md FILE`, and
`--sarif FILE` are extra sinks: they write a self-contained HTML, Markdown, and/or SARIF report to
the paths you name in addition to whatever `--format` prints, and never open a browser. Handy for
CI — e.g. keep the JSON contract on stdout while dropping a human-readable HTML artifact alongside
it:

```sh
coop-dax-review check . --format json --html report.html --md report.md
```

**Annotate a pull request in CI (GitHub / Azure DevOps).** `--format sarif` emits a standard
**SARIF 2.1.0** report that GitHub code scanning (and Azure DevOps) turn into inline PR
annotations on the exact TMDL/`.bim` lines. Findings map to their rule/severity, agent-review
items surface as non-blocking notes, and genuinely malformed DAX (a `syntax_error` diagnostic)
annotates as an error. A ready-to-paste GitHub Actions step:
```yaml
    - name: DAX standards review
      run: coop-dax-review check models/ --format sarif -o coop-dax-review.sarif
    - name: Upload SARIF
      uses: github/codeql-action/upload-sarif@v3
      with:
        sarif_file: coop-dax-review.sarif
```
The tool stays advisory (exit 0) unless you add `--strict`, so the SARIF annotations appear
without failing the build — add `--strict` if you want the build to go red on remaining findings.

## What it checks

Run `coop-dax-review rules` for the live list. Deterministic rules (reported as findings):

| Rule | § | Sev | Flags |
|---|---|---|---|
| `DAX-MEASURE-CATEGORY` | 1 | warning | measure not named `[Category: Name]` |
| `DAX-MEASURE-NOT-PREFIXED` | 1 | warning | `Table[X]` where `X` is a measure (measures take no prefix) |
| `DAX-COLUMN-PREFIXED` | 1 | warning | bare `[X]` where `X` is a column (columns need `Table[X]`) |
| `DAX-VAR-RETURN` | 2 | info | non-trivial measure with no `VAR`/`RETURN` structure |
| `DAX-NO-NESTED-CALCULATE` | 3 | warning | `CALCULATE` nested *directly* inside `CALCULATE` (iterator-mediated per-row nesting is fine) |
| `DAX-FILTER-TABLE-IN-CALCULATE` | 4 | warning | `FILTER(<table>, <col> = ...)` as a CALCULATE filter argument where a plain column filter suffices |
| `DAX-SNOWFLAKE` | 6 | info | a table with relationships chained through it (snowflake link) |
| `DAX-BIDI-RELATIONSHIP` | 7 | warning | a bidirectional cross-filter relationship |
| `DAX-MARKED-DATE-TABLE` | 8 | warning | time-intelligence used (in a measure or calculated column) but no marked Date table |
| `DAX-MEASURE-IN-ITERATOR` | 9 | info | a measure referenced inside a row iterator (hidden context transition) |
| `DAX-COMPLEX-NO-HEADER` | 12 | info | a complex measure (≥3 VARs) without a `/* ... */` header |
| `DAX-DIRECTLAKE-NO-CALC-COL` | 13 | warning | a calculated column in a Direct Lake model |
| `DAX-USE-DIVIDE` | 14 | warning | the `/` operator where `DIVIDE()` should be used (nonzero-literal divisors like `/ 1000` are safe and skipped) |
| `DAX-FORMAT-STRING` | 15 | warning | a measure with no explicit `formatString` |
| `DAX-NO-FLOAT-KEYS` | 16 | info | a relationship key column typed `double` |
| `DAX-HIDE-FK-COLUMNS` | 17 | info | a visible foreign-key (relationship) column |
| `DAX-KEY-SUMMARIZEBY-NONE` | 18 | info | a numeric key column that auto-aggregates (`summarizeBy` ≠ none) |
| `DAX-DISPLAY-FOLDERS` | 19 | info | a measure-heavy table with no display folders |

Agent-judgment rules — the tool detects the construct but emits to the JSON `agent_review` list
(never an auto-finding), because the call needs intent the linter can't infer:

| Rule | § | Judges |
|---|---|---|
| `DAX-KEEPFILTERS-NEEDED` | 5 | whether a CALCULATE boolean filter needs `KEEPFILTERS` (checked per top-level filter argument) |
| `DAX-STAR-SCHEMA` | 6 | whether a snowflake chain should be flattened to a star |
| `DAX-CONTEXT-TRANSITION` | 9 | whether an iterator's context transition is intended/correct |
| `DAX-SIMPLE-FUNCTIONS` | 10 | whether a CALCULATE-heavy measure could use simpler functions |
| `DAX-VALIDATION` | 11 | whether the §11 validation checklist was run (one model-level item counting the non-trivial measures) |
| `DAX-IMPLICIT-MEASURE` | 20 | whether a visible auto-aggregating numeric column should become an explicit measure |

See `RULES.md` for the full taxonomy. `docs/standards.md` §14–§20 are adopted Microsoft/Tabular
best practices (DIVIDE, format strings, key column types, hidden FKs, key summarizeBy, display
folders, explicit measures); `docs/standards-proposed-additions.md` is the original candidate list.

## DAX syntax errors

Beyond the standards rules, `check` runs a cheap **structural** validation over every measure body
and every calculated-column expression and reports genuinely malformed DAX — the kind that would
import broken into Power BI — as **`error`-severity `syntax_error` diagnostics**. It catches:
unbalanced parentheses, unbalanced brackets, an unterminated string literal (`"..."` with no
closing quote), an unterminated block comment (`/* ...` with no `*/`), and an empty measure body.
Parens/brackets/quotes that live inside an identifier (`[Net (USD)]`), a string, or a comment are
never counted, so compliant DAX is never flagged. This is drift **detection**, not a grammar: the
standards rules still run on whatever parsed. Because a `syntax_error` is error-severity, it flips
the JSON `verdict` to not-clean and fails `--strict` (exit 2) — so a broken measure never passes CI
as clean.

Tune it two ways:

- **`rules.yml` knob** — `syntax_errors: error` (default) | `warning` (demote but keep it visible in
  the JSON) | `off` (drop entirely):
  ```yaml
  syntax_errors: warning
  ```
- **Inline** — silence a single occurrence with a `syntax` (or bare `*`) ignore on the finding's
  line or the line above it. A rule-scoped ignore does **not** cover a syntax error:
  ```
  // coop-dax-review:ignore syntax
  ```

## Suppressing findings (adopting on an existing model)

Three deterministic, never-blocking ways to silence findings you've already triaged. All three
apply to regular findings **and** to `agent_review` items (the judgment-call prompts in the JSON),
so a triaged item stays silenced everywhere:

- **Inline** — drop a comment on a finding's line (or the line directly above it):
  ```
  // coop-dax-review:ignore DAX-VAR-RETURN reason: legacy measure, rewrite scheduled
  ```
  List several rule ids (`ignore DAX-A, DAX-B`), or use a bare `ignore` / `*` to silence every
  rule on that line. The `reason:` text is for humans; it's ignored by the parser.
- **`rules.yml` ignore list** — a human-readable, fingerprint-matched suppression list that lives
  in the one config file (like a baseline, but readable and hand-editable). Add an `ignore:` block:
  ```yaml
  ignore:
    - fingerprint: 4ad6aeb79867
      rule: DAX-BIDI-RELATIONSHIP        # rule / where / note are for humans; matching is by fingerprint
      where: Sales/FactSales[ProductId] -> DimCustomer[CustomerId]
      note: intentional many-to-many, reviewed 2026-07
  ```
  You don't have to hand-copy fingerprints: run `check --save-ignores` and, at an interactive
  terminal, you get a checkbox of this run's findings (all unchecked — opt in to the ones you want
  gone); the picks are appended to the config file **this run read** (so a team config beside the
  standards file, or one found in a parent directory, is updated in place rather than shadowed by
  a new `./rules.yml`). A `coop-dax-review.yml` or `rules.yml` in your current directory (or any
  parent up to the repo root) is auto-discovered with no `--config` flag, so the loop is just
  "run, `--save-ignores`, re-run". An ignore entry that no longer matches any finding (you fixed it)
  is reported as a diagnostic so the list self-cleans.
- **Baseline (ratchet)** — record today's findings and surface only *new* ones going forward:
  ```sh
  coop-dax-review check . --write-baseline dax-baseline.json   # once, to capture the status quo
  coop-dax-review check . --baseline dax-baseline.json         # thereafter: only new findings appear
  ```
  Each finding has a stable `fingerprint` (in the JSON) — independent of line numbers **and** of
  file paths, so a baseline written on one machine or from one directory still matches from
  another — and the baseline is a sorted list of those. A baseline entry that no longer matches
  any finding (you fixed it) is reported as a diagnostic so the file self-cleans
  (`--write-baseline` to prune).

  > **One-time migration (schema_version 2):** fingerprints used to include the cwd-relative file
  > path and changed in this release. Delete and regenerate any baseline files and `rules.yml`
  > `ignore:` lists written by earlier versions (re-run `--write-baseline` / `--save-ignores`).

## Agent JSON contract

```json
{
  "tool": "coop-dax-review", "schema_version": 2, "version": "x.y.z",
  "standards": {"path": "...", "sha256": "..."},
  "models_checked": 2,
  "verdict": {"clean": false, "highest_severity": "warning"},
  "findings": [{"rule_id":"...","severity":"warning","model":"Sales","file":"...","line":12,
                "object":"[Sales: Revenue YTD]","message":"...","standard_ref":"§3","fingerprint":"4ad6aeb79867"}],
  "summary": {"error":0,"warning":2,"info":4},
  "agent_review": [{"rule_id":"...","model":"Sales","file":"...","line":40,"object":"[...]","note":"...","standard_ref":"§5","fingerprint":"..."}],
  "diagnostics": [{"severity":"warning","category":"parse_failed","file":"...","message":"..."}]
}
```

`schema_version` lets a consumer pin the shape; `verdict`/`models_checked` give a quick machine
verdict + coverage signal; each finding's `fingerprint` is a stable id for tracking across runs.

## Project docs

- `SPEC.md` — architecture, CLI, agent contract, milestones.
- `RULES.md` — every standard mapped to a concrete check (deterministic vs agent-judgment).
- `docs/standards.md` — the canonical DAX standards the linter checks against (bundled as package data).
- `AGENTS.md` — orientation for coding agents (and humans) working in this repo; `CLAUDE.md`
  imports it.
