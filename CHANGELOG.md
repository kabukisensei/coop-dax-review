# Changelog

All notable changes to **coop-dax-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

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
