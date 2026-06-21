# Changelog

All notable changes to **coop-dax-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

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

[0.6.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.6.0
[0.5.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.5.0
[0.4.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.4.0
[0.3.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.3.0
[0.2.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.2.0
[0.1.0]: https://github.com/kabukisensei/coop-dax-review/releases/tag/v0.1.0
