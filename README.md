# coop-dax-review

Offline, **advisory** DAX/model standards linter for our Power BI semantic models. It parses
TMDL (and legacy `.bim`) models, builds a model catalog, checks measures **and model structure**
against `docs/standards.md` (our DAX standards + Microsoft/Tabular best practices), and surfaces
anything that doesn't match. **It never edits or blocks — it only reports.** Two outputs: a human
console report and **machine JSON for the company analytics agent**.

Sibling tool to [`coop-sql-review`](https://github.com/kabukisensei/coop-sql-review) — same
architecture and contracts.

## Install

```sh
pipx install coop-dax-review        # once on PyPI
```

Use `pipx`, not system `pip`, so the tool stays isolated from other CLIs (`ms-fabric-cli`,
`azure-cli`) it might otherwise fight over shared pins. For local development:

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Usage

```sh
coop-dax-review check [MODEL_PATHS...] [--format text|json] [--min-severity error|warning|info] [--strict]
coop-dax-review rules                 # list every rule (id, severity, tier, agent?)
coop-dax-review --version
```

- `MODEL_PATHS` point at a PBIP/TMDL model folder (`*.SemanticModel/definition/...`), any folder of
  `.tmdl` files, or a legacy `.bim` file. Directories are searched recursively; defaults to `.`.
- **Advisory**: exit code is always `0`. `--strict` is the opt-in CI gate — exit `2` when any
  finding remains at/above `--min-severity`.
- `--standards <path>` overrides the bundled standards (e.g. point it at a canonical company
  standards file). Its sha256 travels in the JSON so the agent knows which standards a report used.
- A `rules.yml` beside the standards file (or `--config`) can disable rules / override severities
  with no rebuild.

```sh
coop-dax-review check ./MyModel.SemanticModel
coop-dax-review check . --format json --strict --min-severity warning
```

## What it checks

Run `coop-dax-review rules` for the live list. Deterministic rules (reported as findings):

| Rule | § | Sev | Flags |
|---|---|---|---|
| `DAX-MEASURE-CATEGORY` | 1 | warning | measure not named `[Category: Name]` |
| `DAX-MEASURE-NOT-PREFIXED` | 1 | warning | `Table[X]` where `X` is a measure (measures take no prefix) |
| `DAX-COLUMN-PREFIXED` | 1 | warning | bare `[X]` where `X` is a column (columns need `Table[X]`) |
| `DAX-VAR-RETURN` | 2 | info | non-trivial measure with no `VAR`/`RETURN` structure |
| `DAX-NO-NESTED-CALCULATE` | 3 | warning | `CALCULATE` nested inside `CALCULATE` |
| `DAX-FILTER-TABLE-IN-CALCULATE` | 4 | warning | `FILTER(<table>, <col> = ...)` where a plain column filter suffices |
| `DAX-SNOWFLAKE` | 6 | info | a table with relationships chained through it (snowflake link) |
| `DAX-BIDI-RELATIONSHIP` | 7 | warning | a bidirectional cross-filter relationship |
| `DAX-MARKED-DATE-TABLE` | 8 | warning | time-intelligence used but no marked Date table |
| `DAX-MEASURE-IN-ITERATOR` | 9 | info | a measure referenced inside a row iterator (hidden context transition) |
| `DAX-COMPLEX-NO-HEADER` | 12 | info | a complex measure (≥3 VARs) without a `/* ... */` header |
| `DAX-DIRECTLAKE-NO-CALC-COL` | 13 | warning | a calculated column in a Direct Lake model |
| `DAX-USE-DIVIDE` | 14 | warning | the `/` operator where `DIVIDE()` should be used |
| `DAX-FORMAT-STRING` | 15 | warning | a measure with no explicit `formatString` |
| `DAX-NO-FLOAT-KEYS` | 16 | info | a relationship key column typed `double` |
| `DAX-HIDE-FK-COLUMNS` | 17 | info | a visible foreign-key (relationship) column |
| `DAX-KEY-SUMMARIZEBY-NONE` | 18 | info | a numeric key column that auto-aggregates (`summarizeBy` ≠ none) |
| `DAX-DISPLAY-FOLDERS` | 19 | info | a measure-heavy table with no display folders |

Agent-judgment rules — the tool detects the construct but emits to the JSON `agent_review` list
(never an auto-finding), because the call needs intent the linter can't infer:

| Rule | § | Judges |
|---|---|---|
| `DAX-KEEPFILTERS-NEEDED` | 5 | whether a CALCULATE boolean filter needs `KEEPFILTERS` |
| `DAX-STAR-SCHEMA` | 6 | whether a snowflake chain should be flattened to a star |
| `DAX-CONTEXT-TRANSITION` | 9 | whether an iterator's context transition is intended/correct |
| `DAX-SIMPLE-FUNCTIONS` | 10 | whether a CALCULATE-heavy measure could use simpler functions |
| `DAX-VALIDATION` | 11 | whether the §11 validation checklist was run for a non-trivial measure |
| `DAX-IMPLICIT-MEASURE` | 20 | whether a visible auto-aggregating numeric column should become an explicit measure |

See `RULES.md` for the full taxonomy. `docs/standards.md` §14–§20 are adopted Microsoft/Tabular
best practices (DIVIDE, format strings, key column types, hidden FKs, key summarizeBy, display
folders, explicit measures); `docs/standards-proposed-additions.md` is the original candidate list.

## Agent JSON contract

```json
{
  "tool": "coop-dax-review", "version": "x.y.z",
  "standards": {"path": "...", "sha256": "..."},
  "findings": [{"rule_id":"...","severity":"warning","model":"Sales","file":"...","line":12,
                "object":"[Sales: Revenue YTD]","message":"...","standard_ref":"§3"}],
  "summary": {"error":0,"warning":2,"info":4},
  "agent_review": [{"rule_id":"...","object":"[...]","note":"...","standard_ref":"§5"}],
  "diagnostics": [{"severity":"warning","category":"parse_failed","file":"...","message":"..."}]
}
```

## Project docs

- `SPEC.md` — architecture, CLI, agent contract, milestones.
- `RULES.md` — every standard mapped to a concrete check (deterministic vs agent-judgment).
- `docs/standards.md` — the canonical DAX standards the linter checks against (bundled as package data).
- `CLAUDE.md` — orientation for Claude Code sessions in this repo.
