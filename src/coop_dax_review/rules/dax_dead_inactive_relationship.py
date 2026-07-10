"""DAX-DEAD-INACTIVE-RELATIONSHIP (§23): no dead inactive relationships.

§23: an inactive relationship (``isActive: false``) exists to be activated on
demand with ``USERELATIONSHIP()``. One that no measure, calculated column,
calculated table, or calculation item ever activates is dead modeling weight —
or a missed active path. We flag each inactive relationship whose endpoint
pair is never named by a ``USERELATIONSHIP(...)`` call anywhere in the model's
DAX.

Matching is precise: a ``USERELATIONSHIP`` call "uses" a relationship only when
its arguments name BOTH endpoint columns (either argument order), compared as
normalized ``Table[Column]`` pairs via ``bracket_refs`` — so a same-named
column on another table can't count. Scans masked DAX, so a call inside a
comment or string never keeps a relationship alive.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import bracket_refs, mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import dax_targets, iter_calls

_USERELATIONSHIP = frozenset({"userelationship"})


def _used_endpoint_pairs(ctx: RuleContext) -> set[frozenset[tuple[str, str]]]:
    """Every endpoint pair named by a USERELATIONSHIP call in any DAX body,
    as frozensets of normalized ``(table, column)`` tuples (order-free)."""
    pairs: set[frozenset[tuple[str, str]]] = set()
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = mask_dax(target.dax)
        for _name, _off, args in iter_calls(text, _USERELATIONSHIP):
            refs = [(normalize(ref.table), normalize(ref.name)) for ref in bracket_refs(args) if ref.table]
            if len(refs) >= 2:
                pairs.add(frozenset(refs[:2]))
    return pairs


def check(ctx: RuleContext) -> list[Finding]:
    inactive = [rel for rel in ctx.catalog.relationships if not rel.is_active]
    if not inactive:
        return []
    used = _used_endpoint_pairs(ctx)
    findings: list[Finding] = []
    for rel in inactive:
        endpoints = frozenset(
            {
                (normalize(rel.from_table), normalize(rel.from_column)),
                (normalize(rel.to_table), normalize(rel.to_column)),
            }
        )
        if endpoints in used:
            continue
        findings.append(
            ctx.finding(
                object=rel.label,
                file=rel.file,
                line=rel.line,
                message=(
                    "inactive relationship is never activated by USERELATIONSHIP() in any "
                    "measure, calculated column, or calculation item — dead modeling weight "
                    "or a missed active path; use it or remove it (§23)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-DEAD-INACTIVE-RELATIONSHIP",
    title="No dead inactive relationships",
    severity="warning",
    category="relationships",
    standard_ref="§23",
    tier=2,
    check=check,
)
