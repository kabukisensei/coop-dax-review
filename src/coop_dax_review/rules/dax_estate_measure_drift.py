import re
from collections import defaultdict
from typing import List

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.base import EstateContext, Rule


def _normalize_body(dax: str) -> str:
    # whitespace/comment-insensitive comparison
    # mask_dax blanks comments/strings to spaces. wait! We DO want to compare string literals.
    # The issue says: "compare mask_dax()-normalized bodies (whitespace/comment-insensitive via parsers/dax.py)".
    # Wait, mask_dax blanks string literal content? Let's check mask_dax docstring: "blanked to spaces but every offset and newline preserved."
    # Actually, mask_dax replaces comments and strings. If we use mask_dax, string literal differences are ignored. Is that intended? The issue says: "compare mask_dax()-normalized bodies (whitespace/comment-insensitive via parsers/dax.py)"
    # Then we just remove all whitespace from mask_dax(dax)
    masked = mask_dax(dax)
    return re.sub(r"\s+", "", masked)


def check_estate(ctx: EstateContext) -> List[Finding]:
    findings = []

    # group measures by normalize(name) -> dict[normalized_body, list[model_name]]
    measure_groups = defaultdict(lambda: defaultdict(list))

    for catalog in ctx.catalogs:
        for measure in catalog.measures:
            # wait, if a measure appears twice in the same model? The model is already checked for within-model issues.
            name = normalize(measure.name)
            body = _normalize_body(measure.dax)
            measure_groups[name][body].append(catalog.name)

    for name, bodies in measure_groups.items():
        if len(bodies) > 1:
            models_involved = set(m for sublist in bodies.values() for m in sublist)
            # e.g., 'ModelA <> ModelB'
            model_label = " <> ".join(sorted(models_involved))

            message = f"measure '{name}' has conflicting definitions across models ({model_label})"
            findings.append(
                ctx.finding(models=model_label, object=name, message=message, fingerprint_key=name)
            )

    return findings


RULE = Rule(
    id="DAX-ESTATE-MEASURE-DRIFT",
    title="Measure definition drift",
    severity="warning",
    category="consistency",
    standard_ref="Estate Consistency",
    tier=2,
    kind="estate",
    check_estate=check_estate,
)
