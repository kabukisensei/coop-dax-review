"""The rule engine: run rules over parsed models, collect Findings + Diagnostics.

Advisory contract: a rule that raises must never abort the run — the failure
is captured as a Diagnostic (so it surfaces to the user and can be fixed) and
the other rules still report. Parser diagnostics (files that wouldn't parse)
are merged in too, so coverage gaps are never silent. Output is sorted so
identical inputs yield byte-identical artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from coop_dax_review.diagnostics import RULE_ERROR, Diagnostic
from coop_dax_review.finding import AgentReviewItem, Finding, severity_rank
from coop_dax_review.model import ModelCatalog
from coop_dax_review.rules.base import Rule, RuleContext


@dataclass
class Result:
    """The outcome of a linting run."""

    findings: list[Finding] = field(default_factory=list)
    agent_review: list[AgentReviewItem] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    models_checked: int = 0

    def summary(self) -> dict[str, int]:
        """Counts per severity across all findings."""
        counts = {"error": 0, "warning": 0, "info": 0}
        for finding in self.findings:
            if finding.severity in counts:
                counts[finding.severity] += 1
        return counts

    def diagnostic_summary(self) -> dict[str, int]:
        """Counts per severity across diagnostics (processing problems)."""
        counts = {"error": 0, "warning": 0}
        for diag in self.diagnostics:
            if diag.severity in counts:
                counts[diag.severity] += 1
        return counts

    def filtered(self, min_severity: str) -> "Result":
        """A copy keeping only findings at or above ``min_severity``.

        Diagnostics are always kept in full — a processing error/gap is worth
        knowing about regardless of the finding severity floor.
        """
        threshold = severity_rank(min_severity)
        return Result(
            findings=[f for f in self.findings if severity_rank(f.severity) <= threshold],
            agent_review=list(self.agent_review),
            diagnostics=list(self.diagnostics),
            models_checked=self.models_checked,
        )


def run_rules(catalogs: list[ModelCatalog], rules: list[Rule]) -> Result:
    """Evaluate every rule against every parsed model."""
    result = Result(models_checked=len(catalogs))
    for catalog in catalogs:
        result.diagnostics.extend(catalog.diagnostics)  # parse failures / degradations
        for rule in rules:
            ctx = RuleContext(rule, catalog)
            try:
                if rule.kind == "agent":
                    if rule.detect is not None:
                        result.agent_review.extend(rule.detect(ctx))
                elif rule.check is not None:
                    result.findings.extend(rule.check(ctx))
            except Exception as exc:  # advisory: isolate a buggy rule, but surface it
                result.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        category=RULE_ERROR,
                        file=catalog.file,
                        line=0,
                        message=f"rule raised {type(exc).__name__}: {exc}",
                        rule_id=rule.id,
                    )
                )
    result.findings.sort(key=lambda f: f.sort_key())
    result.agent_review.sort(key=lambda a: a.sort_key())
    result.diagnostics.sort(key=lambda d: d.sort_key())
    return result
