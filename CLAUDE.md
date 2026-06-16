# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: M0–M5 done — 24 rules implemented

Scaffold, model catalog, TMDL/.bim parsers, rule engine, text/JSON renderers, standards-driven
config, the full Tier-1/2/3 + agent rule set from `RULES.md` (17 rules), AND the M5 best-practice
rules adopted from `docs/standards-proposed-additions.md` (§14–§20: DIVIDE, format strings, key
column types, hidden FKs, key summarizeBy, display folders, explicit measures) are implemented and
tested (`coop-dax-review rules` lists all 24). The foundation was adversarially reviewed (20
confirmed issues fixed) and every rule has a fires + a compliant case; precision issues found by
per-rule verifiers are fixed and pinned in `tests/test_regressions.py` / `tests/test_m5*.py`.
Remaining: **M6** (publish to PyPI + wire into the company analytics agent). Any further
`standards-proposed-additions.md` items need the user to merge the section into `docs/standards.md`
(the authored canon) first; keep the bundled copy `src/coop_dax_review/data/standards.md`
byte-identical. Background reading: `SPEC.md`, `RULES.md`, `docs/standards.md`.

**Dev-env gotcha:** in this homebrew-Python 3.14 venv the hatchling editable install's `.pth` is
processed unreliably, so the `coop-dax-review` console script intermittently `ModuleNotFoundError`s.
For reliable local CLI runs use `PYTHONPATH=src .venv/bin/python -m coop_dax_review ...` (a clean
`pip uninstall -y coop-dax-review && pip install -e .` also restores the script). Tests are
unaffected (`conftest.py` puts `src` on the path); shipped installs (pipx/pip from PyPI) are too.

## Commands

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # one-time dev setup
.venv/bin/pytest -q                                          # run all tests
.venv/bin/pytest tests/test_rules.py -q                      # one test file
.venv/bin/pytest tests/test_rules.py::test_nested_calculate_fires   # one test
.venv/bin/ruff check . && .venv/bin/ruff format --check .    # lint + format (both gate CI)
.venv/bin/coop-dax-review check tests/fixtures               # run the linter on the fixtures
.venv/bin/coop-dax-review check tests/fixtures --format json # the agent contract
.venv/bin/coop-dax-review rules                              # list every rule
```

Release = bump `version` in **both** `pyproject.toml` and `src/coop_dax_review/__init__.py`, then
tag `vX.Y.Z` (publish.yml does the rest via PyPI trusted publishing).

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
— it reports, it never edits or stops anything. Two outputs: a human report (console/markdown) and
**machine JSON for the company analytics agent**.

Sibling tool to `coop-sql-review` (same architecture/contracts). Reference implementation to clone
from: the `coop-data-doc` package (PyPI: `coop-data-doc`).

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
              rule engine (measure-text rules + model-level rules) → Findings → render (text + JSON)
```

- **Build the model catalog first** (milestone M1). It's the foundation: most Tier-1 rules need it,
  especially the measure-vs-column distinction — you can't tell a measure ref `[X]` from a column
  ref `[X]` without knowing which names are measures vs columns.
- **Rule** = `{id, title, severity, category, standard_ref, check(catalog|measure) -> [Finding]}`.
  Rule check functions must be **pure and deterministic** (LF, sorted output).
- **standards.md drives config** (which rules on + params) via `rules.yml` / front-matter — editable
  without a rebuild.
- **Judgment rules are never silently dropped** — they go into the `agent_review` list of the JSON
  output so the agent can apply semantic judgment.

Rule taxonomy and the full Tier-1 vs Tier-2/3 build order are in `RULES.md`. The `Method` column
there (`text` / `catalog` / `model` / `agent`) tells you what context each rule needs.

## CLI (proposed)

```
coop-dax-review check [MODEL_PATHS...] --standards <path> [--format text|json] [--min-severity ...] [--strict]
coop-dax-review rules
coop-dax-review --version
```

- Paths point at a PBIP/TMDL model folder (`*.SemanticModel/definition/...`) or a `.bim`.
- Default exit **0** (advisory). `--strict` is the opt-in gate that can return non-zero.
- `--standards` defaults to bundled `docs/standards.md`.

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
  (`DATESYTD`, `SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, …).
- Thresholds for "non-trivial" measures (`DAX-VAR-RETURN`, `DAX-COMPLEX-NO-HEADER`) must be
  configurable.

## Build milestones (see SPEC.md §"Build milestones")

M0 scaffold → M1 parsing + catalog → M2 rule engine + Tier-1 rules → M3 diagnostics output →
M4 standards-driven config → M5 Microsoft/Tabular best-practice rules → M6 package + publish + wire
into the agent.
