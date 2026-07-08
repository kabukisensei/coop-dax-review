"""DAX-NO-FLOAT-KEYS (§16): relationship keys should not be floating-point.

§16: a relationship key column typed ``double`` can fail to match exactly,
silently dropping rows from the join — use ``int64`` or ``decimal``. We look up
each relationship endpoint's column in the catalog and flag any endpoint typed
``double``. The finding points at the **column definition** (``table.file`` /
``column.line``) — where the ``dataType`` fix is made — not the relationship
declaration, matching the sibling endpoint rules ``DAX-HIDE-FK-COLUMNS`` (§17)
and ``DAX-KEY-SUMMARIZEBY-NONE`` (§18). One finding per offending endpoint.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    by_key = {(normalize(t.name), normalize(c.name)): (t, c) for t in ctx.catalog.tables for c in t.columns}
    findings: list[Finding] = []
    for rel in ctx.catalog.relationships:
        for table, column in ((rel.from_table, rel.from_column), (rel.to_table, rel.to_column)):
            entry = by_key.get((normalize(table), normalize(column)))
            if entry is None:
                continue
            tbl, col = entry
            if col.data_type.lower() == "double":
                findings.append(
                    ctx.finding(
                        # object + message stay byte-identical (fingerprint is line/path-
                        # independent => no baseline churn); only file/line move to the
                        # column definition, where the dataType change is actually made.
                        object=f"{table}[{column}]",
                        file=tbl.file,
                        line=col.line,
                        message=(
                            f"relationship key '{table}[{column}]' is typed double — "
                            "floating-point keys can fail to match exactly; use int64 or "
                            "decimal (§16)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="DAX-NO-FLOAT-KEYS",
    title="Relationship key columns are not floating-point",
    severity="info",
    category="datatypes",
    standard_ref="§16",
    tier=2,
    check=check,
)
