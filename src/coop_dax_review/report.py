"""Render a :class:`Result` several ways: machine JSON (the agent contract), a
human console report, Markdown, and a self-contained HTML page — plus a
diagnostics log. All are deterministic (sorted, sort_keys + ensure_ascii on
JSON, LF newlines) so output is byte-identical across runs and operating
systems; HTML/Markdown are offline (inline CSS, no network) and HTML-escape
all dynamic text.

The tool-agnostic report layer — the ASCII console chrome, the branded HTML
style + the ONE bundled Cooptimize logo, the HTML escaping helpers, and the
machine-JSON envelope — lives in ``coop_review_core.report`` (core issue #9);
this module keeps only what is genuinely tool-shaped: the ``model``-grouped
renderers and this tool's finding/agent-review JSON dicts.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from coop_review_core.report import (
    BADGE,
    BADGE_COLOR,
    HTML_STYLE,
    REPORT_WIDTH,
    SARIF_LEVEL,
    build_envelope,
    chip,
    diagnostic_json,
    envelope_text,
    esc,
    logo_data_uri,
    sty,
    verdict,
)
from coop_review_core.report import log_text as _core_log_text
from coop_review_core.report import to_sarif as _core_to_sarif

from coop_dax_review.engine import Result
from coop_dax_review.finding import SEVERITIES
from coop_review_core.delta import EnvelopeDelta

TOOL = "coop-dax-review"

# Closing hint under the per-rule count table (issue #15): the actionable next
# step when one rule dominates is per-rule, so say so where the counts are.
_RULE_TUNE_HINT = 'disable a noisy rule in rules.yml ("DAX-X: {enabled: false}") or tune its severity there'


def _rule_counts(findings) -> list[tuple[str, str, int]]:
    """Per-rule finding counts as ``(rule_id, severity, count)`` rows, sorted by
    count desc then rule id (deterministic; the family's SUMMARY-table order —
    twin: coop-sql-review#18). A rule that emitted mixed severities (a per-
    finding override) yields one row per severity."""
    counts: dict[tuple[str, str], int] = {}
    for f in findings:
        key = (f.rule_id, f.severity)
        counts[key] = counts.get(key, 0) + 1
    return sorted(((r, s, n) for (r, s), n in counts.items()), key=lambda t: (-t[2], t[0], t[1]))


# The agent JSON contract version. Bump on any breaking change to the shape so a
# consumer can pin/branch on it; additive fields don't require a bump.
# 2: fingerprints dropped the cwd-relative display path from their identity
#    (now rule_id+model+object+message) — baselines and rules.yml ignore lists
#    written under schema 1 must be regenerated once.
# 3: the FAMILY identity rule (issue #14; coop-sql-review#16 is its schema-4 twin —
#    the two tools' fingerprint construction is identical again): identity is
#    (rule_id, model, object-or-file-basename, fingerprint_key-or-message,
#    occurrence ordinal). The optional fingerprint_key gives the volatile-message
#    rules (DAX-DISPLAY-FOLDERS, DAX-MARKED-DATE-TABLE, DAX-AUTO-DATETIME) a stable
#    identity core so unrelated model edits no longer churn their fingerprints; the
#    ordinal (0-based, deterministic sort order) discriminates N occurrences of one
#    logical issue (the baseline ratchet hole); an empty object now falls back to
#    the file basename. ALL fingerprints change: regenerate baselines and rules.yml
#    ignore lists once. The SARIF partialFingerprints KEY stays frozen at
#    "coopFingerprint/v2" (core's default — only the values change).
SCHEMA_VERSION = 3


def _finding_json(f) -> dict:
    """One finding as the JSON dict this tool's envelope carries (keeps the
    tool-specific ``model`` key — core owns only the envelope shape)."""
    return {
        "rule_id": f.rule_id,
        "severity": f.severity,
        "model": f.model,
        "file": f.file,
        "line": f.line,
        "object": f.object,
        "message": f.message,
        "standard_ref": f.standard_ref,
        "fingerprint": f.fingerprint(),  # stable, line-independent identity
    }


def _agent_review_json(a) -> dict:
    return {
        "rule_id": a.rule_id,
        "model": a.model,
        "file": a.file,
        "object": a.object,
        "line": a.line,
        "note": a.note,
        "standard_ref": a.standard_ref,
        "fingerprint": a.fingerprint(),
    }


def to_json(result: Result, *, version: str, standards: dict[str, str]) -> dict:
    """The agent contract: stable keys, sorted, deterministic."""
    return build_envelope(
        tool=TOOL,
        schema_version=SCHEMA_VERSION,
        version=version,
        standards=standards,
        checked_key="models_checked",  # lets the agent tell "clean" from "nothing parsed"
        checked=result.models_checked,
        verdict=verdict(
            result.summary(),
            has_findings=bool(result.findings),
            has_error_diagnostic=any(d.severity == "error" for d in result.diagnostics),
        ),
        findings=[_finding_json(f) for f in result.findings],
        summary=result.summary(),
        agent_review=[_agent_review_json(a) for a in result.agent_review],
        diagnostics=[diagnostic_json(d) for d in result.diagnostics],
    )


def json_text(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """JSON string with a trailing newline, sorted keys, LF line endings."""
    return envelope_text(to_json(result, version=version, standards=standards))


def console_lines(
    result: Result,
    *,
    version: str = "",
    standards: dict[str, str] | None = None,
    color: bool = False,
) -> list[str]:
    """A report-style terminal summary: a banner, one section per model with
    severity-badged findings, then a summary panel. Deterministic with ASCII
    chrome; ``color`` only layers ANSI on top (opt-in, for an interactive
    terminal). Advisory wording throughout."""
    bar = "=" * REPORT_WIDTH
    indent = " " * 9  # aligns continuation lines under the rule id (3 + badge 5 + 1)
    lines: list[str] = []

    # ---- banner ----
    title, subtitle = "coop-dax-review", "DAX / model standards report"
    pad = max(2, REPORT_WIDTH - 2 - len(title) - len(subtitle))
    lines.append(sty(bar, "cyan", color=color))
    lines.append(
        "  " + sty(title, "bold", "cyan", color=color) + " " * pad + sty(subtitle, "dim", color=color)
    )
    lines.append(sty(bar, "cyan", color=color))
    meta = []
    if standards and standards.get("path"):
        meta.append(f"standards: {Path(standards['path']).name}")  # filename only; full path is in the JSON
    meta.append(f"models checked: {result.models_checked}")
    if version:
        meta.append(f"v{version}")
    lines.append("  " + sty("    ".join(meta), "dim", color=color))

    # ---- findings, grouped by model ----
    by_model: dict[str, list] = {}
    for finding in result.findings:
        by_model.setdefault(finding.model, []).append(finding)

    for model in sorted(by_model):
        lines.append("")
        lines.append("  " + sty(model, "bold", color=color))
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for f in by_model[model]:
            badge = sty(
                BADGE.get(f.severity, "     "), BADGE_COLOR.get(f.severity, "blue"), "bold", color=color
            )
            head = f"   {badge} " + sty(f.rule_id, "bold", color=color) + f"  {f.standard_ref}"
            if f.object:
                head += f"   {f.object}"
            lines.append(head)
            if f.line:  # a concrete line; the file alone (line 0) is implied by the model section
                lines.append(indent + sty(f"{f.file}:{f.line}", "dim", color=color))
            for wrapped in textwrap.wrap(f.message, REPORT_WIDTH - 9):
                lines.append(indent + wrapped)

    # ---- agent review (judgment required) — list what was flagged, not just a count ----
    if result.agent_review:
        lines.append("")
        lines.append("  " + sty("Agent review (judgment required)", "bold", color=color))
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for a in result.agent_review:
            head = (
                "   "
                + sty("JUDGE", "cyan", "bold", color=color)
                + " "
                + sty(a.rule_id, "bold", color=color)
                + f"  {a.standard_ref}"
            )
            if a.object:
                head += f"   {a.object}"
            lines.append(head)
            # The section spans all models, so each row names its model and
            # file(:line) — without them a row on a multi-model estate is
            # impossible to locate (issue #17; matches the HTML report).
            loc = f"{a.file}:{a.line}" if a.line else a.file
            lines.append(indent + sty(f"{a.model} - {loc}", "dim", color=color))
            for wrapped in textwrap.wrap(a.note, REPORT_WIDTH - 9):
                lines.append(indent + wrapped)

    # ---- diagnostics (processing problems) — always shown; they explain gaps ----
    if result.diagnostics:
        lines.append("")
        lines.append(
            "  " + sty("Diagnostics (processing problems - analysis may be incomplete)", "bold", color=color)
        )
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for diag in result.diagnostics:
            lines.append("   " + diag.as_line())

    # ---- summary panel ----
    summary = result.summary()
    total = sum(summary.values())
    lines.append("")
    lines.append(sty(bar, "cyan", color=color))
    if total == 0 and not result.diagnostics:
        lines.append("  " + sty("SUMMARY", "bold", color=color) + "    no issues found")
    else:
        segs = [
            sty(f"{summary[s]} {s}", BADGE_COLOR[s], "bold", color=color)
            if summary[s]
            else sty(f"{summary[s]} {s}", "dim", color=color)
            for s in SEVERITIES
        ]
        lines.append("  " + sty("SUMMARY", "bold", color=color) + "    " + "   ".join(segs))
        diag = result.diagnostic_summary()
        if result.agent_review:
            lines.append(
                " " * 13 + sty(f"{len(result.agent_review)} flagged for agent review", "dim", color=color)
            )
        if diag["error"] or diag["warning"]:
            bits = ", ".join(f"{diag[s]} {s}" for s in ("error", "warning") if diag[s])
            lines.append(" " * 13 + sty(f"diagnostics: {bits}", "dim", color=color))
        # Per-rule count table (issue #15): which rules dominate, count desc,
        # so triage doesn't require piping the JSON through jq.
        rule_rows = _rule_counts(result.findings)
        if rule_rows:
            lines.append("")
            lines.append("  " + sty("Findings by rule", "bold", color=color))
            for rule_id, rule_severity, count in rule_rows:
                badge = sty(
                    BADGE.get(rule_severity, "     "),
                    BADGE_COLOR.get(rule_severity, "blue"),
                    "bold",
                    color=color,
                )
                lines.append(f"   {count:>5}  {badge} " + sty(rule_id, "bold", color=color))
            lines.append("  " + sty(_RULE_TUNE_HINT, "dim", color=color))
    lines.append(sty(bar, "cyan", color=color))
    lines.append("  " + sty("Advisory only - nothing was changed or blocked.", "dim", color=color))
    return lines


def to_markdown(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A readable markdown report grouped by model — good for `-o report.md`.

    Deterministic (findings already sorted; LF newlines). Chrome is ASCII;
    rule messages pass through as-authored.
    """
    summary = result.summary()
    lines = [
        "# coop-dax-review report",
        "",
        f"- version: {version}",
        f"- standards: `{standards.get('path', '')}`",
        f"- models checked: {result.models_checked}",
        f"- findings: {summary['error']} error, {summary['warning']} warning, {summary['info']} info",
    ]
    diag = result.diagnostic_summary()
    if diag["error"] or diag["warning"]:
        lines.append(f"- diagnostics: {diag['error']} error, {diag['warning']} warning")
    if result.agent_review:
        lines.append(f"- agent review: {len(result.agent_review)} construct(s) need judgment")
    lines.append("")
    lines.append("_Advisory only - nothing was changed or blocked._")

    rule_rows = _rule_counts(result.findings)
    if rule_rows:
        lines.append("")
        lines.append("## Findings by rule")
        lines.append("")
        lines.append("| Count | Severity | Rule |")
        lines.append("|---:|---|---|")
        for rule_id, rule_severity, count in rule_rows:
            lines.append(f"| {count} | {rule_severity} | `{rule_id}` |")
        lines.append("")
        lines.append(f"_{_RULE_TUNE_HINT}._")

    by_model: dict[str, list] = {}
    for finding in result.findings:
        by_model.setdefault(finding.model, []).append(finding)
    if by_model:
        lines.append("")
        lines.append("## Findings")
        for model in sorted(by_model):
            lines.append("")
            lines.append(f"### `{model}`")
            lines.append("")
            for f in by_model[model]:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                obj = f"{f.object} - " if f.object else ""
                lines.append(f"- `{loc}` **[{f.severity}]** {f.rule_id} ({f.standard_ref}): {obj}{f.message}")

    if result.agent_review:
        lines.append("")
        lines.append("## Agent review (judgment required)")
        lines.append("")
        for a in result.agent_review:
            loc = f"{a.file}:{a.line}" if a.line else a.file
            lines.append(f"- `{loc}` {a.rule_id} ({a.standard_ref}) - {a.object}: {a.note}")

    if result.diagnostics:
        lines.append("")
        lines.append("## Diagnostics (processing problems)")
        lines.append("")
        for d in result.diagnostics:
            lines.append(f"- {d.as_line()}")
    lines.append("")
    return "\n".join(lines)


def _finding_row(f) -> str:
    """One finding as an HTML grid row: chip + (rule, ref, object, location) +
    message. ``data-sev``/``data-rule`` feed the filter toggles (issue #17)."""
    loc = f"{esc(f.file)}:{esc(f.line)}" if f.line else esc(f.file)
    obj = f"{esc(f.object)} &middot; " if f.object else ""
    return (
        f'<div class="f {esc(f.severity)}" data-sev="{esc(f.severity)}" data-rule="{esc(f.rule_id)}">'
        f"{chip(f.severity)}"
        f'<div class="head"><span class="rule">{esc(f.rule_id)}</span> '
        f"({esc(f.standard_ref)}) &middot; {obj}{loc}</div>"
        f'<div class="msg">{esc(f.message)}</div></div>'
    )


def _finding_dict_row(f: dict) -> str:
    """One finding dictionary as an HTML grid row (for EnvelopeDelta items)."""
    sev = str(f.get("severity") or "info")
    rule = str(f.get("rule_id") or "")
    ref = str(f.get("standard_ref") or "")
    file = str(f.get("file") or "")
    line = f.get("line")
    obj = str(f.get("object") or "")
    msg = str(f.get("message") or "")
    loc = f"{esc(file)}:{esc(line)}" if line else esc(file)
    obj_span = f"{esc(obj)} &middot; " if obj else ""
    return (
        f'<div class="f {esc(sev)}" data-sev="{esc(sev)}" data-rule="{esc(rule)}">'
        f"{chip(sev)}"
        f'<div class="head"><span class="rule">{esc(rule)}</span> '
        f"({esc(ref)}) &middot; {obj_span}{loc}</div>"
        f'<div class="msg">{esc(msg)}</div></div>'
    )


# Tool-local additions on top of core's shared HTML_STYLE (still one inline
# <style>, fully offline): the "Findings by rule" summary table (issue #15)
# and the severity/rule filter bar (issue #17).
_EXTRA_STYLE = """
.byrule { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.byrule td { padding: 8px 16px; border-bottom: 1px solid var(--line); }
.byrule tr:last-child td { border-bottom: 0; }
.byrule .count { font-family: var(--mono); text-align: right; width: 5ch; font-weight: 600; }
.byrule .rule { font-family: var(--mono); font-weight: 600; }
.hint { color: var(--muted); font-size: 0.8rem; padding: 10px 16px; border-top: 1px solid var(--line); }
.filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 0 0 14px; }
.filters .label { color: var(--muted); font-size: 0.8rem; }
.fbtn { font: inherit; font-size: 0.8rem; font-weight: 600; padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--card); cursor: pointer; }
.fbtn.error { color: var(--error); background: var(--error-bg); border-color: transparent; }
.fbtn.warning { color: var(--warning); background: var(--warning-bg); border-color: transparent; }
.fbtn.info { color: var(--info); background: var(--info-bg); border-color: transparent; }
.fbtn.off { opacity: 0.35; }
.filters select { font: inherit; font-size: 0.8rem; padding: 4px 8px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--card); color: var(--ink); }
"""

# Filter behavior (issue #17): a clicked severity chip toggles that severity's
# finding rows; the rule <select> narrows to one rule; a model card whose rows
# are all hidden hides too. Plain inline vanilla JS — the report MUST stay a
# self-contained offline single file (no CDN, no framework, no network).
_FILTER_SCRIPT = """<script>
(function () {
  var hidden = {};
  var select = document.getElementById("rulefilter");
  function apply() {
    var rule = select ? select.value : "";
    document.querySelectorAll(".f[data-rule]").forEach(function (row) {
      var show = !hidden[row.getAttribute("data-sev")] &&
        (!rule || row.getAttribute("data-rule") === rule);
      row.style.display = show ? "" : "none";
    });
    document.querySelectorAll(".card").forEach(function (card) {
      var rows = card.querySelectorAll(".f[data-rule]");
      if (!rows.length) return;
      var any = false;
      rows.forEach(function (r) { if (r.style.display !== "none") any = true; });
      card.style.display = any ? "" : "none";
    });
  }
  document.querySelectorAll(".fbtn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sev = btn.getAttribute("data-sev");
      hidden[sev] = !hidden[sev];
      btn.classList.toggle("off", !!hidden[sev]);
      apply();
    });
  });
  if (select) select.addEventListener("change", apply);
})();
</script>"""


def _filter_bar(findings, summary) -> str:
    """The severity-chip + rule-select filter row (issue #17), or ``""`` when
    there is nothing to filter. Deterministic: severities in SEVERITIES order,
    rules sorted; presentation only (the JSON contract is untouched)."""
    if not findings:
        return ""
    chips = "".join(
        f'<button type="button" class="fbtn {s}" data-sev="{s}">{summary[s]} {s}</button>'
        for s in SEVERITIES
        if summary[s]
    )
    rules = sorted({f.rule_id for f in findings})
    options = '<option value="">all rules</option>' + "".join(
        f'<option value="{esc(r)}">{esc(r)}</option>' for r in rules
    )
    return (
        '<div class="filters"><span class="label">show:</span>'
        f'{chips}<select id="rulefilter" aria-label="Filter by rule">{options}</select></div>'
    )


def _agent_row(a) -> str:
    """One agent-review item as an HTML row — WITH its model and file:line
    (issue #17): the section spans all models in one card, so without them a
    row on a multi-model estate was impossible to locate. A model-level item
    (``object`` == model) skips the redundant object."""
    loc = f"{esc(a.file)}:{esc(a.line)}" if a.line else esc(a.file)
    obj = f"{esc(a.object)} &middot; " if a.object and a.object != a.model else ""
    return (
        f'<div class="f"><span class="chip info">agent</span>'
        f'<div class="head"><span class="rule">{esc(a.rule_id)}</span> '
        f"({esc(a.standard_ref)}) &middot; {esc(a.model)} &middot; {obj}{loc}</div>"
        f'<div class="msg">{esc(a.note)}</div></div>'
    )


def _byrule_card(findings) -> str:
    """The per-rule count table as one card (issue #15), or ``""``."""
    rows = _rule_counts(findings)
    if not rows:
        return ""
    body = "".join(
        f'<tr><td class="count">{n}</td><td>{chip(s)}</td><td class="rule">{esc(r)}</td></tr>'
        for r, s, n in rows
    )
    hint = f'<div class="hint">{esc(_RULE_TUNE_HINT)}.</div>'
    return f'<h2>Findings by rule</h2><div class="card"><table class="byrule">{body}</table>{hint}</div>'


def to_html(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A self-contained, clean HTML report (inline CSS, no network).

    Deterministic and offline: findings are pre-sorted, no timestamps, all
    dynamic text is HTML-escaped. Findings are grouped by model.
    """
    summary = result.summary()
    logo = logo_data_uri()
    logo_img = f'<img src="{logo}" alt="Cooptimize">' if logo else ""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Cooptimize DAX Review</title>",
        f"<style>{HTML_STYLE}{_EXTRA_STYLE}</style>",
        '</head><body><div class="wrap">',
        f'<header class="brand">{logo_img}<div>'
        "<h1>DAX Review</h1>"
        '<div class="sub">coop-dax-review &middot; Power BI model standards report</div>'
        "</div></header>",
        '<div class="brandbar"></div>',
        f'<div class="meta">version {esc(version)} &middot; standards '
        f"<code>{esc(standards.get('path', ''))}</code> &middot; "
        f"{result.models_checked} model(s) checked</div>",
        '<div class="pills">'
        + "".join(f'<span class="pill {s}">{summary[s]} {s}</span>' for s in SEVERITIES if summary[s])
        + (
            f'<span class="pill">{len(result.agent_review)} agent review</span>'
            if result.agent_review
            else ""
        )
        + "</div>",
        '<div class="advisory">Advisory only - nothing was changed or blocked.</div>',
    ]

    byrule = _byrule_card(result.findings)
    if byrule:
        parts.append(byrule)
    filter_bar = _filter_bar(result.findings, summary)
    if filter_bar:
        parts.append(filter_bar)

    by_model: dict[str, list] = {}
    for finding in result.findings:
        by_model.setdefault(finding.model, []).append(finding)

    if by_model:
        for model in sorted(by_model):
            rows = "".join(_finding_row(f) for f in by_model[model])
            parts.append(f'<div class="card"><div class="file">{esc(model)}</div>{rows}</div>')
    else:
        parts.append('<div class="empty">No issues found.</div>')

    if result.agent_review:
        parts.append("<h2>Agent review (judgment required)</h2>")
        rows = "".join(_agent_row(a) for a in result.agent_review)
        parts.append(f'<div class="card">{rows}</div>')

    if result.diagnostics:
        parts.append("<h2>Diagnostics (processing problems)</h2>")
        rows = "".join(
            f'<div class="f">{chip(d.severity)}'
            f'<div class="head"><span class="rule">{esc(d.category)}</span> &middot; '
            f"{esc(d.file)}{(':' + esc(d.line)) if d.line else ''}</div>"
            f'<div class="msg">{esc(d.message)}</div></div>'
            for d in result.diagnostics
        )
        parts.append(f'<div class="card">{rows}</div>')

    if filter_bar:
        parts.append(_FILTER_SCRIPT)
    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def delta_html(delta: EnvelopeDelta, *, version: str) -> str:
    """A self-contained, branded HTML delta report for run-to-run comparisons."""
    logo = logo_data_uri()
    logo_img = f'<img src="{logo}" alt="Cooptimize">' if logo else ""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Cooptimize DAX Review Delta</title>",
        f"<style>{HTML_STYLE}{_EXTRA_STYLE}</style>",
        '</head><body><div class="wrap">',
        f'<header class="brand">{logo_img}<div>'
        "<h1>DAX Review Delta</h1>"
        '<div class="sub">coop-dax-review &middot; run-to-run progress report</div>'
        "</div></header>",
        '<div class="brandbar"></div>',
        f'<div class="meta">version {esc(version)} &middot; {delta.new_count} new &middot; {delta.fixed_count} fixed &middot; {delta.persisting} unchanged</div>',
    ]
    if delta.standards_changed:
        parts.append(
            f'<div class="advisory">Standards changed ({esc(str(delta.old_standards_sha256)[:10])} &rarr; '
            f"{esc(str(delta.new_standards_sha256)[:10])}) - findings may differ because the rules changed, not the code.</div>"
        )

    def _render_group(findings: list[dict], title: str) -> None:
        if not findings:
            return
        parts.append(f"<h2>{esc(title)} ({len(findings)})</h2>")
        by_model: dict[str, list[dict]] = {}
        for f in findings:
            by_model.setdefault(str(f.get("model") or ""), []).append(f)
        for model in sorted(by_model):
            rows = "".join(_finding_dict_row(f) for f in by_model[model])
            parts.append(f'<div class="card"><div class="file">{esc(model)}</div>{rows}</div>')

    _render_group(delta.new_findings, "New")
    _render_group(delta.fixed_findings, "Fixed")
    if not delta.new_findings and not delta.fixed_findings:
        parts.append('<div class="empty">No changes found.</div>')

    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def log_text(result: Result) -> str:
    """Full diagnostics log for ``--log-file``: every processing problem,
    one per line, deterministically ordered. Empty-safe."""
    return _core_log_text(result.diagnostics, tool=TOOL, checked=result.models_checked, unit="model")


# --- SARIF 2.1.0 (GitHub code scanning / Azure DevOps PR annotations) ----------------

_SARIF_INFO_URI = "https://github.com/kabukisensei/coop-dax-review"
# The synthetic rule core appends to carry error-severity diagnostics (genuinely
# malformed DAX, rule crashes, unreadable model files) as PR-line annotations.
_SARIF_DIAG_DESCRIPTION = (
    "A processing problem: a genuine DAX syntax error, a rule crash, or an unreadable model file."
)


def _sarif_driver_rules() -> list[dict]:
    """This tool's SARIF rule-metadata table (every rule, agent ones included —
    their items surface as non-blocking notes). Mirrors the coop-sql-review
    twin's shape: id/name, the rule title as shortDescription, the default
    severity mapping, and the standards §ref/tier/category as properties."""
    from coop_dax_review.rules import all_rules  # lazy: avoid an import cycle

    return [
        {
            "id": r.id,
            "name": r.id,
            "shortDescription": {"text": r.title},
            "defaultConfiguration": {"level": SARIF_LEVEL.get(r.severity, "note")},
            "properties": {
                "standard_ref": r.standard_ref,
                "tier": r.tier,
                "category": r.category,
            },
        }
        for r in all_rules()
    ]


def to_sarif(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A deterministic single-run SARIF 2.1.0 log (string + trailing LF), via
    core's shared emitter (one emitter for the whole family — never fork it).

    Findings/agent-items/error-diagnostics become ``results`` with SARIF
    ``level`` (error/warning/note), a physical location (the TMDL/.bim file +
    line; the model name travels in the message-bearing finding itself), and
    ``partialFingerprints`` (GitHub uses them to dedupe alerts across runs).
    Agent-review items are non-blocking ``note`` results; warning-severity
    diagnostics are advisory processing notes and are intentionally NOT
    emitted. ``standards`` is accepted for renderer-signature parity (the
    provenance travels in the JSON contract, not the SARIF log).
    """
    del standards  # renderer-signature parity only (see docstring)
    return _core_to_sarif(
        tool_name=TOOL,
        information_uri=_SARIF_INFO_URI,
        version=version,
        driver_rules=_sarif_driver_rules(),
        findings=[
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "message": f.message,
                "fingerprint": f.fingerprint(),
            }
            for f in result.findings
        ],
        agent_review=[
            {
                "rule_id": a.rule_id,
                "note": a.note,
                "file": a.file,
                "line": a.line,
                "fingerprint": a.fingerprint(),
            }
            for a in result.agent_review
        ],
        diagnostics=result.diagnostics,
        diagnostics_rule_description=_SARIF_DIAG_DESCRIPTION,
    )
