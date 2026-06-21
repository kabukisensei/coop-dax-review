"""rules.yml config: enable/disable, severity overrides + validation, off-by-default,
and unknown-rule-id detection."""

import pytest

from coop_dax_review.rules.base import Rule
from coop_dax_review.standards import RuleConfig, StandardsError, apply_config


def _rule(rid: str, *, default_enabled: bool = True, severity: str = "info") -> Rule:
    return Rule(
        id=rid,
        title=rid,
        severity=severity,
        category="c",
        standard_ref="§1",
        tier=1,
        default_enabled=default_enabled,
    )


def test_disabled_rule_is_dropped():
    rules = [_rule("DAX-A"), _rule("DAX-B")]
    out = apply_config(rules, RuleConfig(disabled={"DAX-A"}))
    assert [r.id for r in out] == ["DAX-B"]


def test_off_by_default_rule_excluded_unless_enabled():
    off = _rule("DAX-OFF", default_enabled=False)
    assert apply_config([off], RuleConfig()) == []  # off by default -> excluded
    assert [r.id for r in apply_config([off], RuleConfig(enabled={"DAX-OFF"}))] == ["DAX-OFF"]


def test_severity_override_applied():
    out = apply_config([_rule("DAX-A", severity="info")], RuleConfig(severity_overrides={"DAX-A": "error"}))
    assert out[0].severity == "error"


def test_invalid_severity_raises(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-A:\n    severity: critical\n", encoding="utf-8")
    with pytest.raises(StandardsError):
        RuleConfig.load(cfg)


def test_enabled_true_parsed_as_force_on(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-OFF:\n    enabled: true\n", encoding="utf-8")
    assert RuleConfig.load(cfg).enabled == {"DAX-OFF"}


def test_unknown_rule_ids_detected(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "rules:\n  DAX-REAL:\n    enabled: false\n  DAX-TYPO:\n    enabled: false\n", encoding="utf-8"
    )
    config = RuleConfig.load(cfg)
    assert config.unknown_rule_ids({"DAX-REAL"}) == ["DAX-TYPO"]


def test_params_parsed_and_applied_to_rule(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-VAR-RETURN:\n    params:\n      min_functions: 9\n", encoding="utf-8")
    config = RuleConfig.load(cfg)
    assert config.params == {"DAX-VAR-RETURN": {"min_functions": 9}}
    out = apply_config([_rule("DAX-VAR-RETURN")], config)
    assert out[0].params == {"min_functions": 9}


def test_ctx_param_reads_and_coerces():
    from coop_dax_review.model import ModelCatalog
    from coop_dax_review.rules.base import RuleContext

    rule = _rule("DAX-X")
    rule.params = {"min_functions": "9"}  # YAML may hand us a string
    ctx = RuleContext(rule, ModelCatalog(name="M", file="f"))
    assert ctx.param("min_functions", 3) == 9  # coerced to int, matching the default's type
    assert ctx.param("missing", 3) == 3  # falls back to the default
