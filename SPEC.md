# coop-dax-review — build spec

## What it is
An **offline, advisory DAX/model standards linter** for our Power BI semantic models. It parses
TMDL (and `.bim`) models, checks measures **and model structure** against `docs/standards.md`
(our standards + Microsoft/Tabular best practices), and surfaces anything that doesn't match.
**Advisory, never blocking** — it reports; it never edits or stops anything. Outputs: a human
report (console, Markdown, or a self-contained branded **HTML** report) and **machine JSON for
the agent**.

> Sibling tool to `coop-sql-review` — same architecture and contracts. Build `coop-sql-review` first
> if possible; this clones the pattern with DAX/model specifics.

## Who runs it
- A developer, on changed measures/models before committing (or in CI as a non-failing report).
- The company analytics agent, which calls it and adds semantic judgment.

## Reuse — do NOT start from scratch
- **Skeleton**: the company CLI playbook + the coop-data-doc bones (hatchling pyproject,
  ci matrix, publish trusted-publishing, `upgrade.py`, `progress.py`, ruff, src layout).
- **DAX + model parsing**: lift from coop-data-doc:
  - `src/coop_data_doc/parsers/tmdl.py` and `bim.py` — parse the model into tables, columns
    (+dataType), measures (+DAX expression), and relationships metadata.
  - `src/coop_data_doc/parsers/dax.py` — DAX dependency extraction; strips comments/strings
    before matching (reuse that tokenizing so rules don't false-positive inside strings).
- **Output**: reuse coop-data-doc `diagnostics.py` (severity + console/JSON/markdown).

## Why "model-aware" matters
Many DAX rules can't be judged from a measure's text alone — they need the **model catalog**:
- distinguishing a **measure** ref `[X]` from a **column** ref `[X]` (rules §1) requires knowing
  which names are measures vs columns;
- bidirectional relationships (§7), a marked Date table (§8), star-vs-snowflake (§6), and Direct
  Lake calculated-column constraints (§13) are **model-level**, not measure text.
So parse the whole model first, build a catalog `{tables, columns-by-table, measures, relationships}`,
then run rules with that context.

## Architecture
```
TMDL/.bim model → parse → catalog {tables, columns, measures(+DAX), relationships}
                                   ↓
              rule engine (measure-text rules + model-level rules) → Findings → render (text + JSON)
```
- **Rule** = `{id, title, severity, category, standard_ref, check(catalog|measure) -> [Finding]}`.
- **standards.md drives config** (which rules on + params) via `rules.yml` / front-matter — edit
  anytime, no rebuild.
- **Judgment rules** → `agent_review` list (never silently dropped).

See `RULES.md` for the taxonomy.

## CLI
```
coop-dax-review check [MODEL_PATHS...] --standards <path> [--format text|json|markdown|html]
                      [-o FILE] [--no-open] [--min-severity ...] [--strict]
coop-dax-review rules
coop-dax-review update            # prints the command to update; never self-applies
coop-dax-review --version
```
- Paths point at a PBIP/TMDL model folder (`*.SemanticModel/definition/...`) or a `.bim`. Run
  `check` with no paths in a terminal and a checkbox picker chooses which subfolders to scan.
- Default exit **0** (advisory); `--strict` opt-in gate.
- `--standards` defaults to bundled `docs/standards.md`; can point at a canonical company
  standards file.
- `--format html` writes a self-contained report file (default `coop-dax-review-report.html`, or
  `-o`), prints its path, and opens it in the browser (`--no-open`, auto-off when non-interactive).

## Agent integration contract (identical shape to coop-sql-review)
```json
{
  "tool": "coop-dax-review", "version": "x.y.z",
  "standards": {"path": "...", "sha256": "..."},
  "findings": [
    {"rule_id":"DAX-NO-NESTED-CALCULATE","severity":"warning","model":"Sales Analytics",
     "object":"[Sales: Revenue YTD]","message":"nested CALCULATE — break into VARs","standard_ref":"§3"}
  ],
  "summary": {"error":0,"warning":2,"info":4},
  "agent_review": [{"rule_id":"DAX-KEEPFILTERS-NEEDED","object":"[...]","note":"judge whether KEEPFILTERS is required per §5"}]
}
```
`object` is the measure name (or table/relationship for model-level findings). Same two-audience
pattern as coop-data-doc.

## Build milestones
- **M0** — scaffold from the playbook.
- **M1** — wire in TMDL/bim parsing (lift from coop-data-doc); build the model catalog.
- **M2** — rule engine + Tier-1 rules from `RULES.md` (measure-text rules first, then model-level).
- **M3** — diagnostics output (text + JSON), advisory exit codes.
- **M4** — standards-driven enable/config.
- **M5** — Microsoft/Tabular best-practice rules (see `docs/standards-proposed-additions.md`).
- **M6** — package + publish + wire into the agent.

## Kickoff (paste into a NEW session launched from this folder)
> Building **coop-dax-review**, an offline advisory DAX/model standards linter for our Power BI
> semantic models. Read the company CLI playbook, this folder's `SPEC.md` + `RULES.md`,
> and `docs/standards.md`. Reuse the coop-data-doc skeleton and lift its model parsers
> (`src/coop_data_doc/parsers/tmdl.py`, `bim.py`, `dax.py`) and `diagnostics.py`. Build the
> model catalog first (M1), then the Tier-1 rules from `RULES.md`.

## Hard requirements
- **Non-blocking**, **offline**, **deterministic** (LF, sorted, pure rule functions) — as coop-data-doc.
- Strip DAX comments/strings before text matching (reuse `dax.py`) so rules don't fire inside literals.
