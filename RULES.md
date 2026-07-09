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

## Agent-judgment rules — emit in `agent_review`

| Rule ID | § | Why judgment (tool still detects the construct) |
|---|---|---|
| `DAX-KEEPFILTERS-NEEDED` | 5 | whether `KEEPFILTERS` is required depends on intended filter shape. Detected per top-level `CALCULATE` filter argument: a bare `Table[Col] <op>` predicate not wrapped in `KEEPFILTERS(...)`. |
| `DAX-STAR-SCHEMA` | 6 | whether a snowflake *should* be flattened is a modeling call. |
| `DAX-CONTEXT-TRANSITION` | 9 | whether an iterator's context transition is *wrong* needs intent. |
| `DAX-SIMPLE-FUNCTIONS` | 10 | "prefer simple functions / CALCULATE only when needed" is stylistic judgment. |
| `DAX-VALIDATION` | 11 | base/slicer/edge-case/control-total validation is a process, not static. Emits ONE model-level item (object = model name) with the non-trivial-measure count + example names — never one per measure. |
| `DAX-IMPLICIT-MEASURE` | 20 | whether a visible auto-aggregating column should become an explicit measure is a modeling call. |

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
