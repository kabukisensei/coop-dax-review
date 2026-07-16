"""DAX-BROKEN-FIELD-REF: report visuals reference fields that do not exist.

When a PBIR report sits alongside the semantic model, we extract its visual
bindings. This rule warns if a visual references a table[column] or
table[measure] that the model does not contain (a broken visual).
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    # Pre-compute valid entity names
    valid_tables = ctx.catalog.table_names
    valid_columns = ctx.catalog.column_names
    valid_measures = ctx.catalog.measure_names

    # Track what we already reported to deduplicate identical breaks in the same visual file
    reported = set()

    for ref in ctx.catalog.report_refs:
        # A ref field looks like "table[column]". We parse it.
        # Handle cases like "'Table Name'[Column Name]" or "Table[Measure]"
        match = re.match(r"^([^\[]+)\[(.*)\]$", ref.field)
        if not match:
            continue

        entity = match.group(1).strip()
        prop = match.group(2).strip()

        # Strip quotes/brackets for normalization
        def _norm(s: str) -> str:
            while len(s) >= 2 and s[0] in "'\"[" and s[-1] in "'\"]":
                s = s[1:-1].strip()
            return s.lower()

        n_entity = _norm(entity)
        n_prop = _norm(prop)

        # Is it broken?
        is_broken = False
        if n_entity not in valid_tables:
            is_broken = True
        elif n_prop not in valid_columns and n_prop not in valid_measures:
            is_broken = True

        if is_broken:
            # deduplicate identical bindings per visual file to reduce noise
            dedup_key = (ref.visual_file, n_entity, n_prop)
            if dedup_key not in reported:
                reported.add(dedup_key)
                findings.append(
                    ctx.finding(
                        object=ref.field,
                        file=ref.visual_file,
                        line=ref.line,
                        message=f"report references field '{ref.field}' which does not exist in the model (broken visual).",
                    )
                )

    return findings


RULE = Rule(
    id="DAX-BROKEN-FIELD-REF",
    title="Report visuals reference fields that do not exist",
    severity="warning",
    category="reliability",
    standard_ref="§REL",
    tier=1,
    check=check,
)
