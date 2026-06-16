"""DAX-NO-FLOAT-KEYS (§16): relationship keys should not be floating-point.

§16: a relationship key column typed ``double`` can fail to match exactly,
silently dropping rows from the join — use ``int64`` or ``decimal``. We look up
each relationship endpoint's column data type in the catalog and flag any
endpoint typed ``double``. One finding per offending endpoint column.
"""

from __future__ import annotations

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext


def _data_types(ctx: RuleContext) -> dict[tuple[str, str], str]:
    """``{(normalized table, normalized column): data_type}`` for the model."""
    out: dict[tuple[str, str], str] = {}
    for table in ctx.catalog.tables:
        for column in table.columns:
            out[(normalize(table.name), normalize(column.name))] = column.data_type
    return out


def check(ctx: RuleContext) -> list[Finding]:
    types = _data_types(ctx)
    findings: list[Finding] = []
    for rel in ctx.catalog.relationships:
        for table, column in ((rel.from_table, rel.from_column), (rel.to_table, rel.to_column)):
            data_type = types.get((normalize(table), normalize(column)), "")
            if data_type.lower() == "double":
                findings.append(
                    ctx.finding(
                        object=f"{table}[{column}]",
                        file=rel.file,
                        line=rel.line,
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
