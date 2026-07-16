"""DAX-UNUSED-MEASURE: a measure is not used in the report or other expressions.

Agent-judgment rule. Checks if a visible measure is unreferenced by any PBIR
visual (if reports were scanned) AND unreferenced by any DAX expression in the
model itself. A finding is sent to agent review because external "thin" reports
might still rely on the measure.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import AgentReviewItem
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    if ctx.catalog.reports_scanned == 0:
        return []

    items: list[AgentReviewItem] = []
    
    # 1. Gather all fields referenced in the local report
    def _norm(s: str) -> str:
        while len(s) >= 2 and s[0] in "'\"[" and s[-1] in "'\"]":
            s = s[1:-1].strip()
        return s.lower()
        
    report_used = set()
    for ref in ctx.catalog.report_refs:
        match = re.match(r"^([^\[]+)\[(.*)\]$", ref.field)
        if match:
            # We only track the property (measure name) here for simplicity,
            # as measure names are globally unique in a model.
            report_used.add(_norm(match.group(2)))
            
    # 2. Gather all measure names used inside DAX expressions within the model
    model_used = set()
    # Simple regex to extract `[MeasureName]` from DAX strings
    # This might slightly over-match (e.g. columns), but that's safe (reduces false positives).
    dax_ref_re = re.compile(r"\[([^\]]+)\]")
    
    def extract_refs(dax: str):
        for match in dax_ref_re.finditer(dax):
            model_used.add(normalize(match.group(1)))

    for m in ctx.catalog.measures:
        extract_refs(m.dax)
    for c in ctx.catalog.calculation_items:
        extract_refs(c.dax)
    for t in ctx.catalog.tables:
        if t.expression:
            extract_refs(t.expression)
        for c in t.columns:
            if c.expression:
                extract_refs(c.expression)

    # 3. Identify visible measures that are completely unreferenced
    for measure in ctx.catalog.measures:
        if measure.is_hidden:
            continue
            
        n_measure = normalize(measure.name)
        if n_measure not in report_used and n_measure not in model_used:
            items.append(
                ctx.review(
                    object=f"[{measure.name}]",
                    file=measure.file,
                    line=measure.line,
                    note=(
                        f"measure '[{measure.name}]' is not referenced by any local report visual "
                        "or any DAX expression in this model. Is it unused and safe to remove, "
                        "or is it required by an external thin report?"
                    ),
                )
            )

    return items


RULE = Rule(
    id="DAX-UNUSED-MEASURE",
    title="Measure appears unused (no report or DAX references)",
    severity="info",
    category="cleanup",
    standard_ref="§CLEANUP",
    tier=3,
    kind="agent",
    detect=detect,
)
