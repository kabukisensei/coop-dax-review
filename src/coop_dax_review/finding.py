"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.

``object`` is the thing flagged: a measure name (``[Sales: Revenue YTD]``),
a table, or a relationship — whatever the rule is about. ``file`` is the TMDL
/ .bim file the object was defined in, and ``line`` its line there (0 when a
model-level construct has no single line).
"""

from __future__ import annotations

from dataclasses import dataclass

# Severity ordering + the line-independent fingerprint live in the shared core;
# re-exported here so the rule modules keep importing them from `finding`.
from coop_review_core.severity import (  # noqa: F401
    SEVERITIES,
    at_or_above,
    severity_rank,
)
from coop_review_core.severity import fingerprint as _fingerprint


@dataclass(frozen=True)
class Finding:
    """One flagged deviation from the standards, at a specific object + line."""

    rule_id: str
    severity: str
    model: str
    file: str
    line: int
    object: str
    message: str
    standard_ref: str

    def sort_key(self) -> tuple:
        return (
            self.model,
            self.file,
            self.line,
            severity_rank(self.severity),
            self.rule_id,
            self.object,
            self.message,
        )

    def fingerprint(self) -> str:
        """Stable identity: ``(rule_id, model, object, message)``. Deliberately
        excludes the line number AND the display path (``file`` is relative to
        the invocation cwd, or absolute — both machine/where-you-ran-it
        specific), so a baseline or ``rules.yml`` ignore written from one
        directory still matches from another. Two files carrying the same
        rule + qualified object + message are the same logical issue —
        suppressing both together is intended."""
        return _fingerprint(self.rule_id, self.model, self.object, self.message)


@dataclass(frozen=True)
class AgentReviewItem:
    """A construct the engine detects but cannot judge — handed to the agent."""

    rule_id: str
    model: str
    file: str
    object: str
    line: int
    note: str
    standard_ref: str

    def sort_key(self) -> tuple:
        return (self.model, self.file, self.rule_id, self.object, self.line, self.note)

    def fingerprint(self) -> str:
        """Stable, line- and path-independent identity (see :meth:`Finding.fingerprint`)."""
        return _fingerprint(self.rule_id, self.model, self.object, self.note)
