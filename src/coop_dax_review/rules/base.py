"""The Rule interface and the context handed to each rule.

A deterministic rule is a small dataclass plus a ``check(ctx) -> [Finding]``
function; an agent-judgment rule provides ``detect(ctx) -> [AgentReviewItem]``
instead (the engine routes those to the ``agent_review`` list rather than
evaluating them). ``RuleContext`` carries the parsed :class:`ModelCatalog` and
stamps the rule's id/severity/standard_ref onto every result so rule modules
stay terse and consistent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.model import ModelCatalog


@dataclass
class Rule:
    """Metadata + the callable that evaluates one standard as a check."""

    id: str
    title: str
    severity: str  # default; a config or the standard may override
    category: str  # short topic, e.g. "naming", "calculate", "relationships"
    standard_ref: str  # section in standards.md, e.g. "§3"
    tier: int
    kind: str = "deterministic"  # "deterministic" | "agent" | "estate"
    default_enabled: bool = True  # off-by-default rules must be turned on in rules.yml
    params: dict[str, Any] = field(default_factory=dict)  # tunables from rules.yml (e.g. thresholds)
    check: Optional[Callable[["RuleContext"], list[Finding]]] = None
    detect: Optional[Callable[["RuleContext"], list[AgentReviewItem]]] = None
    check_estate: Optional[Callable[["EstateContext"], list[Finding]]] = None


class RuleContext:
    """What a rule's ``check``/``detect`` receives: the model catalog plus
    factory helpers that pre-fill the rule's identity onto each result."""

    def __init__(self, rule: Rule, catalog: ModelCatalog) -> None:
        self.rule = rule
        self.catalog = catalog

    @property
    def model(self) -> str:
        return self.catalog.name

    def param(self, name: str, default: Any) -> Any:
        """A per-rule tunable from rules.yml (the rule's ``params:`` block), or
        ``default``. Lets thresholds be retuned without a code change."""
        value = self.rule.params.get(name, default)
        # Be forgiving about YAML types vs the default's type (e.g. "5" -> 5).
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int) and not isinstance(value, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def finding(
        self,
        *,
        object: str,
        message: str,
        file: str | None = None,
        line: int = 0,
        severity: str | None = None,
        fingerprint_key: str = "",
    ) -> Finding:
        """Build a Finding stamped with this rule's id, severity, and ref.

        ``file`` defaults to the model's primary file (for model-level
        findings); a measure-level rule passes the measure's own file.
        A rule whose ``message`` embeds volatile detail (counts, name lists)
        passes a stable ``fingerprint_key`` so its suppression identity survives
        unrelated model edits (issue #14); everything else leaves it empty
        (message = identity).
        """
        return Finding(
            rule_id=self.rule.id,
            severity=severity or self.rule.severity,
            model=self.catalog.name,
            file=file if file is not None else self.catalog.file,
            line=line,
            object=object,
            message=message,
            standard_ref=self.rule.standard_ref,
            fingerprint_key=fingerprint_key,
        )

    def review(
        self,
        *,
        object: str,
        note: str,
        file: str | None = None,
        line: int = 0,
        fingerprint_key: str = "",
    ) -> AgentReviewItem:
        """Build an agent-review item stamped with this rule's id and ref."""
        return AgentReviewItem(
            rule_id=self.rule.id,
            model=self.catalog.name,
            file=file if file is not None else self.catalog.file,
            object=object,
            line=line,
            note=note,
            standard_ref=self.rule.standard_ref,
            fingerprint_key=fingerprint_key,
        )

class EstateContext:
    """What an estate-level rule receives: all catalogs and factory helpers."""

    def __init__(self, rule: Rule, catalogs: list[ModelCatalog]) -> None:
        self.rule = rule
        self.catalogs = catalogs

    def param(self, name: str, default: Any) -> Any:
        value = self.rule.params.get(name, default)
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int) and not isinstance(value, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def finding(
        self,
        *,
        models: str,
        object: str,
        message: str,
        file: str | None = None,
        line: int = 0,
        severity: str | None = None,
        fingerprint_key: str = "",
    ) -> Finding:
        return Finding(
            rule_id=self.rule.id,
            severity=severity or self.rule.severity,
            model=models,
            file=file or "",
            line=line,
            object=object,
            message=message,
            standard_ref=self.rule.standard_ref,
            fingerprint_key=fingerprint_key,
        )
