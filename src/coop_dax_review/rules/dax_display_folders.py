"""DAX-DISPLAY-FOLDERS (§19): measure-heavy tables should use display folders.

§19: a table carrying many measures with no display folders is hard to navigate.
We flag a table that has more than ``_MIN_MEASURES`` measures none of which set a
``displayFolder``. The threshold is a configurable module constant. One finding
per table.
"""

from __future__ import annotations

from collections import defaultdict

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import Rule, RuleContext

# More than a handful of measures with zero display folders is where navigation
# starts to hurt; conservative so small tables are never nagged.
_MIN_MEASURES = 5


def check(ctx: RuleContext) -> list[Finding]:
    by_table: dict[str, list] = defaultdict(list)
    for measure in ctx.catalog.measures:
        by_table[normalize(measure.table)].append(measure)
    tables = {normalize(t.name): t for t in ctx.catalog.tables}

    findings: list[Finding] = []
    for table_key, measures in by_table.items():
        if len(measures) <= _MIN_MEASURES:
            continue
        if any(m.display_folder.strip() for m in measures):
            continue  # at least one folder in use — author is organizing
        table = tables.get(table_key)
        findings.append(
            ctx.finding(
                object=table.name if table else (measures[0].table or table_key),
                file=table.file if table else measures[0].file,
                line=table.line if table else 0,
                message=(
                    f"table has {len(measures)} measures and no display folders — group them into "
                    "display folders so the model is navigable (§19)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="DAX-DISPLAY-FOLDERS",
    title="Measure-heavy tables use display folders",
    severity="info",
    category="modeling",
    standard_ref="§19",
    tier=2,
    check=check,
)
