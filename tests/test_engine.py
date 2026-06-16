"""Engine: rule execution, error isolation, severity filtering, summary."""

from coop_dax_review.engine import run_rules
from coop_dax_review.model import ModelCatalog
from coop_dax_review.rules.base import Rule, RuleContext


def _emit_rule(severity: str) -> Rule:
    def check(ctx: RuleContext):
        return [ctx.finding(object="[M]", message=f"{severity} hit", line=1)]

    return Rule(
        id=f"TEST-{severity.upper()}",
        title="t",
        severity=severity,
        category="test",
        standard_ref="§0",
        tier=1,
        check=check,
    )


def _boom_rule() -> Rule:
    def check(ctx: RuleContext):
        raise ValueError("kaboom")

    return Rule(
        id="TEST-BOOM", title="t", severity="warning", category="test", standard_ref="§0", tier=1, check=check
    )


def _catalogs():
    return [ModelCatalog(name="A", file="A.tmdl"), ModelCatalog(name="B", file="B.tmdl")]


def test_runs_every_rule_over_every_model():
    result = run_rules(_catalogs(), [_emit_rule("warning")])
    assert len(result.findings) == 2  # one per model
    assert result.models_checked == 2


def test_buggy_rule_is_isolated_and_surfaced_as_diagnostic():
    result = run_rules(_catalogs(), [_emit_rule("info"), _boom_rule()])
    assert len(result.findings) == 2  # the good rule still produced findings
    rule_errors = [d for d in result.diagnostics if d.category == "rule_error"]
    assert {d.rule_id for d in rule_errors} == {"TEST-BOOM"}
    assert all(d.severity == "error" and "kaboom" in d.message for d in rule_errors)


def test_summary_and_severity_filter():
    result = run_rules(_catalogs(), [_emit_rule("error"), _emit_rule("warning"), _emit_rule("info")])
    assert result.summary() == {"error": 2, "warning": 2, "info": 2}
    warn_plus = result.filtered("warning")
    assert {f.severity for f in warn_plus.findings} == {"error", "warning"}


def test_findings_sorted_deterministically():
    result = run_rules(_catalogs(), [_emit_rule("warning")])
    keys = [f.sort_key() for f in result.findings]
    assert keys == sorted(keys)
