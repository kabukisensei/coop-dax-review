"""DAX-DISPLAY-FOLDERS (§19): measure-heavy tables should use display folders.

§19: a table carrying many measures with no display folders is hard to navigate.
We flag a table that has more than ``_MIN_MEASURES`` measures none of which set a
``displayFolder``. The threshold is a configurable module constant. One finding
per table.

**Hidden** measures (``isHidden: true``) are excluded from the count: they don't
appear in the field list, so they neither add navigation burden nor need a
folder (issue #7 precision refinement). Measures on a **hidden table** are
excluded the same way — hiding a table removes its measures from the field list.
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
    hidden_tables = ctx.catalog.hidden_tables
    by_table: dict[str, list] = defaultdict(list)
    for measure in ctx.catalog.measures:
        if measure.is_hidden or normalize(measure.table) in hidden_tables:
            continue  # hidden measures aren't in the field list — exclude from §19
        by_table[normalize(measure.table)].append(measure)
    tables = {normalize(t.name): t for t in ctx.catalog.tables}

    min_measures = ctx.param("min_measures", _MIN_MEASURES)  # tunable in rules.yml
    findings: list[Finding] = []
    for table_key, measures in by_table.items():
        if len(measures) <= min_measures:
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
                # The measure COUNT churns on any measure add/remove; the identity is
                # "this table has no display folders" (issue #14 — volatile-message rule).
                fingerprint_key="no display folders",
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
