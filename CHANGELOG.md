# Changelog

All notable changes to **coop-dax-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

## [Unreleased]

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
