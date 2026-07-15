# Changelog

All notable changes to **coop-dax-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

## [Unreleased]
### Added
- **`explain <RULE-ID>`** — print a rule's rationale (its module docstring), the cited
  standards section excerpt (`§N` sliced from the bundled `docs/standards.md`), and its
  metadata (severity, tier, default-enabled, params). Case-insensitive, with a did-you-mean
  on an unknown id (usage error, exit 2); `--format json` for the agent. Mirrors
  coop-sql-review's `explain` (CLI parity). New `standards.section_text` + `rules.rule_docs`
  helpers.

## [0.16.0] - 2026-07-15
### Added
- Accept `.pbit` (Power BI template) files as input without needing Power BI Desktop (issue #35)
- Emit friendly diagnostic for opaque `.pbix` files (issue #35)

## [0.15.0] — 2026-07-14
### Added
- **`check --diff-against FILE`** — compare this run against a previous run's saved
  `--format json` envelope and print a **new / fixed / persisting** delta to stderr, with
  the new and fixed findings listed and a per-severity summary delta. Built on core 0.6.0's
  shared `delta` engine, keyed on each finding's line-independent fingerprint, so a finding
  that only moved is unchanged. Advisory — it never changes the exit code, and it prints to
  stderr so `--format json` stdout stays a clean machine contract. A missing / non-JSON /
  wrong-tool file is a friendly usage error (exit 2), mirroring `--baseline`. Identical
  flag/semantics to the coop-sql-review twin.

### Changed
- Adopt **coop-review-core 0.6.0** (pin raised to `>=0.6,<0.7`) for the shared `delta`
  engine behind `--diff-against`.

## [0.14.0] — 2026-07-14
### Changed
- Adopt **coop-review-core 0.5.0**: the pin is raised to `coop-review-core>=0.5,<0.6`. Core 0.5.0
  made `add_ignores` raise a friendly `StandardsError` on an unreadable / unwritable / invalid
  ignore target, and removed the dead `apply_plan` upgrade path — this tool's `upgrade` shim no
  longer re-exports it (it was unused; `upgrade`/`update` print the command and never self-apply).

### Fixed
- **TMDL calculated tables in the real export form are now detected and linted** (issue #21): a
  calculated table exports as a plain `table X` header plus `partition X = calculated` with the DAX
  under `source =` — never the inline `table X = <DAX>` form the parser previously supported (which
  the TMDL spec doesn't even define). `_PARTITION_RE`'s source type was discarded and
  `_consume_partition` read only `mode:`, so on every real TMDL model `Table.is_calculated` stayed
  False and `Table.expression` stayed empty. Every rule that opts into `calc_tables=True`
  (`DAX-USE-DIVIDE`, `DAX-NO-NESTED-CALCULATE`, `DAX-EARLIER-TO-VAR`, `DAX-IFERROR-WRAPPING`)
  silently skipped calculated-table DAX, and `DAX-DEAD-INACTIVE-RELATIONSHIP` couldn't see a
  `USERELATIONSHIP()` living in a calculated table (false positives). `_consume_partition` now also
  captures the `source =` expression (inline, a verbatim ``` block, or a multi-line body, with
  `dax_line` at the DAX body's first line), and a `calculated` source sets `is_calculated` +
  `expression` — matching the `.bim` parser. A non-`calculated` source (`m`/`entity`) is left alone.
  The inline `table X = <DAX>` handling is kept for compatibility.
- **An undecodable `.bim` is an error-severity `file_unreadable`, not a masked warning** (issue
  #23): the `.bim` path read with `errors="replace"`, so a decode failure (e.g. a UTF-16 `.bim`
  saved without a BOM) never surfaced as such — the mojibake then failed `json.loads` and was
  recorded as a warning-severity `parse_failed`. A model whose only file was an unreadable `.bim`
  therefore reported `verdict clean` and passed `--strict`, while the identical TMDL case fails
  strict (issue #1). The `.bim` branch now decodes via the shared BOM-aware `decode_tmdl` (so a
  UTF-16-with-BOM `.bim` parses and lints, matching the TMDL leg) and emits the same
  error-severity `file_unreadable` diagnostic on a `UnicodeDecodeError`. Genuine JSON syntax errors
  stay a warning `parse_failed`, matching the TMDL parse-failure policy. The shared `decode_tmdl`
  now also raises on a NUL byte (a UTF-16-no-BOM file), closing the same silent-clean gap on the
  TMDL leg (issue #22).
- **UTF-16 TMDL saved without a BOM no longer parses to an empty catalog certified clean** (issue
  #22): UTF-16-LE/BE of ASCII TMDL is 100% valid UTF-8 (NUL is a legal codepoint), so the previous
  `utf-8-sig` fallback in `decode_tmdl` never raised — the NUL-riddled text matched no parser regex,
  yielding an EMPTY catalog with zero findings, zero diagnostics, `verdict clean`, and `--strict`
  exit 0. `decode_tmdl`'s NUL-byte guard (shared with the issue-#23 `.bim` fix) now raises so the
  error-severity `file_unreadable` path fires. Regression tests pin UTF-16-LE and -BE no-BOM TMDL to
  an error-diagnosed, non-clean verdict. We deliberately do not guess a BOM-less UTF-16 encoding — a
  real UTF-16 export carries a BOM (already handled).
- **TMDL property keywords are matched case-insensitively** (issue #24): `dataType`,
  `dataCategory`, `mode`, `fromColumn`, `toColumn`, `crossFilteringBehavior`, and `isActive` (and
  the `table`/`measure`/`column`/`calculationItem`/`partition`/`relationship` object headers) were
  matched case-sensitively while `isHidden`/`summarizeBy`/`displayFolder`/`formatString` already
  accepted any casing. On hand-written / docs-derived / third-party-emitted TMDL (the MS overview
  writes `datatype:`), a case-varied keyword silently dropped a column's type, dropped a
  relationship's endpoints entirely, or flipped an inactive relationship to active — none marked by
  a diagnostic. All the property/object regexes now carry `re.IGNORECASE`. Mainstream Power BI
  Desktop/PBIP exports (always canonical camelCase) are unaffected.
- **TMDL triple-backtick verbatim expressions are parsed correctly** (issue #25): the TMDL
  serializer emits a verbatim block (`measure X = ` ``` ` … ` ``` `) whenever an expression has
  trailing whitespace or blank lines with whitespace. The parser previously stored the ` ``` `
  fences as part of the measure's DAX, silently LOST a calculated column's whole body (the inline
  ` ``` ` was captured as a truthy expression, skipping the body loop), and — because a verbatim
  body is read "including indentation" — a body line dedented to column 0 truncated the entire
  table, misparsing everything after it. `_parse_measures`, `_parse_calculation_items`, and the
  calculated-column and table-block body loops now detect a bare opening fence, consume the body
  verbatim (ignoring indentation and property-break rules) to the closing fence, and store the
  fence-stripped DAX with `dax_line` pointing at the first body line; a trailing `formatString:` /
  `dataType:` property after the block still binds. Presentation of stored DAX only — fingerprints
  and the JSON contract shape are unchanged.
- **`DAX-VALIDATION` no longer churns its baseline identity on unrelated model growth** (issue #26):
  the one model-level agent-review note embeds a volatile count + example measure names that changed
  whenever ANY measure was added, removed, or renamed anywhere in the model — so a baselined/ignored
  item resurfaced and its baseline entry went stale on every ordinary edit. It now carries a stable
  `fingerprint_key` (the same issue-#14 mechanism the three volatile-message finding rules use), so
  the human note still reports the count/examples but the suppression identity is edit-stable.
  **Migration note:** an existing baseline entry for a `DAX-VALIDATION` item goes stale **once** (its
  fingerprint changed with this fix); it re-records on the next `--write-baseline`.
- **`check --write-baseline` to an unwritable path fails with a friendly one-line error, not a raw
  traceback** (issue #27): the write is guarded and mapped to a `ClickException` (exit 1), matching
  the coop-sql-review twin.
- `--save-ignores` surfaces core 0.5.0's friendly one-line error when the ignore target can't be
  read or written, instead of leaking a raw traceback — the handler now catches `StandardsError`
  alongside the existing `OSError` / `ValueError`.

## [0.13.0] — 2026-07-09
### Added
- **Four new rules** (issue #19), each canon-gated behind a new authored section in
  `docs/standards.md` (§22–§25, bundled copy kept byte-identical; the rule registry now
  advertises 29 rules):
  - **`DAX-EARLIER-TO-VAR`** (§22, warning): `EARLIER`/`EARLIEST` — the legacy pre-VAR
    outer-row-context idiom — in any measure, calculated column, calculated table, or calculation
    item; capture the outer row's value in a `VAR` instead. Masked-text scan; an identifier named
    `[Earlier]` or a comment never fires.
  - **`DAX-DEAD-INACTIVE-RELATIONSHIP`** (§23, warning): an `isActive: false` relationship whose
    endpoint pair is never named by a `USERELATIONSHIP(...)` call anywhere in the model's DAX —
    dead modeling weight or a missed active path. Endpoints match as normalized `Table[Column]`
    pairs in either argument order; a call inside a comment/string doesn't keep one alive.
  - **`DAX-IFERROR-WRAPPING`** (§24, warning): `IFERROR` whose first argument contains arithmetic
    (`+ - * /`) — it hides real errors and is slower than `DIVIDE()` (§14, the paired rule). An
    IFERROR guarding a non-arithmetic error source (e.g. `VALUE(...)`) is left alone.
  - **`DAX-MEASURE-DESCRIPTION`** (§25, info): a **visible** measure with no description (TMDL
    `///` doc-comment / `.bim` `description`) — descriptions are what report authors and
    Copilot/Q&A read. Hidden measures and measures on hidden tables are exempt (same visibility
    rule as `DAX-FORMAT-STRING`).
- **HTML report filter toggles** (issue #17): a row of severity chips (error/warning/info, each
  showing its count) and a rule `<select>` hide/show finding rows client-side; a model card whose
  rows are all filtered out hides too. Implemented as a small inline vanilla-JS `<script>` + CSS —
  the report stays a **self-contained, offline single file** (inline CSS, base64 logo, no CDN, no
  framework). The script is only emitted when there are findings to filter. Presentation only:
  JSON contract and fingerprints unchanged.
- **Agent-review rows are locatable** (issue #17): each agent-review row in the HTML *and* console
  reports now names its `model` and `file:line` (the data was always on `AgentReviewItem`; the
  renderers dropped it) — on a multi-model estate the rows were impossible to place. A model-level
  item (object == model) doesn't repeat the name.
- **Per-rule count table in the SUMMARY** (issue #15): the console `SUMMARY` panel, the Markdown
  report, and the HTML report each gain a **Findings by rule** table (count, severity, rule id;
  sorted count desc then rule id — the family's shared format, twin: coop-sql-review#18) plus a
  closing hint that a noisy rule can be disabled/tuned in `rules.yml`. Presentation only — the
  JSON contract is unchanged.
- **`--save-ignores` picker is grouped by rule × model** (issue #15): a separator heads each
  group, multi-finding groups get an "ignore all N" parent row, and individual findings sit
  nested below — a flat 500-row checkbox was unusable at estate scale. Parent+child overlap is
  deduped by fingerprint.
- **Baseline hint for legacy estates** (issue #15): when a run reports more than 50 findings and
  no `--baseline`/`--write-baseline` is in play, one stderr line points at the
  `--write-baseline baseline.json` ratcheting workflow (never printed into the report itself).
  The earlier `--save-ignores` write-back-shadowing part of this issue was already fixed in
  0.12.0 (core `config_write_path`).
### Changed
- **BREAKING (one-time): the family fingerprint identity rule — JSON `schema_version` → 3**
  (issue #14; landed together with coop-sql-review#16, whose `schema_version` goes 3 → 4 with the
  **identical** construction — the family's identity rules are in lockstep again). A fingerprint
  is now `(rule_id, model, object-or-file-basename, fingerprint_key-or-message, occurrence
  ordinal)`:
  - **`Finding.fingerprint_key`** (optional; empty = the message is the identity, the default):
    the three rules whose display messages embed volatile counts/name-lists now set a stable
    identity core — `DAX-DISPLAY-FOLDERS` ("table has {N} measures..." → `no display folders`),
    `DAX-MARKED-DATE-TABLE` (the time-intel user list → `no marked date table`), and
    `DAX-AUTO-DATETIME` (artifact count + examples → `auto date/time artifacts present`). Adding
    an unrelated measure (or date column) no longer churns these fingerprints, so their baselines
    and `rules.yml` `ignore:` entries survive incidental model growth instead of flooding back
    with an `ignore_stale` ghost. The rendered human message is unchanged.
  - **Occurrence ordinal** (the ratchet fix, from the sql twin): N same-identity occurrences are
    numbered 0, 1, 2, ... in the deterministic sort order (stamped on the full pre-suppression
    result; the first occurrence keeps ordinal 0), so a baseline written before a NEW occurrence
    never silently suppresses it. Deliberate trade-off: adding/removing an occurrence *above* a
    same-identity sibling shifts the sibling's ordinal — it resurfaces (and its old baseline entry
    is reported stale, loudly).
  - An **empty `object`** now falls back to the file **basename** (the sql twin's schema-3 fix),
    so object-less findings in different files can never collapse to one fingerprint.
  - The SARIF `partialFingerprints` KEY stays frozen at the family's `coopFingerprint/v2` (core
    `SARIF_FINGERPRINT_KEY`) — only the values change; the label deliberately survives so GitHub
    code-scanning alert continuity remains an explicit choice.

  **Migration (one-time):** every pre-3 fingerprint stops matching — regenerate baselines and
  saved ignores once: re-run `coop-dax-review check <models> --write-baseline baseline.json`, and
  rebuild the `rules.yml` `ignore:` list with `coop-dax-review check <models> --save-ignores` (or
  delete the stale entries by hand). Until then the old entries surface **loudly** as `baseline` /
  `ignore_stale` warning diagnostics on every run — never a silent mismatch. Same playbook as the
  v0.9.0 schema-2 bump.
- **`DAX-VALIDATION` collapses to ONE model-level agent-review item** (issue #16). The per-measure
  form repeated an identical, un-actionable "confirm §11 validation was performed" note for every
  non-trivial measure (163 of 216 agent items on a real five-model estate), burying the genuinely
  reviewable items. The rule now emits a single item per model (`object` = model name) carrying
  the qualifying-measure count and the first few measure names. **Baseline note:** the old
  per-measure fingerprints disappear and one new model-level fingerprint per model appears —
  regenerate baselines that pinned `DAX-VALIDATION` items (`--write-baseline`), or drop those
  entries (stale ones are reported as `baseline_stale`).
### Fixed
- **Multi-line calculated-column findings and syntax errors now point at the right line**
  (issue #13). `Column` gains `dax_line` (same semantics as `Measure.dax_line`): the TMDL parser
  records where a multi-line calculated column's DAX body starts (and preserves interior blank
  body lines for exact offset→line mapping, mirroring the measure parser); rule findings
  (`helpers.dax_targets`) and structural syntax errors (`syntax_validation`) anchor to it instead
  of the `column X =` declaration line. `.bim` columns keep `line=0` — unchanged. Fingerprints
  exclude line numbers, so no baselines change.
- **`DAX-USE-DIVIDE` no longer flags division by a nonzero numeric literal** (issue #12). The
  scaling idiom — `SUM(Sales[Amount]) / 1000`, `[Total Days] / 7`, a parenthesized or signed
  literal — provably cannot divide by zero, and rewriting it as `DIVIDE()` buys nothing (DIVIDE
  carries the alternate-result branch and is slower). A literal `0`/`0.0` divisor IS a guaranteed
  error and still fires, as do column/measure/expression divisors. Surviving findings keep
  byte-identical messages — no fingerprint churn.
- **`DAX-FILTER-TABLE-IN-CALCULATE` no longer flags a `FILTER` used as an iterator's table
  argument** (issue #11). The scan is now scoped to the CALCULATE **filter arguments only**
  (top-level arguments after the first, per-argument offset rebasing — the same shape as the
  0.9.0 `DAX-KEEPFILTERS-NEEDED` fix), so the endorsed §9 idiom
  `CALCULATE(SUMX(FILTER(Sales, ...), ...), pred)` stays silent while a `FILTER` passed as a
  direct filter argument still fires. Surviving findings keep byte-identical messages/objects, so
  fingerprints don't churn.

## [0.12.0] — 2026-07-09
### Added
- **SARIF output** (`--format sarif`, plus a `--sarif FILE` extra sink that composes with any
  `--format`, like `--html`/`--md`) via `coop-review-core` 0.4.0's shared `to_sarif` emitter — one
  emitter for the whole family, flag semantics identical to `coop-sql-review`. Emits a
  deterministic SARIF 2.1.0 log GitHub code scanning / Azure DevOps turn into inline PR
  annotations on the exact TMDL/`.bim` lines: findings map to their rule id/severity (info ->
  `note`) with the rule title, standards §ref, tier, and category in the rule metadata;
  agent-review items surface as non-blocking `note` results; error-severity diagnostics (genuinely
  malformed DAX, rule crashes, unreadable model files) ride a synthetic `syntax-error` rule so
  broken input still annotates. Each result carries the finding's stable fingerprint as
  `partialFingerprints` (key `coopFingerprint/v2`) so alerts dedupe across runs. The README gains
  a paste-ready GitHub Actions snippet (`--format sarif -o` + `upload-sarif`).
- **Unified config discovery** (via `coop-review-core` 0.4.0's `discover_config`). The config file
  is now found, first hit wins, via: `--config`; the new **`COOP_DAX_REVIEW_CONFIG`** environment
  variable (point a whole CI pipeline at one config without threading `--config` through every
  call site — a set-but-missing path is a friendly usage error, never a silent fallback); a
  **`coop-dax-review.yml`** (the new, preferred tool-named config) or `rules.yml` per directory on
  a **git-style walk from the current directory up to the repo root**; else the conventional spot
  beside the standards file. The tool-named file uses the identical schema and ends the monorepo
  collision where this tool and `coop-sql-review` fought over one shared `rules.yml` — when both
  files sit in one directory the tool-named one wins (with a note on stderr).
### Changed
- **Adopt `coop-review-core` 0.4.0** (the report/CLI-helper/envelope/config-discovery
  consolidation; pyproject now pins `coop-review-core>=0.4,<0.5`). The console chrome, branded
  HTML style + the bundled Cooptimize logo (the duplicated `data/cooptimize-logo.png` is deleted —
  core ships the family's single copy), the machine-JSON envelope + verdict, the diagnostics log,
  the CLI edge helpers (`display_path`/`stdio_interactive`/`use_color`/`write_extra_report`/
  `should_open_report`/`force_utf8_console`), the `syntax_errors` policy, the friendly config
  loader, and the shared `upgrade`/`update` command body (message wording unified across the
  family; commands shlex-joined) now come from core instead of drifting local copies.
  JSON/markdown/HTML/console/log output is **byte-identical** to 0.11.0.
### Fixed
- **`--save-ignores` now writes back to the config file the run actually read** (core
  `config_write_path`) instead of unconditionally creating `./rules.yml`. Previously, saving an
  ignore while a standards-side (or otherwise discovered) config was in effect wrote a brand-new
  `./rules.yml` that silently *shadowed* the real config on the next run — the team's overrides
  stopped applying with no message. `--config` still names the write target explicitly, and writes
  never land inside the installed package.
### Deprecated
- **The shared `rules.yml` config filename.** It keeps working everywhere it worked before (same
  schema, same discovery spots), but every coop-*-review tool reads it; rename yours to
  `coop-dax-review.yml` to make it tool-specific. Discovery prints a one-line nudge on stderr when
  the legacy name is used.

## [0.11.0] — 2026-07-09
### Fixed
- **The TMDL parser now reads the dialect real PBIP/Desktop exports actually write.** Two
  compounding parser gaps made it blind to hidden/summarization metadata in every real export
  (all fixtures were written in a hand-rolled colon dialect no tool emits):
  - **Bare boolean properties parse.** Real TMDL serializes a true boolean as the bare keyword —
    `isHidden` alone on a line; exports never write `isHidden: true`. The bare form is accepted in
    column, measure, and table scope (the colon form still parses), and a bare `isHidden` after a
    multi-line measure/calculated-column body now terminates the DAX like any other property line
    instead of being glued into the expression text.
  - **Property lines no longer reset the column tracker.** Any unrecognized property
    (`lineageTag:`, `formatString:`, `isAvailableInMdx:`, `sourceColumn:`, ...) used to clear the
    current-column binding, and real exports serialize `summarizeBy:` AFTER `lineageTag:` — so
    `summarize_by` (and any recognized property behind an unrecognized one) never bound. Only a
    new child object (column/measure/partition/hierarchy/annotation/...) resets the tracker now.
- **Table-level `isHidden` is captured** (`Table.is_hidden`; TMDL bare + colon forms, and `.bim`),
  and hiding a table now hides its columns and measures for every rule that skips hidden objects:
  `DAX-HIDE-FK-COLUMNS` (§17), `DAX-KEY-SUMMARIZEBY-NONE` (§18 — a hidden key column also can't be
  dragged-and-summed, so hidden keys are now skipped there; whether a key should be hidden stays
  §17's call), `DAX-IMPLICIT-MEASURE` (§20), `DAX-FORMAT-STRING` (§15), and `DAX-DISPLAY-FOLDERS`
  (§19).
- Measured on a real five-model estate, the parser fixes collapse the false-positive walls:
  `DAX-HIDE-FK-COLUMNS` 166 → 0 findings, `DAX-KEY-SUMMARIZEBY-NONE` 204 → 0, and
  `DAX-IMPLICIT-MEASURE` 270 → 1 agent items — every removed one was a false positive on a column
  that IS hidden / DOES set `summarizeBy: none`. All other rules' counts are byte-identical.
  Fixtures now exercise the real dialect (bare `isHidden`, real export property order, a
  table-level `isHidden`), with one colon-form `isHidden: true` fixture pinning the hand-written
  dialect.

## [0.10.1] — 2026-07-08
### Changed
- **Adopt `coop-review-core` 0.3.0.** The tool-local `SCAN_EMPTY` / `SYNTAX_ERROR` diagnostic
  categories and the syntax-ignore directive scanner (`scan_syntax_ignores` / `is_syntax_ignored`)
  now come from core (coop-review-core#1), so the whole family shares one directive grammar instead
  of drifting copies. No behavior change.
### Fixed
- **A corrupt/missing/wrong-tool `--baseline` file is now a friendly usage error (exit 2)** instead
  of silently loading an empty baseline — which used to flood every previously-baselined finding
  back with no explanation (coop-review-core#3). A baseline written by a different tool
  (`coop-sql-review`) is rejected too.

## [0.10.0] — 2026-07-08
### Added
- **DAX syntax errors are now reported as `error`-severity `syntax_error` diagnostics** (parity with
  coop-sql-review's `syntax_error`). A cheap **structural** validation pass runs over every measure
  body and every calculated-column expression and flags genuinely malformed DAX — the kind that
  would import broken into Power BI — that previously passed `check` with **zero** diagnostics while
  the text rules half-analyzed the garbage. It catches: unbalanced parentheses, unbalanced brackets,
  an unterminated string literal, an unterminated block comment, and an empty body. All counting is
  done on `blank_identifiers(mask_dax(dax))`, so parens/brackets/quotes inside an identifier
  (`[Net (USD)]`, `'Sales (2024)'`), a string, or a comment are never miscounted — compliant DAX
  (and the standards' own example measures) stays clean. This is drift **detection**, not a grammar:
  the standards rules still run on whatever parsed. Because the diagnostic is error-severity it flips
  the JSON `verdict` to not-clean and fails `--strict` (exit 2), so a broken measure never passes CI
  as clean.
- **`rules.yml` `syntax_errors:` knob** — `error` (default) | `warning` (demote but keep it visible
  in the JSON) | `off` (drop entirely). A bare unquoted `off` (YAML 1.1 `False`) is accepted.
- **Inline `// coop-dax-review:ignore syntax`** (also `--`) on a syntax error's line or the line
  above silences that one occurrence; a bare / `*` wildcard covers it too. A rule-scoped ignore
  (naming rule ids) does **not** silence a syntax error.
- **Calculated-column and calculated-table DAX is now linted** (issue #5). Every text rule used to
  scan measures only; a `/` division or a nested `CALCULATE` in a calculated column or table went
  unseen, and a calculated table's DAX was parsed and then discarded. `Table.expression` is now
  retained (TMDL inline **and** multi-line `table X =` forms, and `.bim` `partition.source`), and
  `DAX-USE-DIVIDE` (§14) + `DAX-NO-NESTED-CALCULATE` (§3) now fire on calc-column (`Table[Column]`)
  and calc-table (`Table`) expressions. Existing measure findings are byte-identical — no baseline
  churn. Other rules stay measure-only pending per-§ decisions (row context inside a calc column is
  normal, not a smell).
- **Calculation groups are now parsed and linted** (issue #8). `calculationGroup` / `calculationItem`
  blocks (TMDL and `.bim`) — whose DAX is often a model's most intricate (`SELECTEDMEASURE()`
  transforms, time-intel wrappers) — were skipped entirely. Items are captured as first-class
  `CalculationItem`s (kept **out** of `measures`, so naming rules never misfire on item names);
  `DAX-USE-DIVIDE` (§14) and `DAX-NO-NESTED-CALCULATE` (§3) lint item DAX, and time intelligence in
  an item now triggers `DAX-MARKED-DATE-TABLE` (§8). Models without calc groups are byte-identical.
- **Measure `isHidden` and `description` are captured** from both parsers (issue #7 — TMDL `///`
  doc-comment + `isHidden:`, `.bim` `isHidden`/`description`). Two precision refinements follow:
  `DAX-FORMAT-STRING` (§15) skips hidden measures (never rendered → an explicit format buys nothing)
  and `DAX-DISPLAY-FOLDERS` (§19) excludes hidden measures from its threshold. (`description` is
  captured for future use; §12's header requirement is deliberately unchanged.)
- **New rule `DAX-AUTO-DATETIME` (§21, warning)** (issue #10). Flags Power BI auto date/time
  artifacts — the hidden `LocalDateTable_<guid>` / `DateTableTemplate_<guid>` tables the option
  creates per date column — a deterministic signal it was left on. One finding per model. Adds a new
  `docs/standards.md` §21 (bundled copy kept byte-identical); the rule set is now **25 rules**.
- **Corpus crash-guard + Windows-compat test suites** (issue #4, parity with coop-sql-review).
  `tests/test_corpus.py` runs every rule over a synthetic model that exercises all parser features
  (multi-line measures + §12 headers, calc columns/tables, a calculation group, quoted identifiers,
  hidden/documented measures, partitions, active/inactive + bidirectional relationships, a marked
  Date table) and asserts **zero `rule_error` diagnostics** + expected object counts, so a rule
  crash or a parser regression that drops objects can't ship green. `tests/test_windows.py` pins
  CRLF==LF findings + line numbers, ASCII console chrome, and `ensure_ascii` JSON.
### Fixed
- **`mask_dax` now masks an unterminated trailing string or block comment all the way to
  end-of-text.** Previously `mask_dax('IF([X] = "abc, 1, 2)')` masked nothing, leaking the string's
  content into the text-rule scans; an unterminated `/* ...` did the same. Both now run the mask to
  EOF (offsets and newlines still preserved), so the leaked content never reaches a rule.
- **`--strict` and the JSON `verdict` now honor error-severity diagnostics** (parity with
  coop-sql-review v0.6.0). A model file the tool couldn't even read (`file_unreadable`, a rule
  crash, or a `syntax_error`) used to report `verdict.clean: true` and exit 0 under `--strict` —
  the analytics agent read a compromised run as a clean pass. Now any error-severity diagnostic
  makes the verdict not-clean with `highest_severity: "error"` (even with zero findings) and fails
  `--strict` (exit 2). The happy path is unchanged (zero findings + zero diagnostics still exits 0
  and reports clean). `schema_version` stays 2 (additive semantics on existing fields).
- **An undecodable model file is now an error, not a warning.** A `.tmdl` with bad UTF-8 (or UTF-16
  saved without a BOM) previously emitted a `parse_failed` **warning**, so a model whose only file
  was mojibake still passed as clean; it now emits an error-severity `file_unreadable` (the file
  contributed nothing, exactly like an unreadable one) — matching the SQL twin.
- **`bracket_refs` no longer mis-anchors the table qualifier when a quoted table name contains
  brackets.** For a (legal) name like `'Weird[Name]'[Col]`, the old `index("[")` re-scan found the
  bracket *inside* the quoted name, so the real `[Col]` read as bare (`DAX-COLUMN-PREFIXED` could
  false-positive on correctly-qualified code) and a phantom `[Name]` ref was attributed to a
  nonexistent table. The qualifier now anchors to the reference bracket itself; a `[...]` inside a
  quoted name is not surfaced as a phantom ref; and `''`-escaped names (`'O''Brien'[X]`) resolve
  correctly.
- **`DAX-NO-FLOAT-KEYS` (§16) now points its finding at the offending column**, not the
  relationship declaration — the same endpoint-column location its sibling rules `DAX-HIDE-FK-COLUMNS`
  (§17) and `DAX-KEY-SUMMARIZEBY-NONE` (§18) use, so the `file:line` lands where the `dataType` fix
  is made. `object` and `message` are unchanged, so no baseline/ignore churn.
### Performance
- **Masked DAX is cached** (`mask_dax`, plus `blank_brackets`/`blank_quoted_identifiers`/
  `blank_identifiers`). ~13 text rules re-masked the same measure body on every measure each run;
  these pure `str`-keyed functions now memoize (`functools.lru_cache`), collapsing that to one pass
  per distinct expression (~9.5× faster on repeated masking in a micro-benchmark). Output is
  byte-identical — the determinism suite still passes.

## [0.9.0] — 2026-07-01
### Changed
- **Suppressions now cover `agent_review` items** exactly like findings: inline
  `coop-dax-review:ignore` directives, `--baseline` fingerprints, and the `rules.yml` `ignore:`
  list all silence agent-review items too, and `--write-baseline` records their fingerprints. A
  baseline/ignore entry that matches only an agent-review item is not reported as stale. Matches
  the identical change in coop-sql-review.
- **Fingerprints no longer include the file path — `schema_version` 2** (breaking, one-time).
  A finding's `fingerprint` used to hash the cwd-relative display path, so baselines and
  `rules.yml` `ignore:` lists silently stopped matching when the tool ran from a different
  directory or machine. The identity is now `(rule_id, model, object, message)` (agent-review
  items: `(rule_id, model, object, note)`) — path- and line-independent. Two files carrying the
  same rule + qualified object + message are the same logical issue and are suppressed together.
  **Migration:** delete and regenerate baseline files and `rules.yml` `ignore:` lists once
  (re-run `--write-baseline` / `--save-ignores`). Coordinated with `coop-sql-review` (same
  `schema_version` 2).
- **`DAX-NO-NESTED-CALCULATE` now flags only *direct* nesting (§3)** — a `CALCULATE` inside an
  iterator (`SUMX`/`AVERAGEX`/`FILTER`/…) inside a `CALCULATE` is the endorsed §9 per-row
  context-transition idiom; hoisting it into a VAR would change results, so it is no longer
  reported. Nesting through a non-iterator scalar call (e.g. `ROUND`) still fires. The shared
  iterator set also gained the statistical iterators (`PERCENTILEX.INC/EXC`, `STDEVX.P/S`,
  `VARX.P/S`).
- **`DAX-KEEPFILTERS-NEEDED` is now evaluated per top-level `CALCULATE` filter argument (§5)** —
  a sibling `KEEPFILTERS(...)` no longer suppresses a bare boolean predicate next to it, and a
  comparison living inside a nested call (`FILTER`/`ALL`/`MAX`…) no longer triggers it. The
  agent-review note names the offending predicate(s).
- **`DAX-MARKED-DATE-TABLE` also scans calculated columns (§8)** — time intelligence living only
  in a calculated-column expression (e.g. a `TOTALYTD` column) now triggers the marked-Date-table
  check; the finding names the offending columns as `Table[Column]` alongside measures.
### Fixed
- **A lone `"` in a `//`/`--` line comment swallowed a real `/* ... */` header** — the §12 helper
  (`has_block_comment`) didn't consume line comments, so an unpaired quote inside one (an inch
  mark like `5/8"`) started a phantom string literal that blanked a following header block and
  made `DAX-COMPLEX-NO-HEADER` fire on a documented measure. The scanner now consumes all three
  token kinds in one pass, mirroring the DAX masker.

## [0.8.0] — 2026-07-01
### Fixed
- **TMDL measure DAX no longer truncates at `Word:` lines** — the body terminator is
  comment-state-aware and restricted to the finite set of real TMDL measure properties, so the
  standards' own §12 header comment (`Measure:`/`Purpose:`/…) parses intact instead of blinding
  every text rule with a 2-character body.
- **TMDL models group by root directory** (`.SemanticModel`/`definition` root, else the parent
  folder) instead of bare model name: same-named dev/prod models stay distinct and a flat folder
  of `.tmdl` files is one model, not a phantom model per file.
- One unparseable table header is contained as a per-file `parse_failed` diagnostic instead of
  an `AttributeError` zeroing the whole model; UTF-16/undecodable TMDL emits `parse_failed`
  instead of silently reporting the model clean.
- Quoted table identifiers are masked before text scans (`'Actual/Budget'` no longer fires
  `DAX-USE-DIVIDE`; parens in table names no longer skew `DAX-VAR-RETURN` or CALCULATE depth).
- Malformed/mis-encoded `rules.yml` and a missing explicit `--config` are friendly one-line
  usage errors (exit 2); zero models found still emits the full JSON contract and `--strict`
  exits 2; explicitly passed non-`.tmdl`/`.bim` files are called out instead of parsed as a
  phantom `.bim` (with resolved-path dedup so overlapping roots don't double-count).
### Added
- `upgrade --check` restored and the parse progress bar wired (coop-sql-review parity); the rule
  registry raises loudly on a broken rule module and the advertised rule count is pinned by test.

## [0.7.1] — 2026-07-01
### Changed
- **`check --help`** now documents the report-file flags (`--html`/`--md`) and `--save-ignores`
  with worked examples and a short "Report output" / "Ignoring findings" walkthrough, so the flags
  are discoverable from the terminal without reading the README.

## [0.7.0] — 2026-07-01
### Added
- **`rules.yml` `ignore:` list** — a human-readable, fingerprint-matched suppression list that lives
  in the one writable config file (a readable, hand-editable companion to the JSON baseline).
  Filtered before the `--min-severity` floor, like the baseline. An entry that no longer matches a
  current finding is reported as an `ignore_stale` diagnostic so the list self-cleans. Backed by
  `coop-review-core` 0.2.0 (`RuleConfig.ignored_fingerprints`).
- **`check --save-ignores`** — at an interactive terminal, a checkbox of this run's findings (all
  unchecked; opt in to what you want silenced) whose picks are appended to `rules.yml` via core
  `add_ignores`, so the next run silences them. A `rules.yml` in the current directory is now
  auto-discovered with no `--config` flag, so the loop is just "run, `--save-ignores`, re-run".
- **`--html FILE` / `--md FILE` extra report sinks** — write a self-contained HTML and/or Markdown
  report to a named path *in addition* to the main `--format` output (they compose with any format
  and never open a browser). Distinct from `--format html`, which still writes/opens one file.
### Changed
- Bumped the `coop-review-core` dependency floor to `>=0.2.0` (adds the ignore-list config, the
  `add_ignores` writer, and the `IGNORE_STALE` diagnostic category the above features build on).

## [0.6.4] — 2026-06-29
### Fixed
- **Keyword before a bracket ref mis-recorded as the qualifying table** — `bracket_refs` read a DAX
  keyword sitting immediately before a `[...]` (e.g. `RETURN [Measure]`, `x IN [Region]`,
  `NOT [Flag]`) as a `Table[Column]` qualifier, producing a §1 false positive in
  DAX-MEASURE-NOT-PREFIXED and §9 false negatives in DAX-MEASURE-IN-ITERATOR /
  DAX-CONTEXT-TRANSITION. Reserved keywords are now excluded from bare-table matching (a real table
  named with a keyword must be quoted, which still resolves).
- **Parentheses inside column/measure names broke the CALCULATE-depth scan** — DAX-NO-NESTED-CALCULATE
  now blanks bracket-reference contents (length-preserving) before counting parens, so a name like
  `[Net (USD)]` no longer causes a missed nested CALCULATE (FN) or a wrongly-flagged sibling (FP).
- **DAX-DIRECTLAKE-NO-CALC-COL false-positived on composite models** — an explicit import/dual table
  in a mixed-storage model is no longer flagged; the model-level Direct Lake fallback now applies
  only to tables whose own storage mode is blank/unknown.
- **DAX-VAR-RETURN counted a paren inside a bracket name as a function call** — call counting now runs
  over blanked brackets, so `[Amount (USD)]` is not a phantom call.
- **DAX-COMPLEX-NO-HEADER missed headers hidden by string literals** — a `/* */` substring inside a
  quoted string no longer counts as a doc header (string literals are blanked first).
- **DAX-MEASURE-IN-ITERATOR named the wrong iterator** — nested-iterator messages now name the
  immediately-enclosing iterator (tightest span) instead of the outermost.
### Docs
- Added the missing CHANGELOG reference-link definitions for 0.6.1/0.6.2/0.6.3; dropped the
  non-existent "front-matter" config claim from CLAUDE.md/SPEC.md (config is rules.yml only); fixed
  CLAUDE.md's stale "17 rules" to the actual 24.

## [0.6.3] — 2026-06-25
### Fixed
- **Bracket-ref qualifier matching spanned newlines** — `_QUOTED_TABLE_RE`/`_BARE_TABLE_RE` used
  `\s*` between a table identifier and its `[column]`, so `Sales\n[Total]` was wrongly read as the
  qualified column `Sales[Total]` (a false negative for the §1/§9 prefixing rules). Tightened to
  `[ \t]*` so a qualifier must sit on the same line as its bracket (as DAX requires).
- **`.bim` cross-filter compare was case-sensitive** — `crossFilteringBehavior == "bothDirections"`
  now matches case-insensitively (`.lower() == "bothdirections"`), so a `.bim` model classifies
  bidirectional relationships identically to the TMDL parser (DAX-BIDI-RELATIONSHIP fires on both).
### Docs
- `dax_simple_functions` docstring corrected to "three or more times" (matches `_MIN_CALCULATES = 3`).
- `PUBLISHING.md`/`CLAUDE.md` no longer say to bump `version` in `pyproject.toml` — the version is
  single-sourced from `src/coop_dax_review/__init__.py` (hatchling dynamic version).
- `SPEC.md`/`CLAUDE.md` corrected the bundled default to `data/standards.md` (kept byte-identical to
  the authored `docs/standards.md`).

## [0.6.2] — 2026-06-23
### Fixed
- **`mask_dax`**: replaced three-pass comment/string stripping with a single combined
  left-to-right scanner. A `//`/`--`/`/*` inside a string literal (e.g. an image/SVG URL
  `"http://example.com"`) was previously treated as a real comment, blanking out the rest
  of the line and silently hiding real measure/column references from every text-based rule.
  Strings are now consumed as units before any comment marker inside them can match.

## [0.6.1] — 2026-06-21
### Changed
- **Internal de-duplication**: the tool-agnostic infrastructure (progress, diagnostics, the
  severity ordering + finding fingerprint, inline/baseline suppressions, self-update, and the
  rules.yml config layer) now comes from the shared **`coop-review-core`** package (new runtime
  dependency `coop-review-core>=0.1.0`). Behavior, CLI, and the JSON contract are unchanged — fingerprints
  are byte-identical — but a fix to that shared infra now lands once instead of being copy-pasted.

## [0.6.0] — 2026-06-21
### Added
- **Configurable rule thresholds** via `rules.yml` `params:` — `DAX-VAR-RETURN` (`min_functions`),
  `DAX-COMPLEX-NO-HEADER` (`min_vars`), `DAX-DISPLAY-FOLDERS` (`min_measures`), and
  `DAX-SIMPLE-FUNCTIONS` (`min_calculates`) can be retuned without a code change.
- Auto-created **GitHub Releases** (with generated notes) on each `v*` tag.
### Changed
- **Single-sourced the version**: `src/coop_dax_review/__init__.py` is the only place to bump;
  `pyproject.toml` derives it (hatchling dynamic version).
### Internal
- A test pins `docs/standards.md` byte-identical to the bundled `data/standards.md` (so the JSON
  `sha256` provenance can't silently drift). Added this CHANGELOG.

## [0.5.0] — 2026-06-21
### Added
- **Suppressions** for adopting on an existing model: inline `coop-dax-review:ignore <RULE>` comments
  and a fingerprint **baseline** (`--write-baseline` / `--baseline`) that surfaces only new findings.
- Agent JSON: a stable, line-independent `fingerprint` per finding/agent-review item, a
  `schema_version`, and a `verdict` `{clean, highest_severity}`.

## [0.4.0] — 2026-06-21
### Fixed
- A malformed TMDL file no longer crashes the run — it degrades to a `parse_failed` diagnostic.
### Added
- `rules.yml` `enabled: true` force-on + `default_enabled`; a diagnostic for unknown rule ids.
- Scan-progress output; the terminal report lists agent-review items; JSON `models_checked`.
- CI: the publish workflow fails fast if the tag doesn't match the package version.

## [0.3.0] — 2026-06-21
### Changed
- The `--format text` report is now a **sectioned, colorized** report (banner, per-model sections,
  severity badges, a SUMMARY panel). `--color/--no-color`; auto-off when piped (`NO_COLOR` honored).

## [0.2.0] — 2026-06-17
### Added
- A self-contained branded **HTML report** (`--format html`, opens in the browser), `--format
  markdown`, and `-o/--output`. An interactive folder picker when run with no paths in a terminal.
### Changed
- `upgrade`/`update` now **print** the command to run instead of self-applying.

## [0.1.0] — 2026-06-16
### Added
- Initial release: 24 DAX/model-standard rules over TMDL/`.bim` Power BI semantic models, a human
  report, and the machine JSON contract for the company analytics agent. Offline, advisory, never blocks.

[0.13.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.13.0
[0.12.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.12.0
[0.11.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.11.0
[0.10.1]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.10.1
[0.10.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.10.0
[0.9.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.9.0
[0.8.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.8.0
[0.7.1]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.7.1
[0.7.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.7.0
[0.6.4]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.4
[0.6.3]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.3
[0.6.2]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.2
[0.6.1]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.1
[0.6.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.0
[0.5.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.5.0
[0.4.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.4.0
[0.3.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.3.0
[0.2.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.2.0
[0.1.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.1.0
