"""DAX-VAR-UNDERSCORE (§27): local variables carry a leading underscore.

§27: every local variable MUST be named with a leading underscore (``_Name``).
The prefix makes variables instantly distinguishable from column references
(``Table[Column]``) and measure references (``[Measure]``) and keeps the
step-by-step dependency chain obvious when reading a measure top to bottom.
(DAX for Humans writes these ``__Table`` / ``__Result`` — a double underscore —
but any leading underscore satisfies the standard.)

Detection is a masked-text scan for ``VAR <name> =`` declarations where
``<name>`` does not start with ``_``, over every DAX-bearing object (measures,
calculated columns, calculated tables, calculation items): §27 says "every
local variable", so the rule opts into all of them. Comments/strings are
masked and identifier contents blanked first, so ``VAR`` inside a string or a
column named ``[VAR Amount]`` can never fire. One finding per declaration, at
the declaration's line.
"""

from __future__ import annotations

import re

from coop_dax_review.finding import Finding
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import Rule, RuleContext
from coop_dax_review.rules.helpers import blank_identifiers, dax_targets, line_at

_VAR_DECL_RE = re.compile(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.IGNORECASE)


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in dax_targets(ctx.catalog, calc_columns=True, calc_tables=True, calc_items=True):
        text = blank_identifiers(mask_dax(target.dax))
        for match in _VAR_DECL_RE.finditer(text):
            name = match.group(1)
            if name.startswith("_"):
                continue  # single (this standard) or double (DAX for Humans) prefix
            findings.append(
                ctx.finding(
                    object=target.object,
                    file=target.file,
                    line=line_at(target, match.start()),
                    message=(
                        f"VAR '{name}' has no leading underscore — name local variables "
                        f"_{name} so they are distinguishable from column and measure "
                        "references at a glance (§27)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="DAX-VAR-UNDERSCORE",
    title="Local variables carry a leading underscore",
    severity="warning",
    category="naming",
    standard_ref="§27",
    tier=2,
    check=check,
)
