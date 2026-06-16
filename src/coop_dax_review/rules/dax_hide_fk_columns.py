"""DAX-HIDE-FK-COLUMNS (§17): hide foreign-key columns from report view.

§17: a relationship's "many"-side key column (the foreign key) is plumbing and
should be hidden so report authors don't drag a raw key onto a visual. By the
catalog's convention the ``from`` side of a relationship is the many side, so we
check each relationship's ``from_column`` and flag it when it resolves to a
visible (not ``isHidden``) column. One finding per visible FK column.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    # Index columns by (table, column) so we can resolve a relationship endpoint.
    by_key = {(normalize(t.name), normalize(c.name)): (t, c) for t in ctx.catalog.tables for c in t.columns}
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rel in ctx.catalog.relationships:
        key = (normalize(rel.from_table), normalize(rel.from_column))
        if key in seen:
            continue
        entry = by_key.get(key)
        if entry is None:
            continue  # FK column not in the catalog — can't tell
        table, column = entry
        if not column.is_hidden:
            seen.add(key)
            findings.append(
                ctx.finding(
                    object=f"{rel.from_table}[{rel.from_column}]",
                    file=table.file,
                    line=column.line,
                    message=(
                        f"foreign-key column '{rel.from_table}[{rel.from_column}]' is visible — "
                        "hide relationship key columns from report view (§17)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-HIDE-FK-COLUMNS",
    title="Hide foreign-key (relationship) columns",
    severity="info",
    category="modeling",
    standard_ref="§17",
    tier=2,
    check=check,
)
