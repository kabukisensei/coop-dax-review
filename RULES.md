# coop-dax-review — rule taxonomy

Bridge from prose `standards.md` to concrete checks. **Method**: `text` = DAX expression
(comments/strings stripped via `dax.py`); `catalog` = needs the model catalog
(tables/columns/measures); `model` = model structure/metadata (relationships, date table,
storage mode); `agent` = judgment → emitted in `agent_review`. **Tier 1** = build first.

## Deterministic rules — build these

| Rule ID | § | What it flags | Sev | Method | Tier |
|---|---|---|---|---|---|
| `DAX-NO-NESTED-CALCULATE` | 3 | `CALCULATE` nested *directly* inside `CALCULATE` (an iterator in between is the endorsed §9 per-row idiom, not flagged) | warning | text | 1 |
| `DAX-MEASURE-NOT-PREFIXED` | 1 | `Table[X]` where `X` is a measure (measures take no table prefix) | warning | catalog | 1 |
| `DAX-COLUMN-PREFIXED` | 1 | bare `[X]` where `X` is a column (columns need `Table[Col]`) | warning | catalog | 1 |
| `DAX-MEASURE-CATEGORY` | 1 | measure name not `[Category: Name]` | warning | catalog | 1 |
| `DAX-BIDI-RELATIONSHIP` | 7 | relationship with bidirectional cross-filter | warning | model | 1 |
| `DAX-MARKED-DATE-TABLE` | 8 | time-intel funcs used (in a measure or calculated column) but no marked Date table | warning | model+text | 1 |
| `DAX-FILTER-TABLE-IN-CALCULATE` | 4 | `FILTER(<table>, <col predicate>)` as a `CALCULATE` **filter argument** where a boolean filter suffices (a FILTER inside the first/expression argument — an iterator's table arg — is the §9 idiom, not flagged) | warning | text | 2 |
| `DAX-VAR-RETURN` | 2 | non-trivial measure without `VAR`/`RETURN` | info | text | 2 |
| `DAX-MEASURE-IN-ITERATOR` | 9 | measure ref inside `SUMX`/`AVERAGEX`/… (hidden context transition) | info | text+catalog | 2 |
| `DAX-SNOWFLAKE` | 6 | dimension related to another dimension (snowflake chain) | info | model | 2 |
| `DAX-DIRECTLAKE-NO-CALC-COL` | 13 | calculated column in a Direct Lake model | warning | model | 2 |
| `DAX-COMPLEX-NO-HEADER` | 12 | complex measure (≥N VARs / length) without a `/* header */` | info | text | 3 |
| `DAX-USE-DIVIDE` | 14 | the `/` operator where `DIVIDE()` should be used (division by a **nonzero numeric literal** — `/ 1000` scaling — cannot divide by zero and is not flagged; `/ 0` still is) | warning | text | 2 |
| `DAX-FORMAT-STRING` | 15 | measure with no explicit `formatString` | warning | catalog | 2 |
| `DAX-NO-FLOAT-KEYS` | 16 | relationship key column typed `double` | info | model | 2 |
| `DAX-HIDE-FK-COLUMNS` | 17 | visible foreign-key (relationship) column | info | model | 2 |
| `DAX-KEY-SUMMARIZEBY-NONE` | 18 | numeric key column that auto-aggregates (`summarizeBy` ≠ none) | info | model | 2 |
| `DAX-DISPLAY-FOLDERS` | 19 | measure-heavy table with no display folders | info | model | 2 |
| `DAX-AUTO-DATETIME` | 21 | auto date/time artifacts (`LocalDateTable_*` / `DateTableTemplate_*` tables) | warning | model | 2 |
| `DAX-EARLIER-TO-VAR` | 22 | `EARLIER`/`EARLIEST` — the legacy pre-VAR outer-row-context idiom; capture the value in a `VAR` | warning | text | 2 |
| `DAX-VAR-UNDERSCORE` | 27 | `VAR <name>` declaration without a leading underscore (single or double both pass) | warning | text | 2 |
| `DAX-NO-GRATUITOUS-CALCULATE` | 29 | single-argument `CALCULATE`/`CALCULATETABLE` in a measure — no filter manipulation. Skips calls inside row-context functions (§30 case 3 context transition) and defers nested single-arg chains to the innermost call | warning | text | 2 |
| `DAX-DEAD-INACTIVE-RELATIONSHIP` | 23 | inactive relationship never activated by `USERELATIONSHIP()` in any measure / calc column / calc item | warning | model+text | 2 |
| `DAX-IFERROR-WRAPPING` | 24 | `IFERROR(<arithmetic>, ...)` — hides real errors and is slower than `DIVIDE()` | warning | text | 2 |
| `DAX-MEASURE-DESCRIPTION` | 25 | visible measure with no description (TMDL `///` doc-comment / `.bim` `description`) | info | catalog | 3 |

## Agent-judgment rules — emit in `agent_review`

| Rule ID | § | Why judgment (tool still detects the construct) |
|---|---|---|
| `DAX-KEEPFILTERS-NEEDED` | 5 | whether `KEEPFILTERS` is required depends on intended filter shape. Detected per top-level `CALCULATE` filter argument: a bare `Table[Col] <op>` predicate not wrapped in `KEEPFILTERS(...)`. |
| `DAX-STAR-SCHEMA` | 6 | whether a snowflake *should* be flattened is a modeling call. |
| `DAX-CONTEXT-TRANSITION` | 9 | whether an iterator's context transition is *wrong* needs intent. |
| `DAX-SIMPLE-FUNCTIONS` | 10 | "prefer simple functions / CALCULATE only when needed" is stylistic judgment. |
| `DAX-VALIDATION` | 11 | base/slicer/edge-case/control-total validation is a process, not static. Emits ONE model-level item (object = model name) with the non-trivial-measure count + example names — never one per measure. |
| `DAX-IMPLICIT-MEASURE` | 20 | whether a visible auto-aggregating column should become an explicit measure is a modeling call. |

## Hybrid-tier coverage (standards §27–§32)

The 2026-08 hybrid refactor added the variable-first / intentional-CALCULATE tiers as
standards §27–§32. Coverage today:

| Standards § | Rule | Status |
|---|---|---|
| §27 leading-underscore VAR names | `DAX-VAR-UNDERSCORE` | **Implemented** (warning, text): `VAR <name>` without a leading `_`; scans measures, calc columns/tables, calc items. |
| §28 table variables + explicit iterators | `DAX-SIMPLE-FUNCTIONS` (§10, agent) + `DAX-FILTER-TABLE-IN-CALCULATE` (§4) | Partial. `SUMX(FILTER(...))` in an iterator's first argument is explicitly exempt from the §4 rule (the docstring calls it the "§9 iterator idiom"; canon is now §28 — cosmetic docstring cross-ref only). Whether a routine local filter *should* have been a table variable is agent judgment. |
| §29 no gratuitous CALCULATE | `DAX-NO-GRATUITOUS-CALCULATE` | **Implemented** (warning, text): single-argument `CALCULATE`/`CALCULATETABLE` in a measure; row-context occurrences excluded (§30 case 3), nested single-arg chains fire once. |
| §30 intentional CALCULATE (3 allowed uses) | agent judgment | Detect: every `CALCULATE` whose filter arguments use none of `REMOVEFILTERS`/`ALL`/`ALLEXCEPT`/`ALLSELECTED`/time-intel/`USERELATIONSHIP`/`CROSSFILTER`. Emit one agent item per such measure to judge intent. Precision risk: plain predicate overrides (§4 nuance) will fire legitimately — keep in `agent_review`, not findings. |
| §31 magic numbers / inline literals | agent judgment (proposed `DAX-MAGIC-LITERAL`) | **Gap** — deterministic detection is noisy (exempt 0/1/100, DIVIDE scaling per §14). Candidate: info-level item when a measure's non-VAR expression contains numeric/string literals. |
| §32 implicit context transition | `DAX-MEASURE-IN-ITERATOR` (§9, info) + `DAX-CONTEXT-TRANSITION` (agent) | Covered at detection level. Intentional vs accidental remains agent judgment; §32 now requires an intent comment for the allowed form. |

Tier-3 anti-patterns already enforced: `DAX-NO-NESTED-CALCULATE` (§3), `DAX-AUTO-DATETIME`
(§21), `DAX-EARLIER-TO-VAR` (§22), `DAX-IFERROR-WRAPPING` (§24).

## Implementation notes
- **Build the model catalog first** (M1): `{tables, columns-by-table, measures, relationships,
  storage_mode, date_table}`. Most Tier-1 rules need it — especially the measure-vs-column
  distinction (`DAX-MEASURE-NOT-PREFIXED`, `DAX-COLUMN-PREFIXED`).
- Reuse `dax.py`'s comment/string stripping before any text rule so matches don't fire inside
  string literals or comments.
- `DAX-MARKED-DATE-TABLE`: trigger only when the model actually uses time-intelligence functions
  (`DATESYTD`, `SAMEPERIODLASTYEAR`, `DATEADD`, `TOTALYTD`, …) — in measures **or** in
  calculated-column expressions (same §8 requirement either way).
- "Non-trivial" for `DAX-VAR-RETURN` / `DAX-COMPLEX-NO-HEADER`: pick a threshold (e.g. expression
  length or function count) and make it configurable.
